FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESERVAS_DB=/data/reservas.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py almacen_sqlite.py consulta_llm.py chatbot_memoria.py app_gradio.py negocio.json ./

# Usuario sin privilegios; /data guarda reservas.db
RUN useradd --create-home --uid 1000 barber \
    && mkdir /data && chown barber:barber /data
USER barber

EXPOSE 8011 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8011"]
