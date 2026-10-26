"""Pruebas del chatbot con un 'LLM' falso y una API en memoria (sin red)."""
import json
from urllib.error import HTTPError

import pytest

import chatbot_memoria as cm
import consulta_llm as cl
import app_gradio


@pytest.fixture
def api_falsa(cliente, monkeypatch):
    """Redirige las peticiones HTTP del chatbot hacia la API de pruebas."""
    def peticion(metodo, ruta, cuerpo=None):
        r = cliente.request(metodo, ruta, json=cuerpo)
        if r.status_code >= 400:
            raise HTTPError(ruta, r.status_code, "error", {}, __import__("io").BytesIO(r.content))
        return r.json()
    monkeypatch.setattr(cl, "peticion_api", peticion)
    monkeypatch.setattr(cm, "peticion_api", peticion)
    return cliente


def llm_guion(*respuestas):
    cola = list(respuestas)
    return lambda mensajes, clave, modelo: cola.pop(0)


def test_solicitud_en_varios_turnos(api_falsa, miercoles):
    historial = cm.nuevo_historial()
    llm = llm_guion(
        {"accion": "crear", "cliente": "Laura", "servicio": "corte"},
        {"accion": "crear", "fecha": miercoles, "hora": "10:00"},      # el modelo no repite nombre ni servicio
    )
    res, historial, plan = cm.procesar_turno("Quiero un corte, soy Laura", historial, "k", "m", llm=llm)
    assert res["tipo"] == "faltantes" and plan is None
    res, historial, plan = cm.procesar_turno("Para el miércoles a las 10", historial, "k", "m", llm=llm)
    assert res["tipo"] == "confirmacion"
    assert plan == {"accion": "crear", "cliente": "Laura", "servicio": "corte", "fecha": miercoles, "hora": "10:00"}


def test_confirmar_crea_y_luego_cancela(api_falsa, miercoles):
    plan = {"accion": "crear", "cliente": "Laura", "servicio": "corte", "fecha": miercoles, "hora": "10:00"}
    with pytest.raises(ValueError):
        cl.ejecutar(plan)  # sin confirmar no escribe
    assert api_falsa.get("/api/reservas").json() == []
    creada = cl.ejecutar(plan, confirmar=True)["datos"]
    registro = {"plan": plan, "respuesta": creada}
    historial = cm.nuevo_historial() + [{"role": "assistant", "content": json.dumps(registro)}]
    res, historial, plan2 = cm.procesar_turno("cancela mi reserva", historial, "k", "m",
                                              llm=llm_guion({"accion": "cancelar"}))
    assert res["tipo"] == "confirmacion" and plan2["codigo"] == creada["codigo"]  # código tomado del historial
    assert cl.ejecutar(plan2, confirmar=True)["datos"]["estado"] == "cancelada"


def test_servicio_desconocido_se_pide_de_nuevo(api_falsa):
    res, _, _ = cm.procesar_turno("un masaje", cm.nuevo_historial(), "k", "m",
                                  llm=llm_guion({"accion": "crear", "servicio": "masaje", "cliente": "Ana"}))
    assert res["tipo"] == "faltantes" and "masaje" in res["mensaje"]


def test_error_de_api_no_modifica_el_historial(api_falsa):
    historial = cm.nuevo_historial()
    copia = list(historial)
    with pytest.raises(HTTPError):
        cm.procesar_turno("disponibilidad", historial, "k", "m", llm=llm_guion(
            {"accion": "disponibilidad", "servicio": "corte", "fecha": "2030-99-14"}))
    assert historial == copia


def test_interfaz_reiniciar_y_descartar():
    estado = app_gradio.nuevo_estado()
    assert estado["pendiente"] is None and estado["historial"][0]["role"] == "system"
    estado["pendiente"] = {"accion": "cancelar", "codigo": "X"}
    pantalla, nuevo, caja, aviso, _ = app_gradio.descartar(estado)
    assert nuevo["pendiente"] is None and caja == ""
    assert app_gradio.crear_interfaz() is not None
