"""Peticiones HTTP: Groq (interpretar el mensaje) y FastAPI (ejecutar la operación).

Solo usa la biblioteca estándar. La clave de Groq llega por parámetro y nunca se
escribe en el historial ni en los archivos.
"""

import json
import os
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError
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


def cabeceras_telegram(usuario):
    """Cabeceras de las rutas /telegram: clave privada compartida y cuenta de Telegram."""
    return {"X-Clave-Privada": os.getenv("API_PRIVATE_KEY", ""), "X-Usuario-Telegram": str(usuario)}


def peticion_api(metodo, ruta, cuerpo=None, usuario=None):
    cabeceras = cabeceras_telegram(usuario) if usuario is not None else None
    return _peticion(url_api() + ruta, metodo, cuerpo, cabeceras)


def llamar_groq(mensajes, clave, modelo):
    """Envía el historial a Groq y devuelve el plan (objeto JSON) que interpretó."""
    cuerpo = {
        "model": modelo,
        "messages": mensajes,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    for intento in range(2):  # un reintento ante fallos de red momentáneos (no ante errores HTTP)
        try:
            respuesta = _peticion(GROQ_URL, "POST", cuerpo, {"Authorization": f"Bearer {clave}"})
            break
        except HTTPError:
            raise
        except (URLError, TimeoutError):
            if intento == 1:
                raise
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


def ejecutar(plan, confirmar=False, usuario=None, solicitud_id=None):
    """Ejecuta un plan contra FastAPI. Las escrituras exigen confirmar=True.

    Con `usuario` (Telegram) las reservas pasan por /telegram/..., que aplica la clave
    privada y la propiedad de cada reserva; sin él se usan las rutas /api (Gradio).
    """
    accion = plan.get("accion")
    if accion in ESCRITURAS and not confirmar:
        raise ValueError("La operación debe estar confirmada")

    base = "/telegram" if usuario is not None else "/api"
    kw = {"usuario": usuario} if usuario is not None else {}
    codigo = quote(plan.get("codigo") or "", safe="")

    if accion == "servicios":
        datos = peticion_api("GET", "/api/servicios")
    elif accion == "disponibilidad":
        consulta = urlencode({"fecha": plan["fecha"], "servicio": plan["servicio"]})
        datos = peticion_api("GET", f"/api/disponibilidad?{consulta}")
    elif accion == "listar":
        datos = peticion_api("GET", f"{base}/reservas", **kw)
    elif accion == "consultar":
        datos = peticion_api("GET", f"{base}/reservas/{codigo}", **kw)
    elif accion == "crear":
        cuerpo = {"cliente": plan["cliente"], "servicio": plan["servicio"],
                  "fecha": plan["fecha"], "hora": plan["hora"], "confirmada": True}
        if usuario is not None:
            cuerpo["solicitud_id"] = solicitud_id or ""
        datos = peticion_api("POST", f"{base}/reservas", cuerpo, **kw)
    elif accion == "modificar":
        datos = peticion_api("PUT", f"{base}/reservas/{codigo}", {
            "servicio": plan["servicio"], "fecha": plan["fecha"], "hora": plan["hora"]}, **kw)
    elif accion == "cancelar":
        datos = peticion_api("DELETE", f"{base}/reservas/{codigo}", **kw)
    else:
        raise ValueError(f"Acción no ejecutable: {accion}")
    return {"tipo": "resultado", "mensaje": formatear(accion, datos), "datos": datos}


__all__ = ["HTTPError", "ejecutar", "llamar_groq", "peticion_api", "detalle_error",
           "cargar_negocio", "LECTURAS", "ESCRITURAS", "dinero"]
