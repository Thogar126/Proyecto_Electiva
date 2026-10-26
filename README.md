# BarberBot

BarberBot es un chatbot para la gestión de reservas en una barbería. Permite consultar información del negocio, atender solicitudes de los clientes y gestionar las reservas mediante una interfaz conversacional.

## Características

- Atención al cliente mediante un chatbot.
- Gestión de reservas.
- Consulta de información del negocio desde `negocio.json`.
- Almacenamiento de información mediante SQLite.
- Memoria de conversación.
- Integración con modelos de lenguaje mediante una API.
- Interfaz gráfica con Gradio.
- Integración con Telegram.

## Tecnologías utilizadas

- Python
- SQLite
- Gradio
- API de modelos de lenguaje
- Telegram Bot API

## Requisitos

- Python instalado.
- Una clave API para el modelo de lenguaje utilizado.
- Un token de Telegram si se desea ejecutar el bot de Telegram.

## Instalación

1. Clonar el repositorio:

   ```bash
   git clone https://github.com/Thogar126/Proyecto_Electiva.git
   ```

2. Entrar en la carpeta del proyecto:

   ```bash
   cd Proyecto_Electiva
   ```

3. Crear un entorno virtual:

   ```bash
   python -m venv .venv
   ```

4. Activar el entorno virtual en Windows:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

5. Instalar las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

## Configuración

Configurar las claves de API y los tokens necesarios antes de ejecutar los componentes que los utilizan. No publicar credenciales privadas en el repositorio.

Revisar `negocio.json` para establecer la información correspondiente a la barbería.

## Ejecución

Ejecutar el archivo principal:

```bash
python main.py
```

Para iniciar la interfaz de Gradio:

```bash
python app_gradio.py
```

Para iniciar el bot de Telegram:

```bash
python bot_telegram.py
```

## Estructura del proyecto

- `main.py`: punto de entrada principal.
- `chatbot_memoria.py`: lógica del chatbot y memoria conversacional.
- `consulta_llm.py`: comunicación con el modelo de lenguaje.
- `almacen_sqlite.py`: almacenamiento de datos con SQLite.
- `app_gradio.py`: interfaz web con Gradio.
- `bot_telegram.py`: integración con Telegram.
- `negocio.json`: información del negocio.
- `requirements.txt`: dependencias del proyecto.
