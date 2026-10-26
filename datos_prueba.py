"""Carga reservas de ejemplo en la base (útil para las evidencias de la entrega).

Uso:  python datos_prueba.py [ruta_a_reservas.db]
"""
import sys
from datetime import date, timedelta
from pathlib import Path

from almacen_sqlite import AgendaSQLite, ConflictoReserva
from main import cargar_negocio

BASE = Path(__file__).resolve().parent


def proximo(dia_semana, desde=7):
    d = date.today() + timedelta(days=desde)
    while d.weekday() != dia_semana:
        d += timedelta(days=1)
    return d.isoformat()


def main(ruta):
    negocio = cargar_negocio()
    h = negocio["horario"]
    agenda = AgendaSQLite(ruta, negocio["servicios"], apertura=h["apertura"], cierre=h["cierre"],
                          dias=tuple(h["dias"]), paso=h["paso_minutos"])
    lunes, martes = proximo(0), proximo(1)
    for cliente, servicio, fecha, hora in [
        ("Laura", "corte", lunes, "10:00"),
        ("Andrés", "corte_barba", lunes, "11:00"),
        ("Camilo", "tinte", martes, "09:00"),
    ]:
        try:
            print("creada:", agenda.crear(cliente, servicio, fecha, hora)["codigo"], cliente, fecha, hora)
        except ConflictoReserva:
            print("ya ocupado:", cliente, fecha, hora)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else BASE / "reservas.db")
