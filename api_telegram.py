"""Rutas de FastAPI reservadas para el bot de Telegram (/telegram/...).

Cada petición debe traer:
  X-Clave-Privada:    clave compartida entre el bot y la API (variable API_PRIVATE_KEY).
  X-Usuario-Telegram: identificador numérico de la cuenta de Telegram.

La API usa ese identificador como propietario: cada cuenta solo ve, modifica y
cancela sus propias reservas. Si API_PRIVATE_KEY no está definida, las rutas se
cierran (503) en lugar de quedar abiertas.
"""

import hmac
import os
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from almacen_sqlite import ConflictoReserva, ReservaAjena, ReservaNoEncontrada


class ReservaTelegram(BaseModel):
    cliente: str = Field(min_length=2, max_length=60)
    servicio: str
    fecha: date
    hora: str = Field(pattern=r"^\d{2}:\d{2}$")
    confirmada: bool
    solicitud_id: str = Field(min_length=8, max_length=64)


class CambioTelegram(BaseModel):
    servicio: str
    fecha: date
    hora: str = Field(pattern=r"^\d{2}:\d{2}$")


def usuario_autorizado(x_clave_privada: str = Header(default=""),
                       x_usuario_telegram: str = Header(default="")):
    esperada = os.getenv("API_PRIVATE_KEY", "")
    if not esperada:
        raise HTTPException(503, "La API no tiene configurada API_PRIVATE_KEY")
    if not hmac.compare_digest(x_clave_privada.encode(), esperada.encode()):
        raise HTTPException(401, "Clave privada inválida")
    if not x_usuario_telegram.strip().isdigit():
        raise HTTPException(400, "Falta el identificador de la cuenta de Telegram")
    return x_usuario_telegram.strip()


def responder(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except ReservaNoEncontrada as error:
        raise HTTPException(404, str(error)) from error
    except ReservaAjena as error:
        raise HTTPException(403, str(error)) from error
    except ConflictoReserva as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def crear_router(agenda):
    router = APIRouter(prefix="/telegram", tags=["telegram"])

    @router.get("/reservas")
    def mis_reservas(usuario: str = Depends(usuario_autorizado)):
        return agenda.listar_de(usuario)

    @router.get("/reservas/{codigo}")
    def mi_reserva(codigo: str, usuario: str = Depends(usuario_autorizado)):
        def consultar():
            reserva = agenda.consultar(codigo.upper())
            agenda.exigir_propietario(reserva, usuario)
            return reserva
        return responder(consultar)

    @router.post("/reservas")
    def crear(datos: ReservaTelegram, respuesta: Response, usuario: str = Depends(usuario_autorizado)):
        if not datos.confirmada:
            raise HTTPException(400, "La operación debe estar confirmada")
        resultado = responder(agenda.crear, datos.cliente, datos.servicio,
                              datos.fecha.isoformat(), datos.hora,
                              propietario=usuario, solicitud_id=datos.solicitud_id)
        # 201 si se creó ahora; 200 si era una confirmación repetida de la misma solicitud.
        respuesta.status_code = 200 if resultado.get("repetida") else 201
        return resultado

    @router.put("/reservas/{codigo}")
    def modificar(codigo: str, datos: CambioTelegram, usuario: str = Depends(usuario_autorizado)):
        return responder(agenda.modificar, codigo.upper(), datos.servicio,
                         datos.fecha.isoformat(), datos.hora, propietario=usuario)

    @router.delete("/reservas/{codigo}")
    def cancelar(codigo: str, usuario: str = Depends(usuario_autorizado)):
        return responder(agenda.cancelar, codigo.upper(), propietario=usuario)

    return router
