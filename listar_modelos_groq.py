"""Muestra los IDs de modelo habilitados para tu clave de Groq (usa la variable GROQ_API_KEY)."""
import json
import os
import urllib.request

clave = os.getenv("GROQ_API_KEY", "").strip()
if not clave:
    raise SystemExit("Define primero la variable GROQ_API_KEY.")

peticion = urllib.request.Request(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {clave}", "User-Agent": "BarberBot/1.0"},
)
with urllib.request.urlopen(peticion, timeout=30) as respuesta:
    for modelo in sorted(m["id"] for m in json.load(respuesta)["data"]):
        print(modelo)
