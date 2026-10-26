import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def proximo(dia_semana, desde=7):
    """Primera fecha futura (lunes=0 ... domingo=6) a partir de hoy + `desde` días."""
    d = date.today() + timedelta(days=desde)
    while d.weekday() != dia_semana:
        d += timedelta(days=1)
    return d.isoformat()


@pytest.fixture
def miercoles():
    return proximo(2)


@pytest.fixture
def domingo():
    return proximo(6)


@pytest.fixture
def ruta_db(tmp_path):
    return tmp_path / "prueba.db"


@pytest.fixture
def cliente(ruta_db):
    from fastapi.testclient import TestClient
    from main import crear_app
    return TestClient(crear_app(ruta_db))
