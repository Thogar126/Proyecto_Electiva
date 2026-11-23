"""Genera los registros T18-T25 (parte del backend) en evidencias/*.txt.

Levanta una API temporal con una base desechable y ejecuta, por HTTP real, las operaciones
de la matriz. NO sustituye las capturas de Telegram: demuestra el efecto real en API y SQLite.
Uso (desde la raíz del repositorio):  python evidencias/verificar_backend.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["API_PRIVATE_KEY"] = "clave-de-verificacion"
DB = Path(tempfile.mkdtemp()) / "verificacion.db"
os.environ["RESERVAS_DB"] = str(DB)

import uvicorn  # noqa: E402
from main import app  # noqa: E402

PUERTO = 8098
BASE = f"http://127.0.0.1:{PUERTO}"
SALIDA = Path(__file__).resolve().parent
log = []


def fecha(dia_semana, desde=7):
    d = date.today() + timedelta(days=desde)
    while d.weekday() != dia_semana:
        d += timedelta(days=1)
    return d.isoformat()


def http(metodo, ruta, cuerpo=None, usuario="111", clave=None):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    cab = {"Content-Type": "application/json", "X-Usuario-Telegram": usuario,
           "X-Clave-Privada": clave or os.environ["API_PRIVATE_KEY"]}
    pet = urllib.request.Request(BASE + ruta, data=datos, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(pet, timeout=10) as r:
            codigo, texto = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        codigo, texto = e.code, e.read().decode()
    cuerpo_resp = json.loads(texto) if texto else None
    log.append(f"[cuenta {usuario}] {metodo} {ruta}" + (f"  cuerpo={json.dumps(cuerpo, ensure_ascii=False)}" if cuerpo else ""))
    log.append(f"    -> HTTP {codigo} {json.dumps(cuerpo_resp, ensure_ascii=False)}")
    return codigo, cuerpo_resp


def sql(consulta="SELECT codigo, cliente, propietario, servicio, fecha, hora, estado FROM reservas ORDER BY fecha, hora"):
    con = sqlite3.connect(DB)
    filas = con.execute(consulta).fetchall()
    con.close()
    log.append(f"SQLite> {consulta}")
    for f in filas or [("(sin filas)",)]:
        log.append("    " + " | ".join(map(str, f)))


def guardar(nombre, titulo):
    cabecera = [f"# {titulo}", f"# Generado el {date.today()} con evidencias/verificar_backend.py (API real + SQLite temporal)", ""]
    (SALIDA / nombre).write_text("\n".join(cabecera + log) + "\n", encoding="utf-8")
    log.clear()


def nueva(cliente, servicio, f, hora, usuario, sid):
    return {"cliente": cliente, "servicio": servicio, "fecha": f, "hora": hora, "confirmada": True, "solicitud_id": sid}


def main():
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PUERTO, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.1)
    lunes, domingo, ayer = fecha(0), fecha(6), (date.today() - timedelta(days=1)).isoformat()

    # T18 crear con confirmación y registro en SQLite
    _, a = http("POST", "/telegram/reservas", nueva("Laura", "corte_barba", lunes, "10:00", "111", "solicitud-T18-A"), "111")
    sql()
    guardar("T18_crear_sqlite.txt", "T18 - Reserva confirmada (cuenta 111) y su fila en SQLite")

    # T22 reserva ajena
    http("GET", f"/telegram/reservas/{a['codigo']}", usuario="222")
    http("PUT", f"/telegram/reservas/{a['codigo']}", {"servicio": "corte", "fecha": lunes, "hora": "15:00"}, "222")
    http("DELETE", f"/telegram/reservas/{a['codigo']}", usuario="222")
    sql()
    guardar("T22_reserva_ajena.txt", "T22 - La cuenta 222 intenta ver/modificar/cancelar la reserva de la 111")

    # T19 cada cuenta ve solo lo suyo
    http("POST", "/telegram/reservas", nueva("Pedro", "corte", lunes, "14:00", "222", "solicitud-T19-B"), "222")
    http("GET", "/telegram/reservas", usuario="111")
    http("GET", "/telegram/reservas", usuario="222")
    guardar("T19_listar_propias.txt", "T19 - Cada cuenta lista solo sus reservas")

    # T20 modificar libre / ocupado / cruce al crear
    http("POST", "/telegram/reservas", nueva("Pedro", "corte", lunes, "10:30", "222", "solicitud-T20-C"), "222")
    http("PUT", f"/telegram/reservas/{a['codigo']}", {"servicio": "corte_barba", "fecha": lunes, "hora": "13:00"}, "111")
    http("PUT", f"/telegram/reservas/{a['codigo']}", {"servicio": "corte_barba", "fecha": lunes, "hora": "14:00"}, "111")
    sql()
    guardar("T20_modificar_y_cruce.txt", "T20 - Cruce al crear (409), modificación a hora libre (200) y a hora ocupada (409, datos conservados)")

    # T21 cancelar y liberar
    http("GET", f"/api/disponibilidad?fecha={lunes}&servicio=corte", usuario="111")
    http("DELETE", f"/telegram/reservas/{a['codigo']}", usuario="111")
    http("GET", f"/api/disponibilidad?fecha={lunes}&servicio=corte", usuario="111")
    sql()
    guardar("T21_cancelar_libera.txt", "T21 - Cancelar propia: estado=cancelada y el intervalo se libera")

    # T23 confirmación repetida
    c = nueva("Laura", "corte", lunes, "16:00", "111", "solicitud-T23-D")
    http("POST", "/telegram/reservas", c, "111")
    http("POST", "/telegram/reservas", c, "111")
    sql("SELECT COUNT(*) AS filas_con_esa_solicitud FROM reservas WHERE solicitud_id='solicitud-T23-D'")
    guardar("T23_confirmacion_repetida.txt", "T23 - La misma solicitud confirmada dos veces no duplica (la 2a responde 200, repetida=true)")

    # T24 entradas inválidas
    base = {"cliente": "Laura", "servicio": "corte", "confirmada": True}
    for n, (f, h) in enumerate([(ayer, "10:00"), (domingo, "10:00"), (lunes, "18:00"), (lunes, "10:15"), ("2030-99-14", "10:00")]):
        http("POST", "/telegram/reservas", {**base, "fecha": f, "hora": h, "solicitud_id": f"solicitud-T24-{n}"}, "111")
    http("POST", "/telegram/reservas", nueva("Laura", "corte", lunes, "10:00", "111", "solicitud-T24-x"), usuario="111", clave="clave-incorrecta")
    sql("SELECT COUNT(*) AS filas_T24 FROM reservas WHERE solicitud_id LIKE 'solicitud-T24-%'")
    guardar("T24_entradas_invalidas.txt", "T24 - Fecha pasada, domingo, fuera de horario, fuera de paso, fecha inexistente y clave incorrecta: nada se guarda")

    # T25 reinicio: nueva instancia de la API sobre la misma base
    srv.should_exit = True
    time.sleep(0.5)
    from almacen_sqlite import AgendaSQLite
    from main import cargar_negocio
    antes = AgendaSQLite(DB, cargar_negocio()["servicios"]).listar_de("222")
    log.append(f"Antes: la API se detiene. Se reconstruye AgendaSQLite sobre la misma base (equivale a reiniciar uvicorn).")
    log.append(f"Reservas de la cuenta 222 tras el reinicio: {len(antes)}")
    for r in antes:
        log.append("    " + json.dumps(r, ensure_ascii=False))
    guardar("T25_reinicio_persistencia.txt", "T25 - Tras reiniciar la API las reservas siguen en SQLite (el historial del bot vive en memoria y se pierde)")
    print("Evidencias generadas en", SALIDA)


if __name__ == "__main__":
    main()
