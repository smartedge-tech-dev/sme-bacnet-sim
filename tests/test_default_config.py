"""Default config location: bundled demo config, or ~/.sme-bacnet-sim/config.yaml for the Windows executable."""

import shutil
import sys
from pathlib import Path

import pytest

import sme_bacnet_sim.__main__ as cli

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "configs" / "demo-building.yaml"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: h))
    return h


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Simulate a PyInstaller onefile run: the bundled config lives in the temporary ``sys._MEIPASS``."""
    meipass = tmp_path / "_MEI12345"
    (meipass / "configs").mkdir(parents=True)
    bundled = meipass / "configs" / "demo-building.yaml"
    shutil.copyfile(DEMO, bundled)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(cli, "DEFAULT_CONFIG", bundled)
    return meipass


@pytest.fixture
def started(monkeypatch):
    """Run ``main`` up to the web server and record the config path handed to the engine."""
    seen = {}

    class FakeEngine:
        def __init__(self, cfg, config_path=None, config_text=None):
            seen["config_path"] = config_path
            seen["config_text"] = config_text

    monkeypatch.setattr(cli, "Engine", FakeEngine)
    monkeypatch.setattr(cli, "create_app", lambda engine: engine)
    monkeypatch.setattr(cli, "run_web", lambda app, args, name: None)
    monkeypatch.setattr(cli, "print_banner", lambda: None)
    return seen


def test_not_frozen_uses_bundled_demo(home, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert cli.default_config_path() == DEMO
    assert not (home / ".sme-bacnet-sim").exists()


def test_user_data_dir_matches_package_name(home):
    assert cli.user_data_dir() == home / ".sme-bacnet-sim"


def test_frozen_first_run_copies_demo(home, frozen):
    p = cli.default_config_path()
    assert p == home / ".sme-bacnet-sim" / "config.yaml"
    assert p.read_bytes() == DEMO.read_bytes()
    assert frozen not in p.parents


def test_frozen_keeps_existing_user_config(home, frozen):
    user = home / ".sme-bacnet-sim" / "config.yaml"
    user.parent.mkdir()
    user.write_text("devices: []\n", encoding="utf-8")
    assert cli.default_config_path() == user
    assert user.read_text(encoding="utf-8") == "devices: []\n"


def test_frozen_without_bundled_config(home, frozen, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_CONFIG", frozen / "configs" / "missing.yaml")
    assert cli.default_config_path() is None
    assert not (home / ".sme-bacnet-sim" / "config.yaml").exists()


def test_frozen_main_runs_on_user_config(home, frozen, started):
    assert cli.main([]) == 0
    user = home / ".sme-bacnet-sim" / "config.yaml"
    assert Path(started["config_path"]) == user
    assert started["config_text"] == DEMO.read_text(encoding="utf-8")


def test_frozen_main_with_config_option(home, frozen, started, tmp_path):
    own = tmp_path / "site.yaml"
    shutil.copyfile(DEMO, own)
    assert cli.main(["-c", str(own)]) == 0
    assert started["config_path"] == str(own)
    assert not (home / ".sme-bacnet-sim").exists()


def test_not_frozen_main_runs_on_bundled_demo(home, started, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert cli.main([]) == 0
    assert Path(started["config_path"]) == DEMO
    assert not (home / ".sme-bacnet-sim").exists()
