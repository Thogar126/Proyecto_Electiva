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


# ---------- Telegram: botones, propiedad y errores ----------

import asyncio
from types import SimpleNamespace

import bot_telegram as bt


@pytest.fixture
def api_telegram_falsa(cliente, monkeypatch):
    monkeypatch.setenv("API_PRIVATE_KEY", "k")

    def peticion(metodo, ruta, cuerpo=None, usuario=None):
        cab = cl.cabeceras_telegram(usuario) if usuario is not None else {}
        r = cliente.request(metodo, ruta, json=cuerpo, headers=cab)
        if r.status_code >= 400:
            raise HTTPError(ruta, r.status_code, "error", {}, __import__("io").BytesIO(r.content))
        return r.json()
    monkeypatch.setattr(cl, "peticion_api", peticion)
    monkeypatch.setattr(cm, "peticion_api", peticion)
    return cliente


class MensajeFalso:
    def __init__(self, texto=""):
        self.text = texto
        self.enviados = []

    async def reply_text(self, texto, reply_markup=None):
        self.enviados.append(texto)


def contexto():
    return SimpleNamespace(chat_data={}, bot_data={"clave_modelo": "k", "modelo": "m"})


def actualizacion(texto, usuario=111):
    msg = MensajeFalso(texto)
    return SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=usuario)), msg


def con_pendiente(ctx, miercoles, sid="solicitud-test-1"):
    plan = {"accion": "crear", "cliente": "Laura", "servicio": "corte", "fecha": miercoles, "hora": "10:00"}
    ctx.chat_data["pendiente"] = {"plan": plan, "solicitud_id": sid}


def test_responder_si_guarda_y_repetir_si_no_duplica(api_telegram_falsa, miercoles):
    ctx = contexto()
    con_pendiente(ctx, miercoles)
    upd, msg = actualizacion("¡Sí!")
    asyncio.run(bt.recibir_texto(upd, ctx))
    assert "Reserva creada" in msg.enviados[-1] and "pendiente" not in ctx.chat_data
    assert len(api_telegram_falsa.get("/api/reservas").json()) == 1
    # un segundo «sí» ya no tiene nada pendiente y no crea nada
    asyncio.run(bt.recibir_texto(upd, ctx))
    assert "ninguna operación pendiente" in msg.enviados[-1]
    assert len(api_telegram_falsa.get("/api/reservas").json()) == 1


def test_responder_no_descarta_sin_crear_fila(api_telegram_falsa, miercoles):
    ctx = contexto()
    con_pendiente(ctx, miercoles, "solicitud-test-2")
    upd, msg = actualizacion("no")
    asyncio.run(bt.recibir_texto(upd, ctx))
    assert "descartada" in msg.enviados[-1].lower() and "pendiente" not in ctx.chat_data
    assert api_telegram_falsa.get("/api/reservas").json() == []


def test_respuesta_perdida_conserva_pendiente_y_reintento_no_duplica(api_telegram_falsa, miercoles, monkeypatch):
    ctx = contexto()
    con_pendiente(ctx, miercoles, "solicitud-test-4")
    original = bt.ejecutar
    llamadas = []

    def con_corte(plan, confirmar, usuario, solicitud_id):
        resultado = original(plan, confirmar, usuario, solicitud_id)  # la API sí guarda...
        if not llamadas:
            llamadas.append(1)
            raise TimeoutError()                                      # ...pero la respuesta se pierde
        return resultado
    monkeypatch.setattr(bt, "ejecutar", con_corte)
    upd, msg = actualizacion("si")
    asyncio.run(bt.recibir_texto(upd, ctx))
    assert "No recibí respuesta" in msg.enviados[-1] and "pendiente" in ctx.chat_data
    asyncio.run(bt.recibir_texto(upd, ctx))
    assert "no se creó una reserva duplicada" in msg.enviados[-1]
    assert len(api_telegram_falsa.get("/api/reservas").json()) == 1


def test_normalizar_respuesta_y_pregunta_de_confirmacion():
    assert bt.normalizar_respuesta("¡Sí!") == "si" and bt.normalizar_respuesta(" NO. ") == "no"
    texto = bt.con_pregunta_de_confirmacion("Voy a crear...\n\nPulsa **Confirmar operación** o **Descartar solicitud**.")
    assert "Responde SÍ" in texto and "Pulsa" not in texto


def test_cuenta_ajena_no_puede_cancelar(api_telegram_falsa, miercoles):
    creada = cl.ejecutar({"accion": "crear", "cliente": "Laura", "servicio": "corte",
                          "fecha": miercoles, "hora": "10:00"}, confirmar=True,
                         usuario=111, solicitud_id="solicitud-test-3")["datos"]
    with pytest.raises(HTTPError) as error:
        cm.procesar_turno("cancela", cm.nuevo_historial(), "k", "m", usuario=222,
                          llm=llm_guion({"accion": "cancelar", "codigo": creada["codigo"]}))
    assert error.value.code == 403
    assert "no pertenece" in bt.texto_error_http(error.value)
    assert api_telegram_falsa.get(f"/api/reservas/{creada['codigo']}").json()["estado"] == "activa"


def test_listar_solo_muestra_las_propias(api_telegram_falsa, miercoles):
    for usuario, hora, sid in ((111, "10:00", "solicitud-A001"), (222, "11:00", "solicitud-B001")):
        cl.ejecutar({"accion": "crear", "cliente": "Ana", "servicio": "corte", "fecha": miercoles,
                     "hora": hora}, confirmar=True, usuario=usuario, solicitud_id=sid)
    res, _, _ = cm.procesar_turno("mis reservas", cm.nuevo_historial(), "k", "m", usuario=111,
                                  llm=llm_guion({"accion": "listar"}))
    assert len(res["datos"]) == 1 and res["datos"][0]["hora"] == "10:00"


def test_flujo_completo_por_texto_dos_cuentas(api_telegram_falsa, miercoles, monkeypatch):
    """Mensaje -> resumen con pregunta SÍ/NO -> «sí» -> fila con propietario; la otra cuenta no la ve."""
    plan_llm = {"accion": "crear", "cliente": "Laura", "servicio": "corte", "fecha": miercoles, "hora": "10:00"}
    original = cm.procesar_turno
    monkeypatch.setattr(bt, "procesar_turno",
                        lambda m, h, c, mo, usuario=None: original(m, h, c, mo, llm=llm_guion(plan_llm), usuario=usuario))
    ctx_a, ctx_b = contexto(), contexto()
    upd, msg = actualizacion("Quiero un corte el miércoles a las 10, soy Laura", usuario=111)
    asyncio.run(bt.recibir_texto(upd, ctx_a))
    assert "Responde SÍ para confirmar" in msg.enviados[-1] and "NO se ejecutó" not in msg.enviados[-1]
    assert api_telegram_falsa.get("/api/reservas").json() == []          # aún no se guardó
    upd_si, msg_si = actualizacion("si", usuario=111)
    asyncio.run(bt.recibir_texto(upd_si, ctx_a))
    fila = api_telegram_falsa.get("/api/reservas").json()[0]
    assert fila["propietario"] == "111" and "Reserva creada" in msg_si.enviados[-1]
    # la cuenta B no tiene nada pendiente: su «sí» no hace nada
    upd_b, msg_b = actualizacion("si", usuario=222)
    asyncio.run(bt.recibir_texto(upd_b, ctx_b))
    assert "ninguna operación pendiente" in msg_b.enviados[-1]
    assert len(api_telegram_falsa.get("/api/reservas").json()) == 1
