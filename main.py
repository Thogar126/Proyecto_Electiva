"""API de BarberBot (FastAPI + SQLite).

Todas las operaciones de reservas pasan por AgendaSQLite, que valida horario,
duración e intervalos ocupados dentro de una misma transacción.
"""

import json
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from almacen_sqlite import AgendaSQLite, ConflictoReserva, ReservaNoEncontrada

BASE = Path(__file__).resolve().parent


def cargar_negocio(ruta=None):
    ruta = Path(ruta or BASE / "negocio.json")
    return json.loads(ruta.read_text(encoding="utf-8-sig"))


class ReservaNueva(BaseModel):
    cliente: str = Field(min_length=2, max_length=60)
    servicio: str
    fecha: date
    hora: str = Field(pattern=r"^\d{2}:\d{2}$")
    confirmada: bool


class CambioReserva(BaseModel):
    servicio: str
    fecha: date
    hora: str = Field(pattern=r"^\d{2}:\d{2}$")


def responder(funcion, *args):
    """Convierte las excepciones del almacén en respuestas HTTP."""
    try:
        return funcion(*args)
    except ReservaNoEncontrada as error:
        raise HTTPException(404, str(error)) from error
    except ConflictoReserva as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def crear_app(ruta_db=None):
    negocio = cargar_negocio()
    servicios = negocio["servicios"]
    horario = negocio["horario"]
    ruta_db = Path(ruta_db or os.getenv("RESERVAS_DB") or BASE / "reservas.db")
    ruta_db.parent.mkdir(parents=True, exist_ok=True)

    agenda = AgendaSQLite(
        ruta_db,
        servicios,
        apertura=horario["apertura"],
        cierre=horario["cierre"],
        dias=tuple(horario["dias"]),
        paso=horario["paso_minutos"],
    )
    app = FastAPI(title=f"{negocio['nombre']} · API de reservas", version="1.0.0")
    app.state.agenda = agenda

    @app.get("/health")
    def salud():
        return {"estado": "ok"}

    @app.get("/api/servicios")
    def listar_servicios():
        return servicios

    @app.get("/api/disponibilidad")
    def disponibilidad(fecha: date, servicio: str):
        return responder(agenda.disponibilidad, fecha.isoformat(), servicio)

    @app.get("/api/reservas")
    def listar_reservas():
        return agenda.listar()

    @app.get("/api/reservas/{codigo}")
    def consultar(codigo: str):
        return responder(agenda.consultar, codigo.upper())

    @app.post("/api/reservas", status_code=201)
    def crear(datos: ReservaNueva):
        if not datos.confirmada:
            raise HTTPException(400, "La operación debe estar confirmada")
        return responder(agenda.crear, datos.cliente, datos.servicio,
                         datos.fecha.isoformat(), datos.hora)

    @app.put("/api/reservas/{codigo}")
    def modificar(codigo: str, datos: CambioReserva):
        return responder(agenda.modificar, codigo.upper(), datos.servicio,
                         datos.fecha.isoformat(), datos.hora)

    @app.delete("/api/reservas/{codigo}")
    def cancelar(codigo: str):
        return responder(agenda.cancelar, codigo.upper())

    return app


app = crear_app()
