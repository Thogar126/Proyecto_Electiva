
import asyncio
import json
import logging
import os
import unicodedata
import uuid
from getpass import getpass
from urllib.error import HTTPError, URLError

from telegram import Update
from telegram.error import InvalidToken, NetworkError, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from chatbot_memoria import nuevo_historial, procesar_turno
from consulta_llm import cargar_negocio, detalle_error, ejecutar


BIENVENIDA = (
    "¡Hola! Soy BarberBot, el asistente de tu barbería. ✂️\n"
    "Puedo ayudarte a consultar servicios, precios y horarios, y a crear, consultar, "
    "modificar o cancelar tus reservas.\n"
    "Escribe /help para ver ejemplos."
)

AYUDA = (
    "Comandos disponibles:\n"
    "/start — iniciar el asistente.\n"
    "/help — ver esta ayuda.\n"
    "/reset — reiniciar el contexto de esta conversación.\n\n"
    "Ejemplos de consultas:\n"
    "• ¿Qué servicios ofrecen y cuánto cuestan?\n"
    "• ¿Cuánto vale el corte de cabello?\n"
    "• ¿Qué horarios hay para corte mañana?\n"
    "• Quiero un corte el próximo lunes a las 10:00, soy Laura\n"
    "• Muéstrame mis reservas\n"
    "• Cambia mi reserva ABC12345 al martes a las 11:00\n"
    "• Cancela mi reserva ABC12345\n\n"
    "Antes de guardar cualquier cambio te muestro un resumen: responde SÍ para "
    "confirmar o NO para descartar. Solo puedes ver y cambiar tus propias reservas."
)


RESPUESTAS_SI = {"si", "confirmar", "confirmo", "confirmado", "ok", "dale", "de acuerdo"}
RESPUESTAS_NO = {"no", "descartar", "descarto", "descartar solicitud"}


def normalizar_respuesta(texto):
    """Minúsculas, sin tildes ni signos: «¡Sí!» -> «si»."""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return "".join(c for c in texto if c.isalnum() or c == " ").strip()


def con_pregunta_de_confirmacion(texto):
    """Cambia la invitación a pulsar botones (de la interfaz Gradio) por SÍ / NO escrito."""
    return texto.split("\n\nPulsa")[0] + "\n\nResponde SÍ para confirmar o NO para descartar."


def dinero_cop(valor):
    """Presenta un precio en pesos colombianos sin depender de la configuración regional."""
    try:
        return "$" + f"{int(valor):,}".replace(",", ".") + " COP"
    except (TypeError, ValueError):
        return f"{valor} COP"


async def enviar_texto(mensaje, texto):
    """Divide las respuestas largas en fragmentos aceptados por Telegram."""
    texto = str(texto or "No tengo una respuesta para mostrar.")
    for inicio in range(0, len(texto), 4000):
        await mensaje.reply_text(texto[inicio:inicio + 4000])


async def iniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.effective_message
    if mensaje is not None:
        # /start muestra la bienvenida, pero conserva el historial de esta conversación.
        context.chat_data.setdefault("historial", nuevo_historial())
        await enviar_texto(mensaje, BIENVENIDA)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is not None:
        await enviar_texto(update.effective_message, AYUDA)


async def reiniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.effective_message
    if mensaje is not None:
        context.chat_data["historial"] = nuevo_historial()
        context.chat_data.pop("pendiente", None)
        await enviar_texto(
            mensaje,
            "Conversación reiniciada. Las reservas guardadas en BarberBot no se borraron.",
        )


def formatear_resultado(resultado, plan):
    """Adapta las estructuras que devuelve chatbot_memoria/consulta_llm a Telegram."""
    tipo = resultado.get("tipo")
    datos = resultado.get("datos")
    accion = plan.get("accion") if isinstance(plan, dict) else None

    # El resumen de una operación de escritura pide confirmar escribiendo SÍ o NO (ver recibir_texto).
    if tipo == "confirmacion":
        return str(resultado.get("mensaje", "")).replace("**", "")

    # Los datos se toman de la respuesta actual de FastAPI, no de precios inventados por el modelo.
    if accion == "servicios" and isinstance(datos, dict):
        lineas = ["✂️ Servicios de BarberBot:"]
        for identificador, servicio in datos.items():
            if not isinstance(servicio, dict):
                continue
            nombre = servicio.get("nombre", identificador)
            precio = dinero_cop(servicio.get("precio_cop", "por consultar"))
            duracion = servicio.get("duracion_minutos", "por consultar")
            lineas.append(f"• {nombre}: {precio} · {duracion} minutos")
        if len(lineas) > 1:
            return "\n".join(lineas)

    if accion == "disponibilidad" and isinstance(datos, dict):
        servicio_id = datos.get("servicio", plan.get("servicio", "el servicio solicitado"))
        try:
            catalogo = cargar_negocio().get("servicios", {})
            servicio = catalogo.get(servicio_id, {}).get("nombre", servicio_id)
        except (OSError, ValueError, TypeError):
            servicio = servicio_id
        fecha = datos.get("fecha", plan.get("fecha", "la fecha indicada"))
        duracion = datos.get("duracion_minutos")
        horas = datos.get("horas", [])
        titulo = f"Horarios disponibles para {servicio} el {fecha}"
        if duracion is not None:
            titulo += f" ({duracion} minutos)"
        if not horas:
            return titulo + ":\nNo hay horarios disponibles para esta fecha."
        return titulo + ":\n" + ", ".join(str(hora) for hora in horas)

    mensaje = resultado.get("mensaje")
    if mensaje:
        # consulta_llm.formatear usa Markdown para Gradio; Telegram aquí envía texto plano.
        return str(mensaje).replace("**", "")
    if datos is not None:
        return json.dumps(datos, ensure_ascii=False, indent=2)
    return "No tengo una respuesta para mostrar. Intenta reformular la consulta."


async def recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.effective_message
    if mensaje is None or not mensaje.text or not mensaje.text.strip():
        return

    respuesta = normalizar_respuesta(mensaje.text)
    if respuesta in RESPUESTAS_SI or respuesta in RESPUESTAS_NO:
        # Confirmar o descartar no pasa por el modelo: lo decide el estado de este chat.
        await resolver_pendiente(update, context, confirmar=respuesta in RESPUESTAS_SI)
        return

    clave = context.bot_data.get("clave_modelo", "")
    modelo = context.bot_data.get("modelo", "")
    if not clave or not modelo:
        await enviar_texto(
            mensaje,
            "Falta configurar GROQ_API_KEY o GROQ_MODEL en la terminal donde ejecutaste el bot.",
        )
        return

    historial = context.chat_data.get("historial")
    if historial is None:
        historial = nuevo_historial()

    usuario = update.effective_user.id
    try:
        resultado, actualizado, plan = await asyncio.to_thread(
            procesar_turno, mensaje.text.strip(), historial, clave, modelo, usuario=usuario
        )
        texto = formatear_resultado(resultado, plan)
    except HTTPError as error:
        await enviar_texto(mensaje, texto_error_http(error))
        return
    except (URLError, TimeoutError):
        await enviar_texto(
            mensaje,
            "No pude conectarme con Groq o FastAPI. Revisa la conexión y vuelve a intentarlo.",
        )
        return
    except (ValueError, KeyError, IndexError, TypeError):
        await enviar_texto(
            mensaje,
            "La respuesta del servicio no tiene el formato esperado. Revisa los registros de la API.",
        )
        return

    # Solo se guarda el nuevo historial si el turno terminó correctamente.
    context.chat_data["historial"] = actualizado
    if resultado.get("tipo") == "confirmacion":
        # Una solicitud nueva reemplaza a la anterior: solo hay una pendiente por chat.
        context.chat_data["pendiente"] = {"plan": plan, "solicitud_id": uuid.uuid4().hex}
        await enviar_texto(mensaje, con_pregunta_de_confirmacion(texto))
        return
    await enviar_texto(mensaje, texto)


def texto_error_http(error):
    """Mensaje para el usuario según el código HTTP; usa el detalle que entrega FastAPI."""
    detalle = detalle_error(error)
    if error.code in (403, 404, 409, 422):
        return f"No se pudo completar: {detalle or 'la solicitud no es válida'}. No se modificó ningún dato."
    if error.code in (401, 503):
        return "El bot no está autorizado ante la API. Revisa API_PRIVATE_KEY en ambas terminales."
    return (f"Un servicio respondió con error HTTP {error.code}. "
            "Revisa si FastAPI está encendida y la configuración de Groq.")


async def resolver_pendiente(update: Update, context: ContextTypes.DEFAULT_TYPE, confirmar):
    """Responde a un SÍ o NO escrito por la persona sobre la solicitud pendiente de este chat."""
    mensaje = update.effective_message
    pendiente = context.chat_data.get("pendiente")

    if pendiente is None:
        await enviar_texto(
            mensaje,
            "No hay ninguna operación pendiente: ya fue procesada, descartada o no existe. "
            "No se hizo ningún cambio. Escribe una solicitud nueva si lo necesitas.",
        )
        return

    if not confirmar:
        context.chat_data.pop("pendiente")
        context.chat_data["historial"] = context.chat_data.get("historial", nuevo_historial()) + [
            {"role": "user", "content": "Descartar la solicitud pendiente."},
            {"role": "assistant", "content": "Solicitud descartada; no se guardó ningún cambio."},
        ]
        await enviar_texto(mensaje, "Solicitud descartada. No se guardó ningún cambio.")
        return

    plan = pendiente["plan"]
    usuario = update.effective_user.id
    try:
        resultado = await asyncio.to_thread(
            ejecutar, plan, True, usuario, pendiente["solicitud_id"]
        )
    except HTTPError as error:
        # La API rechazó la operación (cruce, reserva ajena, etc.): se cierra la solicitud.
        context.chat_data.pop("pendiente", None)
        await enviar_texto(mensaje, texto_error_http(error))
        return
    except (URLError, TimeoutError):
        # Sin respuesta: el pendiente se conserva. Repetir «sí» reutiliza la misma
        # solicitud_id, así que la API no duplica la reserva si la primera sí llegó.
        await enviar_texto(
            mensaje,
            "No recibí respuesta de la API. Escribe SÍ otra vez: "
            "si la reserva ya se había guardado, no se duplicará.",
        )
        return
    except (ValueError, KeyError, TypeError):
        await enviar_texto(mensaje, "La respuesta de la API no tiene el formato esperado.")
        return

    context.chat_data.pop("pendiente", None)
    context.chat_data["historial"] = context.chat_data.get("historial", nuevo_historial()) + [
        {"role": "user", "content": "Confirmar la operación pendiente."},
        {"role": "assistant", "content": json.dumps(
            {"plan": plan, "respuesta": resultado["datos"]}, ensure_ascii=False)},
    ]
    texto = str(resultado["mensaje"]).replace("**", "")
    if isinstance(resultado["datos"], dict) and resultado["datos"].get("repetida"):
        texto = "Esta solicitud ya estaba confirmada; no se creó una reserva duplicada.\n" + texto
    await enviar_texto(mensaje, texto)


async def comando_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is not None:
        await enviar_texto(
            update.effective_message,
            "No conozco ese comando. Usa /start, /help o /reset.",
        )


async def otro_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is not None:
        await enviar_texto(
            update.effective_message,
            "Por ahora solo puedo procesar texto. Envíame una consulta escrita.",
        )


async def informar_error(update, context):
    # No registrar tokens, claves ni URLs que puedan contener credenciales.
    logging.error("Error del bot de Telegram: %s", type(context.error).__name__)


def registrar_handlers(aplicacion):
    privado = filters.ChatType.PRIVATE
    aplicacion.add_handler(CommandHandler("start", iniciar, filters=privado))
    aplicacion.add_handler(CommandHandler("help", ayuda, filters=privado))
    aplicacion.add_handler(CommandHandler("reset", reiniciar, filters=privado))
    aplicacion.add_handler(
        MessageHandler(privado & filters.TEXT & ~filters.COMMAND, recibir_texto)
    )
    aplicacion.add_handler(
        MessageHandler(privado & filters.COMMAND, comando_desconocido)
    )
    aplicacion.add_handler(MessageHandler(privado & ~filters.TEXT, otro_mensaje))
    aplicacion.add_error_handler(informar_error)


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    token = (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or getpass("Token de BotFather (entrada oculta): ").strip()
    )
    if not token:
        print("Necesito el token de Telegram para iniciar.")
        return

    try:
        aplicacion = Application.builder().token(token).build()
        aplicacion.bot_data["clave_modelo"] = os.getenv("GROQ_API_KEY", "").strip()
        aplicacion.bot_data["modelo"] = os.getenv("GROQ_MODEL", "").strip()
        registrar_handlers(aplicacion)

        if not os.getenv("API_PRIVATE_KEY", "").strip():
            print("Falta API_PRIVATE_KEY: las reservas desde Telegram serán rechazadas por la API.")
        if not aplicacion.bot_data["clave_modelo"] or not aplicacion.bot_data["modelo"]:
            print("Los comandos funcionarán; configura GROQ_API_KEY y GROQ_MODEL para consultar el negocio.")
        print("BarberBot está conectado a Telegram. Detén el proceso con Ctrl+C.")
        aplicacion.run_polling(allowed_updates=["message"])
    except InvalidToken:
        print("Token inválido. Comprueba la credencial entregada por BotFather.")
    except NetworkError:
        print("No fue posible conectarse con Telegram. Revisa Internet e inténtalo otra vez.")
    except TelegramError as error:
        print(f"Telegram no completó el inicio: {type(error).__name__}.")


if __name__ == "__main__":
    main()
