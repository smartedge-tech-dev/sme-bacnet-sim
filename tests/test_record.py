"""``sme-bacnet-sim record``: poll / Trend Log recording against the simulator itself, replay round trip.

Uses BACnet port 47920 (simulator) / 47921-47925 (record clients) and virtual network 220.
"""

import asyncio
import csv

import pytest

from sme_bacnet_sim import record
from sme_bacnet_sim.behaviors import ReplayTable
from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine, RouterApplication, SimApplication, detect_ip

CONFIG = """
network: {ip: auto, port: 47920, virtual_network: 220, router: {device_id: 4194120}}
simulation: {tick_seconds: 0.2}
devices:
  - device_id: 3201
    name: Real-AHU
    objects:
      - {type: analog-input, instance: 1, name: SupplyTemp, units: degrees-celsius, value: 18.5}
      - {type: analog-value, instance: 2, name: SupplyTempSP, units: degrees-celsius, value: 16.25}
      - {type: binary-output, instance: 1, name: Fan, value: 1}
      - {type: multi-state-value, instance: 1, name: Mode, states: ["Off", Cool, Heat], value: 2}
      - {type: accumulator, instance: 1, name: Energy, units: kilowatt-hours, value: 42}
      - {type: trend-log, instance: 1, name: SupplyTemp-Log, log_object: SupplyTemp, log_interval: 1,
         buffer_size: 100}
      - {type: trend-log, instance: 2, name: Fan-Log, log_object: Fan, log_interval: 1, buffer_size: 100}
      - {type: calendar, instance: 1, name: Holidays, dates: [2026-01-01]}
  - device_id: 3202
    name: Real-Meter
    objects:
      - {type: analog-input, instance: 1, name: Power, units: kilowatts, value: 3.2}
      - {type: analog-input, instance: 2, name: SupplyTemp, units: degrees-celsius, value: 20}
"""

ALLOWED = {"WhoIsRequest", "ReadPropertyRequest", "ReadPropertyMultipleRequest"}


def _args(tmp_path, port, out, *extra):
    ip = detect_ip()
    return record.build_parser().parse_args(
        ["--address", f"{ip.split('/')[0]}:47920", "--network", "220", "--who-is", "3200-3299",
         "--ip", ip, "--port", str(port), "--rate", "200", "--timeout", "2", "-o", str(tmp_path / out), *extra])


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


@pytest.fixture
def spy(monkeypatch):
    received = []
    for cls in (SimApplication, RouterApplication):
        orig = cls.indication

        async def wrapped(self, apdu, _orig=orig):
            received.append(type(apdu).__name__)
            await _orig(self, apdu)

        monkeypatch.setattr(cls, "indication", wrapped)
    return received


def test_record_poll_resume_and_replay(tmp_path, spy):
    cfg_path = tmp_path / "cloned.yaml"
    cfg_path.write_text(CONFIG, encoding="utf-8")
    out = tmp_path / "rec.csv"

    async def go():
        engine = Engine(parse_text(CONFIG))
        await engine.start()
        try:
            r1 = await record.run_record(_args(tmp_path, 47921, "rec.csv", "-c", str(cfg_path), "--interval", "1",
                                               "--count", "2"), progress=lambda m: None)
            with pytest.raises(ValueError, match="--resume"):
                await record.run_record(_args(tmp_path, 47922, "rec.csv", "-c", str(cfg_path), "--count", "1"),
                                        progress=lambda m: None)
            r2 = await record.run_record(_args(tmp_path, 47922, "rec.csv", "-c", str(cfg_path), "--count", "1",
                                               "--resume", "--no-rpm"), progress=lambda m: None)
            with pytest.raises(ValueError, match="same columns"):
                await record.run_record(_args(tmp_path, 47923, "rec.csv", "-c", str(cfg_path), "--count", "1",
                                               "--resume", "--points", "Fan"), progress=lambda m: None)
        finally:
            await engine.stop()
        return r1, r2

    r1, r2 = asyncio.run(go())
    rows = _rows(out)
    # the name used on both devices gets the device prefix; non-value objects (trend-log, calendar) are skipped
    assert rows[0] == ["time", "3201/SupplyTemp", "SupplyTempSP", "Fan", "Mode", "Energy", "Power", "3202/SupplyTemp"]
    assert len(rows) == 4 and r1["rows"] == 2 and r2["rows"] == 1
    for row in rows[1:]:
        assert row[1:] == ["18.5", "16.25", "active", "2", "42", "3.2", "20"]
    assert set(r1["services"]) == {"who-is", "read-property-multiple"}
    assert set(r2["services"]) == {"who-is", "read-property"}
    assert spy and set(spy) <= ALLOWED, set(spy)

    # the recording is a valid replay CSV, and a config replaying it is accepted by the simulator
    t = ReplayTable(out)
    assert t.column("Fan") == ["active"] * 3 and t.column("SupplyTempSP") == [16.25] * 3
    assert t.times[1] >= 1
    cfg = parse_text(f"""
devices:
  - device_id: 9001
    name: Replayed
    objects:
      - {{type: ai, name: SupplyTemp, behavior: {{type: replay, file: "{out.as_posix()}", column: 3201/SupplyTemp}}}}
      - {{type: bv, name: Fan, behavior: {{type: replay, file: "{out.as_posix()}", column: Fan}}}}
      - {{type: msv, name: Mode, states: [a, b, c], behavior: {{type: replay, file: "{out.as_posix()}",
          column: Mode}}}}
""")

    async def prepare():  # bacpypes3 objects need a running loop
        Engine(cfg)._prepare(cfg)

    asyncio.run(prepare())


def test_record_refs_and_trend_log(tmp_path, spy):
    async def go():
        engine = Engine(parse_text(CONFIG))
        await engine.start()
        try:
            await asyncio.sleep(3.5)  # let the 1 s trend logs collect a few records
            r1 = await record.run_record(_args(tmp_path, 47924, "refs.csv", "--devices", "3202",
                                               "--points", "ai:1=Power,analog-input:2", "--count", "1"),
                                         progress=lambda m: None)
            r2 = await record.run_record(_args(tmp_path, 47925, "tl.csv", "--devices", "3201", "--trend-log",
                                               "--points", "trend-log:1=SupplyTemp,tl:2=Fan"),
                                         progress=lambda m: None)
        finally:
            await engine.stop()
        return r1, r2

    r1, r2 = asyncio.run(go())
    rows = _rows(tmp_path / "refs.csv")
    assert rows[0] == ["time", "Power", "analog-input:2"] and rows[1][1:] == ["3.2", "20"]
    rows = _rows(tmp_path / "tl.csv")
    assert rows[0] == ["time", "SupplyTemp", "Fan"] and r2["rows"] == len(rows) - 1 >= 2
    assert all(r[1] == "18.5" and r[2] == "active" for r in rows[1:]), rows
    assert "read-range" in r2["services"]
    assert "ReadRangeRequest" in spy and set(spy) <= ALLOWED | {"ReadRangeRequest"}
    t = ReplayTable(tmp_path / "tl.csv")
    assert t.column("SupplyTemp")[0] == 18.5


def test_parsers():
    assert record.parse_duration("90") == 90 and record.parse_duration("15m") == 900
    assert record.parse_duration("2h") == 7200 and record.parse_duration("1d") == 86400
    with pytest.raises(ValueError):
        record.parse_duration("soon")
    p = record.parse_ref("3201/ai:7=OAT")
    assert (p.device, str(p.oid), p.column) == (3201, "analog-input,7", "OAT")
    assert record.parse_ref("bv:2").column == "binary-value:2"
    with pytest.raises(ValueError, match="TYPE:INSTANCE"):
        record.parse_ref("OAT")
    assert record.fmt_value(21.299999237060547, "analog-input") == "21.3"
    assert record.fmt_value(1, "binary-input") == "active"
    assert record.fmt_value(3, "multi-state-value") == "3"


def test_cli_errors(tmp_path, capsys):
    from sme_bacnet_sim.__main__ import main
    assert main(["record", "--address", "127.0.0.1", "-o", str(tmp_path / "x.csv")]) == 2
    assert "select points" in capsys.readouterr().err
    assert main(["record", "--address", "127.0.0.1", "--points", "calendar:1", "-o", str(tmp_path / "x.csv")]) == 2
    assert "no recordable present-value" in capsys.readouterr().err
    assert main(["record", "--address", "127.0.0.1", "--points", "ai:1", "--interval", "0.5",
                 "-o", str(tmp_path / "x.csv")]) == 2
    assert "at least 1 second" in capsys.readouterr().err
