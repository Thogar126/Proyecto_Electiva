# BarberBot — chatbot de reservas para una barbería (Telegram)

**Repositorio:** `Chatbot_BarberBot_Apellido1_Apellido2_Apellido3`
**Integrantes:** Thomas García, Juan Rodríguez, Juan José Anduquia, David Hurtado · EAM 2026-II · Creación de chatbots con IA · Tercer corte
**Bot en Telegram:** [@barberinho_bot](https://t.me/barberinho_bot) (solo responde mientras FastAPI y el bot estén en ejecución)

BarberBot es un asistente conversacional por Telegram que informa servicios, precios y horarios de una barbería y permite **crear, consultar, modificar y cancelar reservas**. Cada cuenta de Telegram solo ve y cambia sus propias reservas, y ninguna reserva se guarda sin que la persona la confirme escribiendo «sí».

## Problema y alcance

- **Usuarios:** clientes de la barbería que escriben desde Telegram. Una sola agenda (un solo barbero): dos reservas activas no pueden cruzarse.
- **Necesidad:** evitar llamadas y mensajes manuales para agendar, y evitar dobles reservas.
- **Funciones:** consultar servicios y precios; ver horas libres de un servicio en una fecha; crear, consultar, listar, modificar y cancelar reservas; memoria de la conversación (los datos se pueden dar en varios mensajes); `/reset`.
- **Límites:** solo responde sobre la barbería (lo demás lo declina); atiende solo chats privados y texto; horario lunes a sábado 09:00–18:00 en pasos de 30 min (`negocio.json`); el historial de la conversación vive en memoria y se pierde al reiniciar el bot (las reservas **no**); no hay pagos, recordatorios ni varios barberos.

## Arquitectura

```
Telegram ──► bot_telegram.py ──► chatbot_memoria.py ──► consulta_llm.py ──► Groq (modelo: interpreta el mensaje → plan JSON)
   ▲              │ confirmación «sí/no»                       │
   │              ▼                                            ▼  HTTP + clave privada
   └──────  confirmar / descartar ─────────────────►  FastAPI (main.py + api_telegram.py) ──► almacen_sqlite.py ──► reservas.db (SQLite)
```

| Componente | Responsabilidad |
|---|---|
| **Telegram** | Canal del usuario; entrega mensajes y comandos. |
| `bot_telegram.py` | Recibe mensajes, guarda historial y solicitud pendiente **por chat**, muestra el resumen y pide confirmar con **SÍ** o descartar con **NO**, traduce errores a mensajes claros. |
| `chatbot_memoria.py` | Memoria de la conversación y planificación de cada turno; pide los datos que faltan; arma el resumen. |
| `consulta_llm.py` | Llamadas HTTP: a Groq (interpretar) y a FastAPI (ejecutar). Nunca guarda la clave en el historial. |
| **Modelo (Groq)** | Convierte el texto libre en un plan JSON (`accion`, `servicio`, `fecha`, `hora`…). No decide ni guarda nada. |
| `main.py` | API FastAPI: servicios, disponibilidad y rutas `/api/...` (usadas por Gradio). |
| `api_telegram.py` | Rutas `/telegram/...`: exigen la clave privada y la cuenta; aplican la **propiedad de cada reserva** y la **idempotencia** de la confirmación. |
| `almacen_sqlite.py` | Reglas de negocio y SQLite: horario, duración, cruces (en una transacción), propietario, solicitud_id. |
| `negocio.json` | Catálogo: servicios, precios, duraciones y horario. |

**Recorrido de «Quiero un corte el lunes a las 10, soy Laura»:** Telegram → `recibir_texto` → `procesar_turno` (Groq devuelve el plan) → resumen con la pregunta «Responde SÍ para confirmar o NO para descartar» → la persona escribe **sí** → `POST /telegram/reservas` con la clave privada, la cuenta y un `solicitud_id` → `AgendaSQLite.crear` valida y guarda → el bot responde con el código de la reserva.

## Requisitos

- **Python 3.12 o superior** (el Dockerfile usa 3.12; la entrega se ejecutó en Windows con 3.12 y la suite de pruebas también pasa con 3.13) y **Git**.
- Dependencias de Python: `requirements.txt` (FastAPI, uvicorn, python-telegram-bot 22, gradio 6). Para las pruebas: `requirements-dev.txt`.
- Conexión a internet (Groq y Telegram).
- **Un bot de Telegram:** habla con [@BotFather](https://t.me/BotFather), escribe `/newbot`, elige nombre y usuario (termina en `bot`) y guarda el **token** que te entrega. Si usas el bot del equipo, pide el token a un integrante.
- **Una clave de Groq y un modelo:** crea la clave en <https://console.groq.com> → *API Keys*. El modelo con el que se probó es `openai/gpt-oss-120b`; `python listar_modelos_groq.py` lista los que tu cuenta puede usar. El plan gratuito tiene límites de uso (ver *Solución de problemas*, error 429).
- **Una clave privada de la API (`API_PRIVATE_KEY`):** no se pide a nadie; es un texto largo inventado por el equipo (por ejemplo, generado con `python -c "import secrets; print(secrets.token_urlsafe(24))"`). Debe ser el mismo en FastAPI y en el bot.

## Preparación (una sola vez)

```powershell
git clone https://github.com/<usuario>/Chatbot_BarberBot_Apellido1_Apellido2_Apellido3.git
cd Chatbot_BarberBot_Apellido1_Apellido2_Apellido3
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass      # solo si PowerShell bloquea la activación
.venv\Scripts\Activate.ps1                      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Al terminar, el inicio de la línea debe mostrar `(.venv)`. Comprueba que estás en la carpeta correcta con `ls main.py` (debe existir `main.py`): **todos los comandos de este README se ejecutan desde esa carpeta raíz del repositorio.** Si descargaste un zip y ves una carpeta dentro de otra con el mismo nombre, entra a la interna.

## Configuración (variables de entorno)

El proyecto **no lee archivos `.env`**: las variables se definen en la terminal de cada proceso y valen solo mientras esa terminal esté abierta. `.env.example` únicamente lista los nombres. **Nunca guardes claves ni tokens en el repositorio.**

| Variable | Para qué sirve | Proceso |
|---|---|---|
| `API_PRIVATE_KEY` | Clave inventada por el equipo; **igual** en FastAPI y en el bot. Sin ella, la API cierra las rutas de Telegram (503) o las rechaza (401). | FastAPI **y** bot |
| `TELEGRAM_BOT_TOKEN` | Token de BotFather. Si falta, el bot lo pide por consola con entrada oculta. | bot |
| `GROQ_API_KEY` | Clave de Groq. | bot |
| `GROQ_MODEL` | ID del modelo de Groq (por ejemplo, `openai/gpt-oss-120b`). | bot |
| `CHATBOT_API_URL` | Dirección de FastAPI. Por defecto `http://127.0.0.1:8011`. | bot |
| `RESERVAS_DB` | (opcional) ruta de la base SQLite. Por defecto `reservas.db` junto a `main.py`. | FastAPI |

## Arranque — dos terminales, ambas en la carpeta raíz y con `(.venv)` activo

**Terminal 1 — FastAPI (se enciende primero):**

```powershell
$env:API_PRIVATE_KEY = "PEGA_AQUI_LA_CLAVE_INVENTADA"
python -m uvicorn main:app --host 127.0.0.1 --port 8011
```

Debe mostrar `Uvicorn running on http://127.0.0.1:8011`. Comprueba `http://127.0.0.1:8011/health` → `{"estado":"ok"}` y la documentación interactiva en `http://127.0.0.1:8011/docs`. (La ruta `/` devuelve 404: es normal.)

**Terminal 2 — bot de Telegram** (botón `+` de la terminal de VS Code para abrir otra; repite la activación del entorno):

```powershell
$env:API_PRIVATE_KEY = "PEGA_AQUI_LA_MISMA_CLAVE"
$env:TELEGRAM_BOT_TOKEN = "PEGA_AQUI_EL_TOKEN_DE_BOTFATHER"
$env:GROQ_API_KEY = "PEGA_AQUI_LA_CLAVE_DE_GROQ"
$env:GROQ_MODEL = "openai/gpt-oss-120b"
python bot_telegram.py
```

Debe imprimir `BarberBot está conectado a Telegram. Detén el proceso con Ctrl+C.` y ninguna advertencia. Después abre el bot en Telegram y escribe `/start`. Para apagar, `Ctrl+C` en cada terminal.

> Un mismo token de Telegram solo puede estar en ejecución en **un** computador a la vez.

### Comprobación rápida (opcional)

```powershell
pip install -r requirements-dev.txt
python -m pytest -q                      # 45 pruebas (no usan Telegram ni Groq)
python simular_respuesta_perdida.py      # demuestra que reintentar una confirmación no duplica la reserva
python app_gradio.py                     # interfaz web del segundo corte en http://127.0.0.1:7860 (usa las rutas /api y necesita GROQ_API_KEY y GROQ_MODEL)
```

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `la ejecución de scripts está deshabilitada` al activar `.venv` | Ejecuta `Set-ExecutionPolicy -Scope Process Bypass` en esa terminal y vuelve a activar. |
| `can't open file '...bot_telegram.py'` o `Could not import module "main"` | La terminal no está en la carpeta raíz. Usa `cd` hasta que `ls main.py` lo encuentre. |
| `[Errno 10048] ... solo se permite un uso de cada dirección` | El puerto 8011 ya está ocupado por una API anterior. Ciérrala con `Ctrl+C` (o cierra su terminal) y vuelve a arrancar. |
| `Token inválido` / `InvalidToken` | El token está incompleto o tiene el texto de ejemplo. Copia el token completo de BotFather (`/token` o `/revoke` para uno nuevo). |
| `Conflict: terminated by other getUpdates request` | Otro proceso (otro computador o terminal) está usando el mismo token. Detén el otro. |
| `Falta API_PRIVATE_KEY` al arrancar el bot, o «El bot no está autorizado ante la API» | La clave no se definió, o es distinta en las dos terminales. Defínela igual en ambas. |
| «No pude conectarme con Groq o FastAPI» | La API no está encendida (`/health` no abre) o no hay internet hacia `api.groq.com`. Enciende la API y repite el mensaje. |
| «Groq recibió demasiadas solicitudes» (HTTP 429) | Límite de uso de Groq. Espera un minuto; si persiste, usa otra clave o otro modelo. |
| El bot responde otra cosa tras cambiar un archivo | Hay que reiniciar el proceso (`Ctrl+C` y volver a arrancar) y escribir `/reset` en el chat. |

## Uso del chatbot

Comandos: `/start`, `/help`, `/reset` (reinicia la conversación; **no** borra reservas).

| Quiero… | Escribo, por ejemplo |
|---|---|
| Ver servicios y precios | «¿Qué servicios ofrecen y cuánto cuestan?» |
| Ver horas libres | «¿Qué horarios hay para corte el próximo lunes?» |
| Reservar | «Quiero un corte el lunes a las 10:00, soy Laura» (si falta un dato, el bot lo pide) |
| Ver mis reservas | «Muéstrame mis reservas» · «Consulta la reserva ABC12345» |
| Modificar | «Cambia mi reserva ABC12345 al martes a las 11:00» |
| Cancelar | «Cancela mi reserva ABC12345» |

Toda creación, modificación o cancelación termina en un resumen que pide **SÍ** (confirmar) o **NO** (descartar). Si escribes «sí» cuando no hay nada pendiente (por ejemplo, una confirmación repetida), el bot responde que no hay ninguna operación pendiente y no cambia nada.

## Datos y navegación

- **Catálogo:** `negocio.json`.
- **SQLite:** `reservas.db` **se crea automáticamente** al iniciar FastAPI (en la carpeta desde donde se ejecuta, o en `RESERVAS_DB`) y se migra sola si es de una versión anterior. No se sube al repositorio (`*.db` en `.gitignore`). Datos de práctica (opcionales): `python datos_prueba.py` carga reservas de ejemplo y `python almacen_sqlite.py --migrar reservas.json` importa las reservas del corte anterior. Esas reservas **no tienen propietario**, por lo que ninguna cuenta de Telegram las ve ni las modifica; para probar el bot, crea reservas desde Telegram. Para empezar de cero, detén la API y borra `reservas.db`.
- **Docker (opcional, del corte anterior):** `docker-compose.yml` levanta la API y la interfaz Gradio (`API_PRIVATE_KEY`, `GROQ_API_KEY` y `GROQ_MODEL` en un archivo `.env` junto al compose). **No incluye el bot de Telegram**, que se ejecuta con `python bot_telegram.py`, y no se probó con la versión final.
- **Documentación:** [Bitácora consolidada](documentacion/Bitacora_Consolidada.md) · [Matriz de 25 pruebas](documentacion/Matriz_25_Pruebas.md) · [Evidencias](evidencias/) · [Presentación PDF](presentacion/Presentacion_Final.pdf)
