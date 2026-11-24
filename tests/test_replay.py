"""CSV time-series replay behavior (issue #3)."""

import asyncio
from pathlib import Path

import pytest

from sme_bacnet_sim import behaviors
from sme_bacnet_sim.behaviors import make_behavior
from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine

CSV = """time,oat,fan,mode
00:00:00,10,inactive,1
00:10:00,20,active,2
00:20:00,30,inactive,3
"""


def _config(objects: str) -> str:
    return f"""
network: {{ip: auto, port: 47971, virtual_network: 248, router: {{device_id: 4194171}}}}
simulation: {{tick_seconds: 1, running: false}}
devices:
  - device_id: 2481
    name: Replay-Dev
    objects:
{objects}
"""


def _engine(tmp_path: Path, objects: str, csv_text: str = CSV) -> Engine:
    """Build (= validate) the config; bacpypes3 objects need an event loop, so run inside one."""
    return asyncio.run(_build(tmp_path, objects, csv_text))


async def _build(tmp_path: Path, objects: str, csv_text: str) -> Engine:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "day.csv").write_text(csv_text, encoding="utf-8")
    cfg_path = tmp_path / "sim.yaml"
    cfg_path.write_text(_config(objects), encoding="utf-8")
    eng = Engine(parse_text(cfg_path.read_text(encoding="utf-8")), config_path=str(cfg_path))
    eng.devices = eng._prepare(eng.config)
    return eng


def _pv(eng: Engine, name: str):
    return next(p for p in eng.devices[2481].points if p.cfg.name == name).obj.presentValue


def _point(eng: Engine, name: str):
    return next(p for p in eng.devices[2481].points if p.cfg.name == name)


def _beh(tmp_path: Path, **kw):
    (tmp_path / "day.csv").write_text(CSV, encoding="utf-8")
    spec = {"type": "replay", "file": "day.csv", "column": "oat", **kw}
    return make_behavior(spec, tmp_path, "analog-input")


def test_linear_interpolation(tmp_path):
    b = _beh(tmp_path)
    assert b.step({"t": 1.0}, None, 1.0) == pytest.approx(10 + 1 / 60)  # replay time 0 = before the first tick
    assert b.step({"t": 300.0}, None, 1.0) == pytest.approx(15.0)
    assert b.step({"t": 900.0}, None, 1.0) == pytest.approx(25.0)
    assert b.step({"t": 5000.0}, None, 1.0) == 30.0  # no loop: holds the last value


def test_step_hold(tmp_path):
    b = _beh(tmp_path, interpolate="step")
    b.step({"t": 0.0}, None, 0.0)
    assert b.step({"t": 599.0}, None, 1.0) == 10.0
    assert b.step({"t": 600.0}, None, 1.0) == 20.0


def test_loop_and_offset(tmp_path):
    b = _beh(tmp_path, loop=True, offset="00:05:00")
    assert b.step({"t": 0.0}, None, 0.0) == pytest.approx(15.0)
    assert b.progress() == {"t": "00:05:00", "pct": 25}
    # 1200 s of data: 5 min offset + 20 min elapsed wraps to replay time 5 min
    assert b.step({"t": 1200.0}, None, 1.0) == pytest.approx(15.0)
    b2 = _beh(tmp_path, offset=300)
    assert b2.step({"t": 0.0}, None, 0.0) == pytest.approx(15.0)


def test_iso_timestamps_and_offset(tmp_path):
    (tmp_path / "iso.csv").write_text(
        "timestamp,kw\n2026-01-01T00:00:00,0\n2026-01-01T01:00:00,100\n", encoding="utf-8")
    b = make_behavior({"type": "replay", "file": "iso.csv", "column": "kw",
                       "offset": "2026-01-01T00:30:00"}, tmp_path, "analog-value")
    assert b.step({"t": 0.0}, None, 0.0) == pytest.approx(50.0)
    assert b.step({"t": 900.0}, None, 1.0) == pytest.approx(75.0)


def test_engine_multi_column_and_accelerated_clock(tmp_path):
    asyncio.run(_multi_column(tmp_path))


async def _multi_column(tmp_path):
    eng = await _build(tmp_path, """
      - {type: ai, name: OAT, units: degreesCelsius, behavior: {type: replay, file: data/day.csv, column: oat}}
      - {type: bi, name: Fan, behavior: {type: replay, file: data/day.csv, column: fan}}
      - {type: msv, name: Mode, states: [A, B, C], behavior: {type: replay, file: data/day.csv, column: mode}}
""", CSV)
    # one parsed table shared by all three points
    tables = {id(_point(eng, n).behavior.table) for n in ("OAT", "Fan", "Mode")}
    assert len(tables) == 1
    # tick_seconds 1 x time_scale 60 -> one tick = 60 simulated seconds (see Engine._run)
    for _ in range(15):
        eng.step(1 * 60)
    assert float(_pv(eng, "OAT")) == pytest.approx(25.0)  # replay time 15 min
    assert str(_pv(eng, "Fan")) == "active"  # binary: step-hold of 'active' at 10 min
    assert int(_pv(eng, "Mode")) == 2  # multi-state: step-hold, never interpolated
    st = _point(eng, "OAT").status()
    assert st["replay"] == {"t": "00:15:00", "pct": 75}


def test_missing_column_reported_by_config_validation(tmp_path):
    with pytest.raises(ValueError, match=r"Replay-Dev/OAT: replay: .*no column 'rh' \(columns: oat, fan, mode\)"):
        _engine(tmp_path, "      - {type: ai, name: OAT, behavior: {type: replay, file: data/day.csv, column: rh}}")


@pytest.mark.parametrize("csv_text, msg", [
    ("time,oat\n", "needs a header row and at least one data row"),
    ("time\n00:00:00\n", "needs a timestamp column and at least one value column"),
    ("time,oat\n00:00:00,1\nnoon,2\n", r"line 3: bad timestamp 'noon' \(expected HH:MM:SS or seconds\)"),
    ("time,oat\n00:10:00,1\n00:05:00,2\n", "line 3: timestamp '00:05:00' goes backwards"),
    ("time,oat\n2026-01-01T00:00:00,1\n12:00,2\n", r"line 3: bad timestamp '12:00' \(expected an ISO datetime\)"),
])
def test_bad_csv_errors(tmp_path, csv_text, msg):
    with pytest.raises(ValueError, match=msg):
        _engine(tmp_path, "      - {type: ai, name: OAT, behavior: {type: replay, file: data/day.csv, column: oat}}",
                csv_text)


def test_missing_file_and_bad_params(tmp_path):
    with pytest.raises(ValueError, match="replay: cannot read"):
        make_behavior({"type": "replay", "file": "nope.csv", "column": "x"}, tmp_path)
    with pytest.raises(ValueError, match="interpolate must be"):
        _beh(tmp_path, interpolate="cubic")
    with pytest.raises(ValueError, match="bad offset"):
        _beh(tmp_path, offset="soon")
    with pytest.raises(ValueError, match="missing parameter 'column'"):
        make_behavior({"type": "replay", "file": "day.csv"}, tmp_path)


def test_cache_reparses_changed_file(tmp_path):
    b1 = _beh(tmp_path)
    again = make_behavior({"type": "replay", "file": "day.csv", "column": "fan"}, tmp_path, "binary-input")
    assert again.table is b1.table  # parsed once per path
    (tmp_path / "day.csv").write_text("time,oat\n0,99\n10,99\n", encoding="utf-8")
    b2 = make_behavior({"type": "replay", "file": "day.csv", "column": "oat"}, tmp_path)
    assert b2.table is not b1.table and b2.step({"t": 0.0}, None, 0.0) == 99.0
    assert behaviors.load_table(tmp_path / "day.csv") is b2.table


def test_example_config_builds():
    path = Path(__file__).resolve().parents[1] / "configs" / "replay-example.yaml"

    async def build():
        eng = Engine(parse_text(path.read_text(encoding="utf-8")), config_path=str(path))
        eng.devices = eng._prepare(eng.config)
        eng.step(60.0)
        return {p.cfg.name: p.status() for p in eng.devices[3001].points}

    st = asyncio.run(build())
    assert st["OutdoorTemp"]["replay"]["t"] == "06:01:00" and "error" not in st["OutdoorTemp"]
    assert st["Mode"]["value"] == 1  # night until 08:00


def test_xlsx_round_trip_keeps_replay_spec():
    from sme_bacnet_sim.xlsx import export_xlsx, import_xlsx

    cfg = parse_text(_config(
        '      - {type: ai, name: OAT, behavior: {type: replay, file: data/day.csv, column: oat, '
        'interpolate: step, loop: true, offset: "06:00:00"}}'))
    data, _ = export_xlsx(cfg)
    back, _ = import_xlsx(data)
    assert back.devices[0].objects[0].behavior == {"type": "replay", "file": "data/day.csv", "column": "oat",
                                                    "interpolate": "step", "loop": True, "offset": "06:00:00"}
