# BarberBot · chatbot de reservas para una barbería

Chatbot que consulta servicios y horarios, y permite **crear, modificar y cancelar reservas sin cruces de horario**.

- **API**: FastAPI + SQLite (`main.py`, `almacen_sqlite.py`)
- **Vista**: Gradio (`app_gradio.py`)
- **IA**: Groq interpreta el mensaje (`consulta_llm.py`, `chatbot_memoria.py`)
- **Despliegue**: Docker Compose (`Dockerfile`, `docker-compose.yml`)

```text
Navegador → Gradio (7860) → chatbot_memoria → Groq
                  │
                  └─ HTTP → FastAPI (8011) → AgendaSQLite → reservas.db
```

---

## 0. Revisar si tienes Python (Windows)

Abre PowerShell (o la terminal de Visual Studio Code: `Ctrl + ñ`) y ejecuta:

```powershell
python --version
py --version
```

- Si ves `Python 3.10` o superior (ideal 3.12): listo. Gradio 6 necesita **3.10 o más**.
- Si dice que no se reconoce el comando, o abre la Microsoft Store: instala Python desde <https://www.python.org/downloads/> y **marca «Add python.exe to PATH»** en el instalador. Cierra y vuelve a abrir la terminal.
- `py -0` lista todas las versiones instaladas.
- En Visual Studio Code instala la extensión **Python** y elige el intérprete con `Ctrl + Shift + P` → *Python: Select Interpreter* (debe apuntar a `.venv`, ver paso 1).

Para Docker: `docker --version` y `docker compose version` (instala Docker Desktop si no responde).

## 1. Instalación local

Desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> Si PowerShell bloquea scripts no necesitas activar el entorno: todos los comandos usan la ruta explícita a `.venv`.

## 2. Ejecutar sin Docker (dos terminales)

**Terminal 1 · API**

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8011
```

Prueba en <http://127.0.0.1:8011/docs>: consulta, crea, modifica y cancela. Aparecerá `reservas.db`.

**Terminal 2 · Gradio**

```powershell
.\.venv\Scripts\python.exe listar_modelos_groq.py        # opcional: ver modelos habilitados
$env:CHATBOT_API_URL = "http://127.0.0.1:8011"
$env:GROQ_MODEL = "ID_DEL_MODELO_HABILITADO_EN_GROQ"
$clave = Read-Host "API key de Groq" -AsSecureString
$env:GROQ_API_KEY = [System.Net.NetworkCredential]::new('', $clave).Password
.\.venv\Scripts\python.exe app_gradio.py
```

Abre <http://127.0.0.1:7860>. (Para `listar_modelos_groq.py` define antes `GROQ_API_KEY`.)
Si cambias una variable, reinicia el proceso.

> **Groq cambia su lista de modelos con frecuencia.** No te dejo uno fijo: usa `listar_modelos_groq.py` o <https://console.groq.com/docs/models> y elige uno de texto habilitado en tu cuenta.

## 3. Ejecutar con Docker

```powershell
Copy-Item .env.example .env      # luego edita .env con tu GROQ_API_KEY y GROQ_MODEL
docker compose up --build
```

- Gradio: <http://127.0.0.1:7860> · API: <http://127.0.0.1:8011/docs>
- La base queda en `./data/reservas.db` (volumen), así que **sobrevive a reinicios**: `docker compose restart api`.
- Detener: `docker compose down`.
- `.env` está en `.gitignore` y `.dockerignore`: la clave no entra a la imagen ni al repositorio.
- En Linux, si `./data` da error de permisos: `mkdir data && sudo chown 1000:1000 data`.

## 4. Pruebas automáticas

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Cubren: cruce de 60 min vs 30 min a otra hora (409), reserva contigua (aceptada), modificar a libre/ocupado
(conserva datos), cancelar libera el intervalo, fechas inválidas/domingo/fuera de horario, 8 hilos
compitiendo por el mismo intervalo (gana solo uno), persistencia, migración, y el flujo del chatbot en varios turnos.

## 5. Datos de prueba y migración

```powershell
.\.venv\Scripts\python.exe datos_prueba.py                 # 3 reservas de ejemplo
.\.venv\Scripts\python.exe almacen_sqlite.py --migrar reservas.json --negocio negocio.json --base reservas.db
.\.venv\Scripts\python.exe -m sqlite3 reservas.db "SELECT codigo, cliente, fecha, hora, estado FROM reservas;"
```

(`-m sqlite3` requiere Python 3.12+. En versiones anteriores usa el fragmento del laboratorio.)

## 6. Cómo ajustar el negocio

Todo sale de `negocio.json`: nombre, horario (`apertura`, `cierre`, `dias` con lunes=0, `paso_minutos`) y
servicios (`precio_cop`, `duracion_minutos` entero). Al cambiarlo, el chatbot y la API lo leen solos.

## 7. Endpoints

| Método | Ruta | Acción | Errores |
|---|---|---|---|
| GET | `/health` | Estado del servicio | |
| GET | `/api/servicios` | Catálogo | |
| GET | `/api/disponibilidad?fecha=&servicio=` | Horas libres | 422 |
| GET | `/api/reservas` | Listar | |
| GET | `/api/reservas/{codigo}` | Consultar | 404 |
| POST | `/api/reservas` | Crear (`confirmada: true`) | 400, 409, 422 |
| PUT | `/api/reservas/{codigo}` | Modificar | 404, 409, 422 |
| DELETE | `/api/reservas/{codigo}` | Cancelar | 404, 409 |

**«Eliminar» = cancelar:** la fila pasa a `estado = 'cancelada'`, libera el intervalo y se conserva como histórico (así lo pide el laboratorio).

## 8. Buenas prácticas aplicadas

- Una sola fuente de verdad (SQLite) y toda la lógica de horarios en la API, nunca en el chatbot ni en la interfaz.
- Comprobación de cruce **y** guardado en una transacción (`BEGIN IMMEDIATE`); consultas parametrizadas (`?`).
- El modelo solo propone un plan: **nada se escribe sin pulsar «Confirmar operación»** y la API vuelve a validar.
- Un turno fallido no se guarda en el historial; el estado es por sesión (`gr.State`).
- Secretos solo por variables de entorno; imagen Docker con usuario sin privilegios, dependencias fijadas por rango y *healthcheck*.
- Pruebas automáticas sin red (LLM simulado).

## 9. Preguntas de la entrega (para tu bitácora)

- **¿Qué función recibe el mensaje?** `enviar()` en `app_gradio.py` (botón *Enviar* o Enter). Llama a `procesar_turno()` en `chatbot_memoria.py`.
- **¿Dónde vive el historial?** En `estado["historial"]` (un `gr.State` por sesión del navegador), que se envía a Groq en cada turno. `estado["pantalla"]` es solo lo que ve la persona.
- **¿Qué mensajes llegan a Groq?** El `system` (reglas, servicios, horario, fecha de hoy) más los turnos previos y el nuevo. La API key va solo en la cabecera HTTP, nunca en el historial.
- **¿Cuándo se llama a FastAPI?** Consultas (servicios, disponibilidad, reservas): al procesar el turno. Crear/modificar/cancelar: solo en `confirmar()` → `ejecutar(plan, confirmar=True)`.
- **¿Qué endpoint ejecuta cada operación?** Ver tabla de la sección 7.
- **¿Qué SQL corresponde?** `SELECT ... WHERE fecha=? AND estado='activa'` (comprobar cruces), `INSERT INTO reservas VALUES (...)` (crear), `UPDATE reservas SET servicio=?, fecha=?, hora=?, duracion_minutos=? WHERE codigo=?` (modificar), `UPDATE reservas SET estado='cancelada' WHERE codigo=?` (cancelar).
- **¿Por qué comprobar y guardar en la misma transacción?** Dos personas pueden ver libre el mismo horario. `BEGIN IMMEDIATE` bloquea las escrituras: la segunda espera, vuelve a leer las reservas ya con la primera guardada, detecta el cruce y recibe 409. Si comprobara y guardara por separado, ambas podrían insertar.
- **Regla de cruce:** `inicio_nuevo < fin_existente AND fin_nuevo > inicio_existente` (terminar justo cuando otra empieza **no** es cruce).

## 10. Estructura

```text
barberbot/
├── main.py               API FastAPI
├── almacen_sqlite.py     SQLite: tabla, transacciones, disponibilidad (entregado por el curso)
├── consulta_llm.py       HTTP hacia Groq y FastAPI
├── chatbot_memoria.py    historial, plan y confirmación
├── app_gradio.py         vista Gradio
├── negocio.json          catálogo y horario
├── reservas.json         ejemplo para migrar
├── datos_prueba.py · listar_modelos_groq.py
├── Dockerfile · docker-compose.yml · .env.example
├── requirements.txt · requirements-dev.txt
├── tests/
└── BITACORA.md           plantilla de evidencias
```

## Solución de problemas

| Síntoma | Causa probable |
|---|---|
| «Configura GROQ_API_KEY y GROQ_MODEL» | Variables no definidas en esa terminal; reinicia Gradio |
| «No pude conectar con Groq o FastAPI» | API apagada o `CHATBOT_API_URL` incorrecta |
| `Error HTTP 400/404` de Groq | Modelo no habilitado: revisa `GROQ_MODEL` |
| `Error HTTP 409` | Intervalo ocupado: descarta y elige otra hora |
| `Error HTTP 422` | Fecha/hora inválida, domingo, fuera de horario o fecha pasada |
