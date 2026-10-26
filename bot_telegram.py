
import asyncio
import json
import logging
import os
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
from consulta_llm import cargar_negocio


BIENVENIDA = (
    "¡Hola! Soy BarberBot, el asistente de tu barbería. ✂️\n"
    "Puedo ayudarte a consultar servicios, precios y horarios disponibles.\n"
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
    "• ¿Qué horarios hay para corte mañana?\n\n"
    "En esta versión, Telegram permite hacer consultas. Las solicitudes para crear, "
    "modificar o cancelar reservas se explican, pero no se ejecutan desde este canal."
)


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
        await enviar_texto(
            mensaje,
            "Conversación reiniciada. Las reservas guardadas en BarberBot no se borraron.",
        )


def formatear_resultado(resultado, plan):
    """Adapta las estructuras que devuelve chatbot_memoria/consulta_llm a Telegram."""
    tipo = resultado.get("tipo")
    datos = resultado.get("datos")
    accion = plan.get("accion") if isinstance(plan, dict) else None

    # No se debe ejecutar una escritura desde Telegram en esta práctica.
    if tipo == "confirmacion":
        etiquetas = {
            "crear": "crear una reserva",
            "modificar": "modificar una reserva",
            "cancelar": "cancelar una reserva",
        }
        detalle = etiquetas.get(accion, "realizar una operación")
        campos = []
        if plan.get("cliente"):
            campos.append(f"Cliente: {plan['cliente']}")
        if plan.get("codigo"):
            campos.append(f"Código: {plan['codigo']}")
        if plan.get("servicio"):
            campos.append(f"Servicio: {plan['servicio']}")
        if plan.get("fecha"):
            campos.append(f"Fecha: {plan['fecha']}")
        if plan.get("hora"):
            campos.append(f"Hora: {plan['hora']}")
        detalle_texto = "\n".join(campos) if campos else json.dumps(plan, ensure_ascii=False)
        return (
            f"Entendí que deseas {detalle}.\n{detalle_texto}\n\n"
            "Esta versión de BarberBot por Telegram solo permite consultas: "
            "la operación NO se ejecutó y no se guardó ningún cambio. "
            "Para reservar, modificar o cancelar, utiliza la interfaz del proyecto."
        )

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

    try:
        resultado, actualizado, plan = await asyncio.to_thread(
            procesar_turno, mensaje.text.strip(), historial, clave, modelo
        )
        texto = formatear_resultado(resultado, plan)
    except HTTPError as error:
        await enviar_texto(
            mensaje,
            f"Un servicio respondió con error HTTP {error.code}. "
            "Revisa si FastAPI está encendida y la configuración de Groq.",
        )
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
