"""Peticiones HTTP: Groq (interpretar el mensaje) y FastAPI (ejecutar la operación).

Solo usa la biblioteca estándar. La clave de Groq llega por parámetro y nunca se
escribe en el historial ni en los archivos.
"""

import json
import os
import urllib.request
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode

BASE = Path(__file__).resolve().parent
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TIEMPO_ESPERA = 30

LECTURAS = {"servicios", "disponibilidad", "listar", "consultar"}
ESCRITURAS = {"crear", "modificar", "cancelar"}


def url_api():
    return os.getenv("CHATBOT_API_URL", "http://127.0.0.1:8011").rstrip("/")


def cargar_negocio():
    return json.loads((BASE / "negocio.json").read_text(encoding="utf-8-sig"))


def _peticion(url, metodo="GET", cuerpo=None, cabeceras=None):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    cabecera = {"Accept": "application/json", "User-Agent": "BarberBot/1.0"}
    cabecera.update(cabeceras or {})
    if datos is not None:
        cabecera["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=datos, method=metodo, headers=cabecera)
    with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA) as respuesta:
        texto = respuesta.read().decode("utf-8")
    return json.loads(texto) if texto else None


def peticion_api(metodo, ruta, cuerpo=None):
    return _peticion(url_api() + ruta, metodo, cuerpo)


def llamar_groq(mensajes, clave, modelo):
    """Envía el historial a Groq y devuelve el plan (objeto JSON) que interpretó."""
    cuerpo = {
        "model": modelo,
        "messages": mensajes,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    respuesta = _peticion(GROQ_URL, "POST", cuerpo, {"Authorization": f"Bearer {clave}"})
    return json.loads(respuesta["choices"][0]["message"]["content"])


def detalle_error(error):
    """Extrae el mensaje 'detail' que FastAPI incluye en sus errores HTTP."""
    try:
        detalle = json.loads(error.read().decode("utf-8")).get("detail")
    except (ValueError, AttributeError, OSError):
        return ""
    if isinstance(detalle, str):
        return detalle
    return "Datos inválidos; revisa fecha, hora y servicio." if detalle else ""


# ---------- Formato de las respuestas para la pantalla ----------

def dinero(valor):
    return "$" + f"{valor:,}".replace(",", ".") + " COP"


def linea_reserva(r):
    return (f"**{r['codigo']}** · {r['cliente']} · {r['servicio']} · "
            f"{r['fecha']} {r['hora']} ({r['duracion_minutos']} min) · {r['estado']}")


def formatear(accion, datos):
    if accion == "servicios":
        filas = [f"- **{id_}** ({d['nombre']}): {dinero(d['precio_cop'])}, {d['duracion_minutos']} min"
                 for id_, d in datos.items()]
        return "Estos son nuestros servicios:\n" + "\n".join(filas)
    if accion == "disponibilidad":
        if not datos["horas"]:
            return f"No quedan horas libres el {datos['fecha']} para {datos['servicio']}."
        return (f"Horas libres el {datos['fecha']} para {datos['servicio']} "
                f"({datos['duracion_minutos']} min):\n" + ", ".join(datos["horas"]))
    if accion == "listar":
        if not datos:
            return "Todavía no hay reservas guardadas."
        return "Reservas guardadas:\n" + "\n".join("- " + linea_reserva(r) for r in datos[:30])
    if accion == "consultar":
        return "Reserva encontrada:\n- " + linea_reserva(datos)
    etiquetas = {"crear": "Reserva creada", "modificar": "Reserva modificada",
                 "cancelar": "Reserva cancelada"}
    return f"{etiquetas[accion]}:\n- " + linea_reserva(datos)


def ejecutar(plan, confirmar=False):
    """Ejecuta un plan contra FastAPI. Las escrituras exigen confirmar=True."""
    accion = plan.get("accion")
    if accion in ESCRITURAS and not confirmar:
        raise ValueError("La operación debe estar confirmada")

    if accion == "servicios":
        datos = peticion_api("GET", "/api/servicios")
    elif accion == "disponibilidad":
        consulta = urlencode({"fecha": plan["fecha"], "servicio": plan["servicio"]})
        datos = peticion_api("GET", f"/api/disponibilidad?{consulta}")
    elif accion == "listar":
        datos = peticion_api("GET", "/api/reservas")
    elif accion == "consultar":
        datos = peticion_api("GET", f"/api/reservas/{quote(plan['codigo'], safe='')}")
    elif accion == "crear":
        datos = peticion_api("POST", "/api/reservas", {
            "cliente": plan["cliente"], "servicio": plan["servicio"],
            "fecha": plan["fecha"], "hora": plan["hora"], "confirmada": True})
    elif accion == "modificar":
        datos = peticion_api("PUT", f"/api/reservas/{quote(plan['codigo'], safe='')}", {
            "servicio": plan["servicio"], "fecha": plan["fecha"], "hora": plan["hora"]})
    elif accion == "cancelar":
        datos = peticion_api("DELETE", f"/api/reservas/{quote(plan['codigo'], safe='')}")
    else:
        raise ValueError(f"Acción no ejecutable: {accion}")
    return {"tipo": "resultado", "mensaje": formatear(accion, datos), "datos": datos}


__all__ = ["HTTPError", "ejecutar", "llamar_groq", "peticion_api", "detalle_error",
           "cargar_negocio", "LECTURAS", "ESCRITURAS", "dinero"]
