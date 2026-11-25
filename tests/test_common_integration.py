"""sme-sim-common integration: engine protocol, i18n namespaces, standard routes."""

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
