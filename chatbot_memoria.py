"""Memoria de la conversación y planificación de cada turno.

El historial es una lista de mensajes {"role", "content"} que se envía a Groq.
Cada respuesta del asistente se guarda como el plan JSON que se interpretó, de
modo que los datos de un turno (nombre, servicio...) siguen disponibles en el siguiente.
"""

import json
import re
from datetime import date

from consulta_llm import (ESCRITURAS, LECTURAS, cargar_negocio, dinero, ejecutar,
                          formatear, llamar_groq, peticion_api, linea_reserva)

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ACCIONES = LECTURAS | ESCRITURAS | {"conversar"}
CAMPOS = ("cliente", "servicio", "fecha", "hora", "codigo")
REQUERIDOS = {
    "disponibilidad": ("servicio", "fecha"),
    "consultar": ("codigo",),
    "crear": ("cliente", "servicio", "fecha", "hora"),
    "modificar": ("codigo", "servicio", "fecha", "hora"),
    "cancelar": ("codigo",),
}
PIDE = {"cliente": "tu nombre", "servicio": "el servicio", "fecha": "la fecha (AAAA-MM-DD)",
        "hora": "la hora (HH:MM)", "codigo": "el código de la reserva"}
MAX_MENSAJE = 500

PROMPT = """Eres BarberBot, el asistente de la barbería <<NOMBRE>>. Hablas en español, con trato cordial y breve.
Hoy es <<DIA>> <<HOY>>. Atendemos <<DIAS>> de <<APERTURA>> a <<CIERRE>>, con citas cada <<PASO>> minutos.
Servicios (usa exactamente estos identificadores):
<<SERVICIOS>>

Tu única salida es un objeto JSON con estas claves:
accion: "servicios" | "disponibilidad" | "listar" | "consultar" | "crear" | "modificar" | "cancelar" | "conversar"
cliente, servicio, fecha (AAAA-MM-DD), hora (HH:MM en 24 horas), codigo, respuesta

Reglas:
- Usa null en lo que la persona no haya dicho. No inventes nombres, fechas, horas ni códigos.
- Calcula fechas relativas ("mañana", "el viernes") a partir de la fecha de hoy.
- Si la fecha ya viene como AAAA-MM-DD, cópiala tal cual aunque parezca inválida: la API la validará.
- Conserva los datos de turnos anteriores de la misma solicitud y mantén su acción.
- "servicios": servicios o precios. "disponibilidad": horas libres (servicio y fecha). "listar": todas las reservas. "consultar": una reserva por código.
- "crear": nueva reserva. "modificar" y "cancelar": una reserva existente, identificada por su código.
- "conversar": saludos o preguntas generales; escribe una respuesta breve en "respuesta". No afirmes que una reserva quedó hecha: el sistema la guarda solo después de que la persona confirme.
- Responde únicamente con el JSON."""


def instrucciones_sistema(hoy=None):
    hoy = hoy or date.today()
    negocio = cargar_negocio()
    horario = negocio["horario"]
    servicios = "\n".join(
        f"- {id_}: {d['nombre']} ({d['duracion_minutos']} min, {dinero(d['precio_cop'])})"
        for id_, d in negocio["servicios"].items())
    valores = {
        "NOMBRE": negocio["nombre"], "DIA": DIAS_ES[hoy.weekday()], "HOY": hoy.isoformat(),
        "DIAS": ", ".join(DIAS_ES[d] for d in horario["dias"]),
        "APERTURA": horario["apertura"], "CIERRE": horario["cierre"],
        "PASO": str(horario["paso_minutos"]), "SERVICIOS": servicios,
    }
    texto = PROMPT
    for clave, valor in valores.items():
        texto = texto.replace(f"<<{clave}>>", valor)
    return texto


def nuevo_historial():
    return [{"role": "system", "content": instrucciones_sistema()}]


# ---------- Normalización del plan ----------

def _texto(valor):
    if not isinstance(valor, str):
        return None
    valor = valor.strip()
    return None if valor.lower() in {"", "null", "none"} else valor


def normalizar_plan(bruto):
    if not isinstance(bruto, dict):
        raise ValueError("El plan debe ser un objeto JSON")
    accion = (_texto(bruto.get("accion")) or "conversar").lower()
    if accion not in ACCIONES:
        raise ValueError(f"Acción desconocida: {accion}")
    plan = {"accion": accion, **{campo: _texto(bruto.get(campo)) for campo in CAMPOS}}
    plan["respuesta"] = _texto(bruto.get("respuesta"))
    if plan["servicio"]:
        plan["servicio"] = plan["servicio"].lower()
    if plan["codigo"]:
        plan["codigo"] = plan["codigo"].upper()
    if plan["hora"]:
        coincide = re.fullmatch(r"(\d{1,2}):(\d{2})", plan["hora"])
        if coincide:
            plan["hora"] = f"{int(coincide[1]):02d}:{coincide[2]}"
    return plan


def faltantes(plan):
    return [campo for campo in REQUERIDOS.get(plan.get("accion"), ()) if not plan.get(campo)]


def plan_previo(historial):
    """Último plan de crear/modificar que quedó incompleto, si no hubo nada ejecutado después."""
    for mensaje in reversed(historial):
        if mensaje["role"] != "assistant":
            continue
        try:
            dato = json.loads(mensaje["content"])
        except ValueError:
            return None  # texto libre (por ejemplo, una solicitud descartada)
        if not isinstance(dato, dict):
            return None
        if "plan" in dato:
            if (dato["plan"] or {}).get("accion") in ESCRITURAS:
                return None  # una operación ya se ejecutó
            continue
        if dato.get("accion") in ("crear", "modificar"):
            return dato if faltantes(dato) else None
    return None


def ultimo_codigo(historial):
    """Código de la reserva más reciente que aparece en las respuestas de FastAPI."""
    for mensaje in reversed(historial):
        if mensaje["role"] != "assistant":
            continue
        try:
            dato = json.loads(mensaje["content"])
        except ValueError:
            continue
        respuesta = dato.get("respuesta") if isinstance(dato, dict) else None
        if isinstance(respuesta, dict) and respuesta.get("codigo"):
            return respuesta["codigo"]
    return None


def fusionar(plan, previo):
    if not previo:
        return plan
    sin_accion = plan["accion"] == "conversar" and any(plan[c] for c in CAMPOS)
    if plan["accion"] == previo["accion"] or sin_accion:
        plan = {**plan, "accion": previo["accion"]}
        for campo in CAMPOS:
            plan[campo] = plan[campo] or previo.get(campo)
    return plan


def plan_limpio(plan):
    campos = ("codigo", "servicio", "fecha", "hora") if plan["accion"] == "modificar" else \
             ("codigo",) if plan["accion"] in ("cancelar", "consultar") else \
             ("cliente", "servicio", "fecha", "hora") if plan["accion"] == "crear" else \
             ("servicio", "fecha") if plan["accion"] == "disponibilidad" else ()
    return {"accion": plan["accion"], **{c: plan[c] for c in campos}}


def _guardar(historial, mensaje, contenido):
    return list(historial) + [{"role": "user", "content": mensaje},
                              {"role": "assistant", "content": json.dumps(contenido, ensure_ascii=False)}]


def _resumen(plan, servicios, actual=None):
    accion = plan["accion"]
    cierre = "\n\nPulsa **Confirmar operación** para ejecutarla o **Descartar solicitud**."
    if accion == "cancelar":
        return "Voy a cancelar esta reserva:\n- " + linea_reserva(actual) + cierre
    servicio = servicios[plan["servicio"]]
    dia = DIAS_ES[date.fromisoformat(plan["fecha"]).weekday()] if _fecha_valida(plan["fecha"]) else "?"
    titulo = "Voy a crear esta reserva:" if accion == "crear" else \
        f"Voy a modificar la reserva **{plan['codigo']}** (ahora: {actual['fecha']} {actual['hora']}):"
    lineas = [titulo]
    if accion == "crear":
        lineas.append(f"- Cliente: {plan['cliente']}")
    lineas += [f"- Servicio: {plan['servicio']} ({servicio['duracion_minutos']} min, {dinero(servicio['precio_cop'])})",
               f"- Fecha: {plan['fecha']} ({dia})", f"- Hora: {plan['hora']}"]
    return "\n".join(lineas) + cierre


def _fecha_valida(texto):
    try:
        date.fromisoformat(texto)
        return True
    except ValueError:
        return False


def procesar_turno(mensaje, historial, clave, modelo, llm=llamar_groq):
    """Interpreta un mensaje. Devuelve (resultado, historial_nuevo, plan).

    Si algo falla antes del return se lanza la excepción y el historial recibido
    queda intacto: un turno fallido no se guarda como respuesta correcta.
    """
    mensaje = mensaje.strip()[:MAX_MENSAJE]
    servicios = cargar_negocio()["servicios"]
    plan = normalizar_plan(llm(list(historial) + [{"role": "user", "content": mensaje}], clave, modelo))
    plan = fusionar(plan, plan_previo(historial))

    nota = ""
    if plan["servicio"] and plan["servicio"] not in servicios:
        nota = f"No reconozco el servicio «{plan['servicio']}». Opciones: {', '.join(servicios)}.\n"
        plan["servicio"] = None
    if plan["accion"] in ("consultar", "modificar", "cancelar") and not plan["codigo"]:
        plan["codigo"] = ultimo_codigo(historial)
    pendientes = faltantes(plan)
    limpio = plan_limpio(plan)

    if plan["accion"] == "conversar":
        texto = plan["respuesta"] or "¿En qué te ayudo? Puedo mostrarte servicios, horas libres y gestionar tus reservas."
        return ({"tipo": "conversacion", "mensaje": texto, "datos": None},
                _guardar(historial, mensaje, {"accion": "conversar", "respuesta": texto}), None)

    if pendientes:
        texto = nota + "Para continuar necesito " + ", ".join(PIDE[c] for c in pendientes) + "."
        guardado = {**limpio, **{c: plan[c] for c in CAMPOS if plan[c]}}
        return ({"tipo": "faltantes", "mensaje": texto, "datos": None},
                _guardar(historial, mensaje, guardado), None)

    if plan["accion"] in LECTURAS:
        resultado = ejecutar(limpio)
        resultado["tipo"] = "consulta"
        return (resultado,
                _guardar(historial, mensaje, {"plan": limpio, "respuesta": resultado["datos"]}), limpio)

    actual = None
    if plan["accion"] in ("modificar", "cancelar"):
        actual = peticion_api("GET", f"/api/reservas/{plan['codigo']}")
        if actual["estado"] != "activa":
            texto = f"La reserva {plan['codigo']} ya está cancelada y no se puede cambiar."
            return ({"tipo": "conversacion", "mensaje": texto, "datos": None},
                    _guardar(historial, mensaje, {"accion": "conversar", "respuesta": texto}), None)
    texto = _resumen(plan, servicios, actual)
    return ({"tipo": "confirmacion", "mensaje": texto, "datos": None},
            _guardar(historial, mensaje, limpio), limpio)


__all__ = ["nuevo_historial", "procesar_turno", "formatear"]
