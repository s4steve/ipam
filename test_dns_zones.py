import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

VALID_ZONE = {
    "name": "example.com",
    "description": "Primary zone",
    "soa": {
        "mname": "ns1.example.com",
        "rname": "admin.example.com",
        "serial": 2024010101,
        "refresh": 3600,
        "retry": 600,
        "expire": 604800,
        "minimum": 86400,
    },
}


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# -- Create -------------------------------------------------------------------


def test_create_zone():
    resp = client.post("/dns-zones/", json=VALID_ZONE)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "example.com"
    assert data["description"] == "Primary zone"
    assert data["soa"]["mname"] == "ns1.example.com"
    assert data["soa"]["rname"] == "admin.example.com"
    assert data["soa"]["serial"] == 2024010101
    assert data["soa"]["refresh"] == 3600
    assert data["soa"]["retry"] == 600
    assert data["soa"]["expire"] == 604800
    assert data["soa"]["minimum"] == 86400
    assert "id" in data


def test_create_zone_defaults():
    body = {
        "name": "default.example.com",
        "soa": {"mname": "ns1.default.example.com", "rname": "admin.default.example.com"},
    }
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] is None
    assert data["soa"]["serial"] == 1
    assert data["soa"]["refresh"] == 3600
    assert data["soa"]["retry"] == 600
    assert data["soa"]["expire"] == 604800
    assert data["soa"]["minimum"] == 86400


def test_create_zone_duplicate():
    client.post("/dns-zones/", json=VALID_ZONE)
    resp = client.post("/dns-zones/", json=VALID_ZONE)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_create_zone_invalid_name_single_label():
    body = {**VALID_ZONE, "name": "localhost"}
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 422


def test_create_zone_invalid_name_bad_chars():
    body = {**VALID_ZONE, "name": "ex ample.com"}
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 422


def test_create_zone_invalid_soa_mname():
    body = {**VALID_ZONE, "soa": {**VALID_ZONE["soa"], "mname": "bad"}}
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 422


def test_create_zone_invalid_serial_negative():
    body = {**VALID_ZONE, "soa": {**VALID_ZONE["soa"], "serial": -1}}
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 422


def test_create_zone_invalid_serial_too_large():
    body = {**VALID_ZONE, "soa": {**VALID_ZONE["soa"], "serial": 4294967296}}
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 422


def test_create_zone_invalid_refresh_zero():
    body = {**VALID_ZONE, "soa": {**VALID_ZONE["soa"], "refresh": 0}}
    resp = client.post("/dns-zones/", json=body)
    assert resp.status_code == 422


# -- Read ---------------------------------------------------------------------


def test_list_zones_empty():
    resp = client.get("/dns-zones/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_zones():
    client.post("/dns-zones/", json=VALID_ZONE)
    resp = client.get("/dns-zones/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "example.com"


def test_get_zone_by_id():
    create_resp = client.post("/dns-zones/", json=VALID_ZONE)
    zone_id = create_resp.json()["id"]
    resp = client.get(f"/dns-zones/{zone_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "example.com"


def test_get_zone_not_found():
    resp = client.get("/dns-zones/999")
    assert resp.status_code == 404


# -- Update -------------------------------------------------------------------


def test_update_zone_name():
    create_resp = client.post("/dns-zones/", json=VALID_ZONE)
    zone_id = create_resp.json()["id"]
    resp = client.put(f"/dns-zones/{zone_id}", json={"name": "updated.com"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated.com"


def test_update_zone_description():
    create_resp = client.post("/dns-zones/", json=VALID_ZONE)
    zone_id = create_resp.json()["id"]
    resp = client.put(f"/dns-zones/{zone_id}", json={"description": "New desc"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "New desc"


def test_update_zone_soa():
    create_resp = client.post("/dns-zones/", json=VALID_ZONE)
    zone_id = create_resp.json()["id"]
    new_soa = {
        "mname": "ns2.example.com",
        "rname": "hostmaster.example.com",
        "serial": 2024010102,
        "refresh": 7200,
        "retry": 1200,
        "expire": 1209600,
        "minimum": 172800,
    }
    resp = client.put(f"/dns-zones/{zone_id}", json={"soa": new_soa})
    assert resp.status_code == 200
    data = resp.json()
    assert data["soa"]["mname"] == "ns2.example.com"
    assert data["soa"]["serial"] == 2024010102
    assert data["soa"]["refresh"] == 7200


def test_update_zone_not_found():
    resp = client.put("/dns-zones/999", json={"name": "nope.com"})
    assert resp.status_code == 404


def test_update_zone_name_conflict():
    client.post("/dns-zones/", json=VALID_ZONE)
    other = {**VALID_ZONE, "name": "other.com"}
    create_resp = client.post("/dns-zones/", json=other)
    zone_id = create_resp.json()["id"]
    resp = client.put(f"/dns-zones/{zone_id}", json={"name": "example.com"})
    assert resp.status_code == 409


# -- Delete -------------------------------------------------------------------


def test_delete_zone():
    create_resp = client.post("/dns-zones/", json=VALID_ZONE)
    zone_id = create_resp.json()["id"]
    resp = client.delete(f"/dns-zones/{zone_id}")
    assert resp.status_code == 204

    resp = client.get(f"/dns-zones/{zone_id}")
    assert resp.status_code == 404


def test_delete_zone_not_found():
    resp = client.delete("/dns-zones/999")
    assert resp.status_code == 404
