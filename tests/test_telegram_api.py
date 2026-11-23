"""Pruebas de las rutas /telegram: clave privada, propiedad de reservas e idempotencia."""
import pytest

CLAVE = "clave-de-pruebas"


@pytest.fixture(autouse=True)
def clave_privada(monkeypatch):
    monkeypatch.setenv("API_PRIVATE_KEY", CLAVE)


def cab(usuario="111", clave=CLAVE):
    return {"X-Clave-Privada": clave, "X-Usuario-Telegram": usuario}


def crear(cliente, fecha, hora, usuario="111", servicio="corte", solicitud="solicitud-0001"):
    return cliente.post("/telegram/reservas", headers=cab(usuario), json={
        "cliente": "Laura", "servicio": servicio, "fecha": fecha, "hora": hora,
        "confirmada": True, "solicitud_id": solicitud})


def test_sin_clave_o_con_clave_incorrecta(cliente, miercoles):
    assert cliente.get("/telegram/reservas").status_code == 401
    assert cliente.get("/telegram/reservas", headers=cab(clave="otra")).status_code == 401
    assert cliente.get("/telegram/reservas", headers=cab(usuario="abc")).status_code == 400


def test_api_cerrada_si_no_hay_clave_configurada(cliente, monkeypatch):
    monkeypatch.delenv("API_PRIVATE_KEY")
    assert cliente.get("/telegram/reservas", headers=cab()).status_code == 503


def test_dos_cuentas_ven_solo_lo_suyo(cliente, miercoles):
    a = crear(cliente, miercoles, "10:00", "111", solicitud="solicitud-A001").json()
    b = crear(cliente, miercoles, "11:00", "222", solicitud="solicitud-B001").json()
    assert [r["codigo"] for r in cliente.get("/telegram/reservas", headers=cab("111")).json()] == [a["codigo"]]
    assert [r["codigo"] for r in cliente.get("/telegram/reservas", headers=cab("222")).json()] == [b["codigo"]]


def test_reserva_ajena_se_rechaza_y_no_cambia(cliente, miercoles):
    a = crear(cliente, miercoles, "10:00", "111").json()
    ruta = f"/telegram/reservas/{a['codigo']}"
    assert cliente.get(ruta, headers=cab("222")).status_code == 403
    r = cliente.put(ruta, headers=cab("222"), json={"servicio": "corte", "fecha": miercoles, "hora": "15:00"})
    assert r.status_code == 403
    assert cliente.delete(ruta, headers=cab("222")).status_code == 403
    intacta = cliente.get(ruta, headers=cab("111")).json()
    assert intacta["hora"] == "10:00" and intacta["estado"] == "activa"


def test_modificar_y_cancelar_propia(cliente, miercoles):
    a = crear(cliente, miercoles, "10:00").json()
    ruta = f"/telegram/reservas/{a['codigo']}"
    r = cliente.put(ruta, headers=cab(), json={"servicio": "corte", "fecha": miercoles, "hora": "15:00"})
    assert r.status_code == 200 and r.json()["hora"] == "15:00"
    assert cliente.delete(ruta, headers=cab()).json()["estado"] == "cancelada"
    assert cliente.delete(ruta, headers=cab()).status_code == 409


def test_cruce_entre_cuentas_se_rechaza(cliente, miercoles):
    assert crear(cliente, miercoles, "10:00", "111", "corte_barba", "solicitud-A001").status_code == 201
    r = crear(cliente, miercoles, "10:30", "222", "corte", "solicitud-B001")
    assert r.status_code == 409
    assert cliente.get("/telegram/reservas", headers=cab("222")).json() == []


def test_confirmacion_repetida_no_duplica(cliente, miercoles):
    primera = crear(cliente, miercoles, "10:00")
    segunda = crear(cliente, miercoles, "10:00")
    assert primera.status_code == 201 and segunda.status_code == 200
    assert segunda.json()["repetida"] is True and segunda.json()["codigo"] == primera.json()["codigo"]
    assert len(cliente.get("/telegram/reservas", headers=cab()).json()) == 1


def test_crear_exige_confirmacion(cliente, miercoles):
    r = cliente.post("/telegram/reservas", headers=cab(), json={
        "cliente": "Ana", "servicio": "corte", "fecha": miercoles, "hora": "10:00",
        "confirmada": False, "solicitud_id": "solicitud-0002"})
    assert r.status_code == 400
    assert cliente.get("/telegram/reservas", headers=cab()).json() == []


def test_base_anterior_se_migra(ruta_db, miercoles):
    import sqlite3
    from almacen_sqlite import AgendaSQLite
    from main import cargar_negocio
    con = sqlite3.connect(ruta_db)
    con.execute("""CREATE TABLE reservas (codigo TEXT PRIMARY KEY, cliente TEXT NOT NULL, servicio TEXT NOT NULL,
        fecha TEXT NOT NULL, hora TEXT NOT NULL, duracion_minutos INTEGER NOT NULL, estado TEXT NOT NULL)""")
    con.execute("INSERT INTO reservas VALUES ('VIEJA001','Ana','corte',?,'10:00',30,'activa')", (miercoles,))
    con.commit(); con.close()
    agenda = AgendaSQLite(ruta_db, cargar_negocio()["servicios"])
    assert agenda.consultar("VIEJA001")["propietario"] is None
