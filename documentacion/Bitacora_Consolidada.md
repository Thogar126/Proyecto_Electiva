# Bitácora consolidada — BarberBot (Flowise → Gradio → Telegram)

**Equipo:** Thomas García, Juan Rodríguez, Juan José Anduquia, David Hurtado · **Corte:** tercero (final) · **Bot:** [@barberinho_bot](https://t.me/barberinho_bot) · **Repositorio:** `Chatbot_BarberBot_Garcia_Rodriguez_Anduquia_Hurtado`

> **Cómo leer este documento.** Es la documentación principal: explica el proyecto completo y su evolución hasta Telegram. Las afirmaciones sobre el comportamiento verificado enlazan a su evidencia en [`evidencias/`](../evidencias/) y a la [matriz de 25 pruebas](Matriz_25_Pruebas.md).

## 1. Problema, usuarios y alcance

**Problema.** Una barbería con un solo barbero agenda sus citas de forma manual; hay riesgo de dobles reservas y de respuestas lentas sobre precios y horarios.
**Usuarios.** Clientes que escriben desde Telegram. **Atención de una sola agenda:** dos reservas activas no pueden cruzarse.

**Funciones de la versión final**
- Consultar servicios y precios (desde `negocio.json`, vía API) y horas libres por servicio y fecha.
- Crear, consultar, listar, modificar y cancelar reservas **desde Telegram**, siempre con resumen y confirmación escrita («sí» / «no»).
- Reservas **por cuenta**: cada cuenta de Telegram solo ve y cambia las suyas.
- Memoria de la conversación (datos en varios mensajes), `/start`, `/help`, `/reset`.
- Interfaz Gradio del corte anterior, que se conserva.

**Límites**
- Solo texto y chats privados. Fuera de la barbería, el bot debe declinar (regla del prompt; verificar en T15–T17).
- Horario lunes–sábado 09:00–18:00, pasos de 30 min. Sin pagos, recordatorios ni varios barberos.
- El historial y la solicitud pendiente están en memoria: se pierden al reiniciar el bot. Las reservas **no**.
- Las rutas `/api/...` (usadas por Gradio) no tienen autenticación; solo las rutas `/telegram/...` exigen clave privada (ver §8).

## 2. Arquitectura y archivos

```
Telegram → bot_telegram.py → chatbot_memoria.py → consulta_llm.py → Groq (interpreta → plan JSON)
                 │ confirmación «sí/no»                     │ HTTP + X-Clave-Privada + X-Usuario-Telegram
                 └────────────────────────────────► FastAPI: main.py + api_telegram.py → almacen_sqlite.py → reservas.db
```

| Archivo | Estado en el último corte | Responsabilidad |
|---|---|---|
| `bot_telegram.py` | **Ampliado** (en el corte 3a solo consultaba) | Handlers, historial y pendiente por chat, confirmación escrita (SÍ/NO), traducción de errores HTTP. |
| `api_telegram.py` | **Nuevo** | Rutas `/telegram/...`: clave privada, propiedad de reservas, idempotencia. |
| `almacen_sqlite.py` | **Modificado** | Columnas `propietario` y `solicitud_id` (migración automática), `listar_de`, verificación de propietario, `crear` idempotente. |
| `main.py` | **Modificado** | Monta el router de `api_telegram.py`. |
| `consulta_llm.py` | **Modificado** | `ejecutar(..., usuario, solicitud_id)` elige entre `/api` y `/telegram`; cabeceras de la clave privada. |
| `chatbot_memoria.py` | **Modificado** | `procesar_turno(..., usuario)`; regla de prompt para fuera de dominio y no revelar claves. |
| `simular_respuesta_perdida.py` | **Nuevo** | Demuestra que reintentar una confirmación no duplica la reserva. |
| `app_gradio.py`, `negocio.json`, `datos_prueba.py` | Sin cambios | Interfaz web, catálogo, datos de práctica. |
| `tests/` | **Ampliado** (de 26 a 45 pruebas) | `test_telegram_api.py` nuevo; pruebas de confirmación escrita y propiedad en `test_chatbot.py`. |

**Recorrido de una operación (crear):** el mensaje llega a `recibir_texto` → `procesar_turno` pide a Groq un plan JSON, lo normaliza, completa datos faltantes con el historial y devuelve un **resumen** → el bot guarda una solicitud pendiente `{plan, solicitud_id}` y pregunta «Responde SÍ para confirmar o NO para descartar» → cuando la persona escribe «sí» (`resolver_pendiente`), `consulta_llm.ejecutar` hace `POST /telegram/reservas` con la clave privada, la cuenta y el `solicitud_id` → `AgendaSQLite.crear` valida (horario, paso, fecha, cruce) y guarda en una transacción `BEGIN IMMEDIATE` → el bot muestra el código.

## 3. Contexto, memoria y estado

- **Historial por conversación:** `context.chat_data["historial"]` (python-telegram-bot lo separa por chat; en privados equivale a una cuenta). Cada respuesta del asistente se guarda como el plan JSON interpretado, así los datos de un turno (nombre, servicio) siguen disponibles en el siguiente.
- **Propuesta pendiente por cuenta:** `chat_data["pendiente"]`. Una solicitud nueva reemplaza a la anterior (solo hay una pendiente por chat).
- **Un turno fallido no se guarda:** si Groq o la API fallan, el historial queda como estaba.
- **Qué ocurre al reiniciar:** `/reset` limpia historial y pendiente. Reiniciar el proceso del bot hace lo mismo (memoria RAM). **Permanecen** las reservas en SQLite; evidencia en Telegram: [T25](../evidencias/T25_reinicio.png); a nivel de API: [registro](../evidencias/T25_reinicio_persistencia.txt).
- **Identidad de la cuenta:** el `propietario` de una reserva es el `id` numérico de Telegram, no el nombre que la persona escribe como «cliente».

## 4. Operaciones y validaciones

- **Resumen y confirmación.** Ninguna escritura se ejecuta sin que la persona escriba «sí» (los mensajes «sí»/«no» se interceptan antes del modelo). La API refuerza la regla: `confirmada: true` es obligatorio (400 si falta). Descartar no crea fila (prueba `test_boton_descartar_no_crea_fila`).
- **Operaciones desde Telegram.** Crear, consultar, listar (solo las propias), modificar, cancelar.
- **Disponibilidad.** Calculada por la API según duración del servicio y reservas activas; cancelar libera el intervalo ([T21](../evidencias/T21_cancelar_libera.txt)).
- **Cruces.** Se rechazan intervalos que se solapan aunque las horas de inicio sean distintas (corte+barba 10:00–11:00 bloquea un corte a las 10:30); una reserva contigua sí se acepta ([T20](../evidencias/T20_modificar_y_cruce.txt)). La comprobación y el guardado ocurren en la misma transacción.
- **Propiedad.** `GET/PUT/DELETE /telegram/reservas/{codigo}` devuelven **403** «Esa reserva no pertenece a tu cuenta» si el propietario no coincide, y la reserva queda intacta ([T22](../evidencias/T22_reserva_ajena.txt)).
- **Confirmación repetida.** Un segundo «sí» cuando ya no hay nada pendiente responde «No hay ninguna operación pendiente» y no cambia nada. Además, cada confirmación lleva un `solicitud_id`: si la respuesta de la API se pierde y la persona vuelve a escribir «sí», la API devuelve la reserva ya creada con `repetida: true` (HTTP 200) en vez de duplicarla ([T23](../evidencias/T23_confirmacion_repetida.txt), `simular_respuesta_perdida.py`).
- **Manejo de errores.** `texto_error_http` convierte 403/404/409/422 en el mensaje de la API («No se pudo completar… No se modificó ningún dato»), 401/503 en «el bot no está autorizado», y los fallos de red en un aviso para reintentar. Entradas inválidas (fecha pasada, domingo, fuera de horario, fuera de paso, fecha inexistente, clave incorrecta) no guardan nada ([T24](../evidencias/T24_entradas_1.png)).

### Ejemplos con evidencia

**Crear con confirmación ([T18](../evidencias/T18_crear_resumen.png), [T18 confirmada](../evidencias/T18_crear_confirmada.png)).** La persona escribe `Quiero un corte el 2026-11-23 a las 10:00, soy Laura`. El bot responde con un resumen y «Responde SÍ para confirmar o NO para descartar»; al escribir `sí` responde «Reserva creada: CEA6666D · Laura · corte · 2026-11-23 10:00 · activa». Archivos: `bot_telegram.py` (pendiente y «sí»), `consulta_llm.py` (`POST /telegram/reservas`), `almacen_sqlite.py` (guarda con el id de Telegram como `propietario`).

**Rechazo por cruce, datos conservados ([T20](../evidencias/T20_cruce.png), [registro](../evidencias/T20_modificar_y_cruce.txt)).** Con una reserva de 60 min a las 10:00, pedir un corte a las 10:30 devuelve HTTP 409 «El intervalo solicitado se cruza con una reserva activa» y no se crea ninguna fila. Al mover una reserva a una hora ocupada la API responde 409 «El nuevo intervalo está ocupado» y la reserva conserva su fecha y hora anteriores.

**Reserva de otra cuenta ([T22](../evidencias/T22_reserva_ajena.png), [registro](../evidencias/T22_reserva_ajena.txt)).** La cuenta B intenta consultar, modificar o cancelar la reserva de A: la API responde 403 «Esa reserva no pertenece a tu cuenta» y la fila de A queda intacta. Archivos: `api_telegram.py` (`exigir_propietario`) y `almacen_sqlite.py` (`ReservaAjena`).

**Confirmación repetida ([T23](../evidencias/T23_confirmacion_repetida.png)).** Un segundo `sí` responde «No hay ninguna operación pendiente» y no se duplica la reserva.

**Cancelar libera el horario ([T21](../evidencias/T21_cancelar.png)).** Tras cancelar, la reserva pasa a `cancelada` y la consulta de horas libres vuelve a mostrar el intervalo ([antes](../evidencias/T21_consulta_antes.png), [después](../evidencias/T21_consulta_despues.png)).

## 5. Evolución y decisiones

| Corte | Herramienta | Qué se hizo |
|---|---|---|
| 1 | **Flowise** | **[COMPLETAR]** flujo, nodos usados y límites encontrados (conversación y consulta del catálogo). |
| 2 | **Gradio + FastAPI + SQLite** | Reservas reales: planes JSON de Groq, memoria, resumen y confirmación, validación de cruces, persistencia, migración desde JSON (`reservas.json`). |
| 3a | **Telegram (solo consulta)** | `bot_telegram.py` reutiliza `procesar_turno`; solo servicios y disponibilidad. Las escrituras se explicaban pero no se ejecutaban. |
| 3b | **Telegram (final)** | Escrituras con confirmación escrita, reservas por cuenta, clave privada, idempotencia. |

**Qué se reutilizó:** `chatbot_memoria.py`, `consulta_llm.py`, `almacen_sqlite.py`, `negocio.json`, las reglas de cruce y el patrón «resumen → confirmar» del corte de Gradio.
**Qué cambió y por qué**
- *Rutas separadas `/telegram` y `/api`.* Gradio no tiene identidad de usuario; Telegram sí. Separarlas permitió exigir clave y propietario solo donde hay cuentas, sin romper la interfaz anterior.
- *Propietario = id de Telegram.* El nombre escrito puede repetirse o falsearse; el id lo entrega Telegram.
- *Confirmación escrita («sí»/«no») en lugar de botones.* Decisión del equipo: es más simple de mantener y de probar. El bot intercepta esos mensajes antes del modelo, así la confirmación no depende de la interpretación de Groq y solo actúa sobre la solicitud pendiente de ese chat.
- *`solicitud_id` además de ignorar un «sí» repetido.* Ignorar el segundo «sí» no protege cuando la respuesta de la API se pierde y la solicitud sigue pendiente; la idempotencia en la API sí.
- *Clave privada compartida y API cerrada si falta (503).* Mejor fallar cerrado que dejar rutas abiertas por olvido de configuración.
- *Estado en memoria.* Simple y suficiente para el alcance; se documenta como límite.

## 6. Pruebas y evidencias

- **Automáticas:** 45 pruebas aprobadas ([`evidencias/pytest_resultado.txt`](../evidencias/pytest_resultado.txt)): API (crear, cruce, contigua, modificar, cancelar, validaciones, persistencia, concurrencia, migración), chatbot con un modelo simulado (varios turnos, código desde el historial, errores sin tocar el historial), y la capa de Telegram (clave privada, dos cuentas, reserva ajena, confirmación repetida, «sí»/«no» escritos, respuesta perdida con reintento, descartar).
- **Registros reales de API + SQLite** (T18–T25) generados con [`evidencias/verificar_backend.py`](../evidencias/verificar_backend.py).
- **Matriz de 25 casos:** [Matriz_25_Pruebas.md](Matriz_25_Pruebas.md). **Estado: 25 de 25 ejecutados en Telegram**, con una o más capturas por caso en [`evidencias/`](../evidencias/) (`Txx_nombre.png`) enlazadas desde la matriz. Los registros de API + SQLite respaldan el efecto real en los datos.
- **Evidencia previa de Telegram:** [`evidencias/problema_integracion_clase11.png`](../evidencias/problema_integracion_clase11.png) muestra la versión de solo consulta (servicios, fecha y petición del nombre). Sus duraciones (barba 60 min, corte+barba 90 min) no coinciden con el `negocio.json` actual (30 y 60 min), porque el catálogo cambió después; por eso no se usa como evidencia de T01.

## 7. Fallos y correcciones

| # | Caso de la matriz | Fallo / hallazgo | Causa | Corrección | Verificación |
|---|---|---|---|---|---|
| 1 | — | **[COMPLETAR]** el «problema de integración» de la Clase 11 (ver captura del §6) | **[COMPLETAR]** | **[COMPLETAR]** | **[COMPLETAR]** |
| 2 | T18, T20, T21 | El bot de Telegram anunciaba crear/modificar/cancelar pero «no se ejecutaba» | Versión 3a de solo lectura | Confirmación escrita + rutas `/telegram` (§2, §4) | [T18](../evidencias/T18_crear_confirmada.png), T19–T22 y pruebas de confirmación escrita |
| 3 | T19, T22 | `listar` y `consultar` por Telegram habrían mostrado reservas de cualquier persona | Las rutas `/api` no distinguen cuentas | `listar` por propietario y verificación 403 | `test_listar_solo_muestra_las_propias`, T19, T22 |
| 4 | T23 | Una confirmación repetida (o respuesta perdida) podía crear dos reservas | No había identificador de solicitud | `solicitud_id` único; la segunda respuesta es 200 `repetida` | [T23](../evidencias/T23_confirmacion_repetida.png), `simular_respuesta_perdida.py` |
| 5 | T15, T16, T17 | El prompt no tenía regla para temas ajenos ni para revelar instrucciones | Solo decía «conversar: preguntas generales» | Reglas explícitas en `PROMPT` | T15–T17 en Telegram ([T15](../evidencias/T15_fuera_deporte.png), [T16](../evidencias/T16_fuera_codigo.png), [T17](../evidencias/T17_instrucciones.png)); depende del modelo |
| 6 | — | Un `Dockerfile` que no copiaba `api_telegram.py` rompería el contenedor | Archivo nuevo no listado en `COPY` | Añadido al `COPY` | **No verificado** (no se ejecutó Docker) |
| 7 | T18, T11 | En las primeras pruebas el modelo respondía «¿Confirmas…?» o listaba horarios en vez de crear la reserva, aunque ya tenía nombre, servicio, fecha y hora | La acción elegida por Groq variaba | Regla en `PROMPT` y función `corregir_accion`: con los 4 datos, la acción pasa a «crear» | Pruebas automáticas y flujo real de [T18](../evidencias/T18_crear_resumen.png) |
| 8 | T25, T24 | «No pude conectarme con Groq o FastAPI» de forma intermitente | Fallos de red momentáneos o API apagada | `llamar_groq` reintenta una vez ante errores de red | Revisión de `/health` y [T25](../evidencias/T25_api_apagada.png) |
| 9 | — | Error HTTP 429 al hablar con el bot | Límite de peticiones del plan gratuito de Groq | El bot explica el límite; esperar o usar otra clave o modelo | Mensaje visible en Telegram |

**Cómo se relaciona cada corrección con su evidencia.** La columna «Caso de la matriz» indica qué caso detectó o comprobó el fallo; «Verificación» enlaza la captura de la repetición. Ejemplo (fallo 7): en el primer intento de T18 el modelo respondió pidiendo confirmación en vez de crear; se añadió la regla al prompt y `corregir_accion`, y al repetir T18 apareció el resumen y luego «Reserva creada».

_Pruebas cercanas repetidas tras los cambios:_ la suite completa (45 pruebas) se ejecutó al terminar los cambios de `almacen_sqlite.py`, `consulta_llm.py`, `chatbot_memoria.py` y del prompt, y pasó completa; incluye las pruebas del flujo de Gradio (`/api`), que siguen aprobadas.

## 8. Limitaciones y pendientes

- Rutas `/api/...` sin autenticación (heredadas del corte de Gradio); en producción habría que cerrarlas o protegerlas.
- Historial y pendiente en memoria; un reinicio del bot descarta las solicitudes sin confirmar.
- Sin pruebas con Groq ni Telegram reales en CI: esas piezas se probaron con simulaciones.
- Un token de Telegram solo puede escuchar desde una máquina a la vez (error *Conflict*); las pruebas se hicieron desde una sola.
- Groq gratuito tiene límite de peticiones (HTTP 429).
- Docker/Compose conservados del corte anterior y no probados con el bot de Telegram.
- Reservas anteriores a esta versión no tienen propietario (`NULL`): ninguna cuenta de Telegram puede verlas ni modificarlas.
