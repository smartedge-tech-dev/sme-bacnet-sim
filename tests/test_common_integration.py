"""sme-sim-common integration: engine protocol, i18n namespaces, standard routes."""

import datetime
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sme_sim_common.engine import EngineProtocol
from sme_sim_common.testing import check_i18n_keys

from sme_bacnet_sim import __version__
from sme_bacnet_sim.config import load_file
from sme_bacnet_sim.engine import Engine
from sme_bacnet_sim.web import create_app

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "configs" / "demo-building.yaml"


def test_engine_follows_protocol():
    engine = Engine(load_file(DEMO), config_path=str(DEMO), config_text=DEMO.read_text(encoding="utf-8"))
    assert isinstance(engine, EngineProtocol)
    ev = engine.log_event("info", "hello", kind="test")
    assert ev["message"] == "hello" and ev["kind"] == "test" and engine.events[-1] is ev


def test_no_reserved_i18n_keys():
    assert not check_i18n_keys(ROOT / "sme_bacnet_sim" / "static")


def test_standard_routes():
    text = DEMO.read_text(encoding="utf-8")
    engine = Engine(load_file(DEMO), config_path=str(DEMO), config_text=text)
    client = TestClient(create_app(engine))  # no lifespan: the BACnet stack is not started
    page = client.get("/").text
    assert "__SME_SIM_COMMON_VERSION__" not in page and 'data-storage="sme-bacnet-sim"' in page
    assert client.get("/sme-sim-common/shell/shell.js").status_code == 200
    assert client.get("/api/config").text == text  # the file text, comments included
    assert client.get("/api/version").json()["version"] == __version__
    assert client.get("/api/templates").json()


@contextmanager
def _client():
    """One event loop for all requests; the engine is not started by the app (``manage_engine=False``), but a
    reload binds the BACnet devices, so they are stopped on that loop (no leaked transports)."""
    text = DEMO.read_text(encoding="utf-8")
    engine = Engine(load_file(DEMO), config_path=str(DEMO), config_text=text)
    with TestClient(create_app(engine, manage_engine=False)) as client:
        try:
            yield engine, client
        finally:
            client.portal.call(engine.stop)


def test_product_routes_are_flat():
    from fastapi.routing import APIRoute

    with _client() as (engine, client):
        paths = {r.path for r in client.app.routes if isinstance(r, APIRoute)}
        assert "/api/devices/{device_id}/objects/paste" in paths and "/api/network" in paths
        old = {"/api/simulation/clock", "/api/config/import-ede", "/api/devices/{device_id}/config"}
        assert not old & {getattr(r, "path", None) for r in client.app.routes}


def test_device_routes_int_key():
    with _client() as (engine, client):
        ids = {d.device_id for d in engine.config.devices}
        r = client.post("/api/devices", json={"name": "New-Dev"})
        assert r.status_code == 200, r.text
        new = r.json()["name"]
        assert isinstance(new, int) and new >= 1001 and new not in ids and new in {d.device_id for d in engine.config.devices}
        r = client.post(f"/api/devices/{new}/duplicate")
        assert r.status_code == 200, r.text
        dup = r.json()
        assert dup["name"] == max(ids | {new}) + 1 and dup["device"]["name"] == "New-Dev (copy)"
        assert "device_id: %d" % new in client.get(f"/api/devices/{new}/config").text
        assert client.post("/api/devices", json={"device_id": new, "name": "X"}).status_code == 409
        assert client.delete(f"/api/devices/{dup['name']}").status_code == 200
        r = client.delete(f"/api/devices/{dup['name']}")
        assert r.status_code == 404 and r.json()["error"]
        assert client.post("/api/devices/abc/duplicate").status_code in (400, 404)


def test_simulation_set_time():
    with _client() as (engine, client):
        ts = datetime.datetime(2030, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
        r = client.post("/api/simulation", json={"set_time": ts.isoformat().replace("+00:00", "Z")})
        assert r.status_code == 200, r.text
        assert abs(engine.sim_epoch + engine.sim_time - ts.timestamp()) < 1 and "running" in r.json()
        r = client.post("/api/simulation", json={"set_time": "not a time"})
        assert r.status_code == 400 and r.json()["error"]
        assert client.post("/api/simulation", json={"bogus": 1}).status_code == 400


def test_import_hooks():
    with _client() as (engine, client):
        n = len(engine.config.devices)
        ede = client.get("/api/config/export", params={"format": "ede"}).content
        r = client.post("/api/config/import", files={"file": ("points.zip", ede)})
        assert r.status_code == 200, r.text
        assert len(engine.config.devices) == n and isinstance(r.json()["warnings"], list)
        text = DEMO.read_text(encoding="utf-8")
        r = client.post("/api/config/import", files={"file": ("demo.yaml", text.encode("utf-8"))})
        assert r.status_code == 200 and client.get("/api/config").text == text
        js = client.get("/api/config/export", params={"format": "json"}).content
        assert client.post("/api/config/import", files={"file": ("c.json", js)}).status_code == 200
        r = client.post("/api/config/import", files={"file": ("bad.yaml", b"devices: [{name: x}]")})
        assert r.status_code == 400 and r.json()["error"]
        r = client.post("/api/config/import", files={"file": ("bad.xlsx", b"not a workbook")})
        assert r.status_code == 400 and r.json()["errors"]  # the error list is at the top level
