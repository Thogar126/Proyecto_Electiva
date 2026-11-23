"""Simula una respuesta perdida y comprueba que reintentar no duplica la reserva.

Escenario: el bot confirma una reserva, la API la guarda, pero la respuesta nunca
llega al bot (caída de red). El usuario vuelve a pulsar «Confirmar». Como ambas
peticiones llevan la misma solicitud_id, la API devuelve la reserva ya creada.

Uso:  python simular_respuesta_perdida.py
No usa Telegram ni Groq: levanta una API temporal con una base SQLite desechable.
"""

import json
import os
import tempfile
import threading
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import uvicorn

os.environ["API_PRIVATE_KEY"] = "clave-de-simulacion"
os.environ["RESERVAS_DB"] = str(Path(tempfile.mkdtemp()) / "simulacion.db")

from main import app  # noqa: E402  (después de fijar las variables de entorno)

PUERTO = 8099
BASE = f"http://127.0.0.1:{PUERTO}"


def proximo_lunes():
    dia = date.today() + timedelta(days=7)
    while dia.weekday() != 0:
        dia += timedelta(days=1)
    return dia.isoformat()


def llamar(metodo, ruta, cuerpo=None, usuario="111"):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    peticion = urllib.request.Request(BASE + ruta, data=datos, method=metodo, headers={
        "Content-Type": "application/json", "X-Clave-Privada": os.environ["API_PRIVATE_KEY"],
        "X-Usuario-Telegram": usuario})
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        return respuesta.status, json.loads(respuesta.read())


def main():
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PUERTO, log_level="error"))
    threading.Thread(target=servidor.run, daemon=True).start()
    while not servidor.started:
        time.sleep(0.1)

    cuerpo = {"cliente": "Laura", "servicio": "corte", "fecha": proximo_lunes(), "hora": "10:00",
              "confirmada": True, "solicitud_id": "solicitud-demo-0001"}

    estado, _ = llamar("POST", "/telegram/reservas", cuerpo)
    print(f"1) La API guardó la reserva (HTTP {estado}), pero el bot NO recibe la respuesta.")
    estado, reserva = llamar("POST", "/telegram/reservas", cuerpo)
    print(f"2) El usuario repite Confirmar con la misma solicitud_id -> HTTP {estado}, "
          f"repetida={reserva.get('repetida')}, código {reserva['codigo']}")
    _, mias = llamar("GET", "/telegram/reservas")
    print(f"3) Reservas guardadas para esta cuenta: {len(mias)}")
    assert len(mias) == 1, "Se duplicó la reserva"
    print("Resultado: OK, el reintento no duplicó la reserva.")
    servidor.should_exit = True


if __name__ == "__main__":
    main()
