import json
import threading

import pytest

from almacen_sqlite import AgendaSQLite, ConflictoReserva
from main import cargar_negocio


def reservar(cliente, fecha, hora, servicio="corte", nombre="Laura"):
    return cliente.post("/api/reservas", json={
        "cliente": nombre, "servicio": servicio, "fecha": fecha, "hora": hora, "confirmada": True})


def test_servicios_y_salud(cliente):
    assert cliente.get("/health").json() == {"estado": "ok"}
    assert "corte" in cliente.get("/api/servicios").json()


def test_crear_y_consultar(cliente, miercoles):
    r = reservar(cliente, miercoles, "10:00")
    assert r.status_code == 201
    datos = r.json()
    assert datos["estado"] == "activa" and datos["duracion_minutos"] == 30
    assert cliente.get(f"/api/reservas/{datos['codigo']}").json() == datos


def test_crear_exige_confirmacion(cliente, miercoles):
    r = cliente.post("/api/reservas", json={"cliente": "Ana", "servicio": "corte",
                                            "fecha": miercoles, "hora": "10:00", "confirmada": False})
    assert r.status_code == 400
    assert cliente.get("/api/reservas").json() == []


def test_cruce_de_intervalos_se_rechaza(cliente, miercoles):
    assert reservar(cliente, miercoles, "10:00", "corte_barba").status_code == 201  # 60 min
    r = reservar(cliente, miercoles, "10:30", "corte", "Pedro")                      # 30 min, otra hora
    assert r.status_code == 409
    assert len(cliente.get("/api/reservas").json()) == 1


def test_reserva_contigua_se_acepta(cliente, miercoles):
    assert reservar(cliente, miercoles, "10:00", "corte_barba").status_code == 201
    assert reservar(cliente, miercoles, "11:00", "corte", "Pedro").status_code == 201
    assert reservar(cliente, miercoles, "09:30", "corte", "Ana").status_code == 201


def test_disponibilidad_antes_y_despues(cliente, miercoles):
    antes = cliente.get("/api/disponibilidad", params={"fecha": miercoles, "servicio": "corte"}).json()["horas"]
    reservar(cliente, miercoles, "10:00", "corte_barba")
    despues = cliente.get("/api/disponibilidad", params={"fecha": miercoles, "servicio": "corte"}).json()["horas"]
    assert {"10:00", "10:30"} <= set(antes)
    assert not {"10:00", "10:30"} & set(despues)
    assert "11:00" in despues


def test_modificar_a_hora_libre(cliente, miercoles):
    codigo = reservar(cliente, miercoles, "10:00").json()["codigo"]
    r = cliente.put(f"/api/reservas/{codigo}", json={"servicio": "corte", "fecha": miercoles, "hora": "15:00"})
    assert r.status_code == 200 and r.json()["hora"] == "15:00"


def test_modificar_a_hora_ocupada_conserva_datos(cliente, miercoles):
    codigo = reservar(cliente, miercoles, "10:00").json()["codigo"]
    reservar(cliente, miercoles, "11:00", "corte", "Pedro")
    r = cliente.put(f"/api/reservas/{codigo}", json={"servicio": "corte", "fecha": miercoles, "hora": "11:00"})
    assert r.status_code == 409
    assert cliente.get(f"/api/reservas/{codigo}").json()["hora"] == "10:00"


def test_modificar_puede_solaparse_con_su_propio_intervalo(cliente, miercoles):
    codigo = reservar(cliente, miercoles, "10:00", "corte_barba").json()["codigo"]
    r = cliente.put(f"/api/reservas/{codigo}", json={"servicio": "corte_barba", "fecha": miercoles, "hora": "10:30"})
    assert r.status_code == 200


def test_cancelar_libera_el_intervalo(cliente, miercoles):
    codigo = reservar(cliente, miercoles, "10:00").json()["codigo"]
    assert reservar(cliente, miercoles, "10:00", nombre="Pedro").status_code == 409
    r = cliente.delete(f"/api/reservas/{codigo}")
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    assert reservar(cliente, miercoles, "10:00", nombre="Pedro").status_code == 201
    assert cliente.delete(f"/api/reservas/{codigo}").status_code == 409  # ya cancelada


def test_reserva_inexistente_404(cliente):
    assert cliente.get("/api/reservas/NOEXISTE").status_code == 404
    assert cliente.delete("/api/reservas/NOEXISTE").status_code == 404


@pytest.mark.parametrize("fecha,hora,servicio", [
    ("domingo", "10:00", "corte"),      # negocio cerrado
    ("miercoles", "08:30", "corte"),    # antes de abrir
    ("miercoles", "17:30", "corte_barba"),  # termina después del cierre
    ("miercoles", "10:15", "corte"),    # no respeta el paso de 30 min
    ("miercoles", "10:00", "masaje"),   # servicio desconocido
])
def test_datos_invalidos_422(cliente, miercoles, domingo, fecha, hora, servicio):
    dia = {"miercoles": miercoles, "domingo": domingo}[fecha]
    assert reservar(cliente, dia, hora, servicio).status_code == 422


def test_fecha_inexistente_422(cliente):
    assert cliente.get("/api/disponibilidad", params={"fecha": "2030-99-14", "servicio": "corte"}).status_code == 422


def test_fecha_pasada_422(cliente):
    assert reservar(cliente, "2020-01-06", "10:00").status_code == 422


def test_persistencia_tras_reiniciar(ruta_db, miercoles):
    negocio = cargar_negocio()
    h = negocio["horario"]
    args = dict(apertura=h["apertura"], cierre=h["cierre"], dias=h["dias"], paso=h["paso_minutos"])
    agenda = AgendaSQLite(ruta_db, negocio["servicios"], **args)
    codigo = agenda.crear("Laura", "corte", miercoles, "10:00")["codigo"]
    reiniciada = AgendaSQLite(ruta_db, negocio["servicios"], **args)
    assert reiniciada.consultar(codigo)["cliente"] == "Laura"


def test_solo_una_reserva_gana_el_mismo_intervalo(ruta_db, miercoles):
    negocio = cargar_negocio()
    agenda = AgendaSQLite(ruta_db, negocio["servicios"])
    resultados = []

    def intentar(n):
        try:
            agenda.crear(f"Cliente{n}", "corte", miercoles, "10:00")
            resultados.append("ok")
        except ConflictoReserva:
            resultados.append("conflicto")

    hilos = [threading.Thread(target=intentar, args=(n,)) for n in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert resultados.count("ok") == 1 and resultados.count("conflicto") == 7


def test_migracion_idempotente_y_con_cruce(ruta_db, tmp_path):
    agenda = AgendaSQLite(ruta_db, cargar_negocio()["servicios"])
    registros = [{"codigo": "A1", "cliente": "Laura", "servicio": "corte", "fecha": "2020-01-06",
                  "hora": "10:00", "estado": "activa"}]
    origen = tmp_path / "r.json"
    origen.write_text(json.dumps(registros), encoding="utf-8")
    assert agenda.importar_json(origen) == {"importadas": 1, "ya_existentes": 0}
    assert agenda.importar_json(origen) == {"importadas": 0, "ya_existentes": 1}
    registros.append({**registros[0], "codigo": "A2", "hora": "10:00"})
    origen.write_text(json.dumps(registros), encoding="utf-8")
    with pytest.raises(ConflictoReserva):
        agenda.importar_json(origen)
    assert len(agenda.listar()) == 1  # nada a medias
