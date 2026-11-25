"""Excel point-list import / export tests (no network needed)."""

import io
from pathlib import Path

import pytest
from openpyxl import load_workbook

from sme_bacnet_sim.config import load_file, parse_text
from sme_bacnet_sim.engine import Engine
from sme_bacnet_sim.templates import expand_device
from sme_bacnet_sim.web import create_app
from sme_bacnet_sim.xlsx import XlsxImportError, blank_template, export_xlsx, import_xlsx

DEMO = Path(__file__).resolve().parent.parent / "configs" / "demo-building.yaml"

SMALL = """
network: {ip: 127.0.0.1/8, port: 47900}
devices:
  - device_id: 10
    name: Room
    objects:
      - {type: notification-class, instance: 1, name: NC1, recipients: [{device: 99}]}
      - {type: analog-input, instance: 1, name: Temp, units: degrees-celsius, value: 22.5, cov_increment: 0.5,
         behavior: {type: sine, min: 20, max: 26, period: 600},
         alarm: {notification_class: NC1, high_limit: 28, low_limit: 16, deadband: 1, time_delay: 5,
                 notify_type: event}}
      - {type: binary-value, instance: 1, name: Fan, active_text: "ON", inactive_text: "OFF", commandable: true,
         alarm: {notification_class: 1, alarm_value: active}}
      - {type: multi-state-value, instance: 1, name: Mode, states: [Auto, Manual, "Off"], value: 2,
         alarm: {notification_class: NC1, alarm_values: [3]}}
      - {type: multi-state-input, instance: 2, name: Mode2, states: [Auto, Manual, "Off"], value: 1}
      - {type: trend-log, instance: 1, name: Temp_Log, log_object: Temp, log_interval: 30}
      - {type: schedule, instance: 1, name: Sched, targets: [Fan], weekly: {weekdays: [{time: "08:00", value: 1}]}}
"""


def _wb_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(*cells, **named):
    """A Points row by column name (device_id, type, instance, name positional)."""
    header = [c.value for c in load_workbook(io.BytesIO(blank_template()))["Points"][1]]
    row = [None] * len(header)
    row[:len(cells)] = cells
    for k, v in named.items():
        row[header.index(k)] = v
    return row


def test_blank_template():
    wb = load_workbook(io.BytesIO(blank_template()))
    assert wb.sheetnames == ["Devices", "Points", "StateTexts", "Network"]
    pts = wb["Points"]
    header = [c.value for c in pts[1]]
    assert header[:4] == ["device_id", "type", "instance", "name"] and "alarm_high_limit" in header
    assert str(pts["A2"].value).startswith("#")  # description row
    assert pts.max_row == 2
    cfg, warnings = import_xlsx(blank_template())  # an empty template imports as an empty config
    assert cfg.devices == [] and warnings == []


@pytest.mark.parametrize("cfg", [load_file(DEMO), parse_text(SMALL)], ids=["demo", "small"])
def test_roundtrip(cfg):
    data, warnings = export_xlsx(cfg)
    assert warnings == []
    back, warnings = import_xlsx(data)
    assert warnings == []
    assert back.model_dump(exclude_none=True) == cfg.model_dump(exclude_none=True)
    for a, b in zip(cfg.devices, back.devices):
        assert [o.model_dump(exclude_none=True) for o in expand_device(a)] == \
               [o.model_dump(exclude_none=True) for o in expand_device(b)]


def test_export_layout_and_extra():
    wb = load_workbook(io.BytesIO(export_xlsx(parse_text(SMALL))[0]))
    pts = wb["Points"]
    header = [c.value for c in pts[1]]
    rows = {r[header.index("name")]: dict(zip(header, r)) for r in pts.iter_rows(min_row=3, values_only=True)}
    temp = rows["Temp"]
    assert (temp["alarm_class"], temp["alarm_high_limit"], temp["alarm_low_limit"]) == ("NC1", 28, 16)
    assert "notify_type: event" in temp["extra"] and temp["behavior"].startswith("{type: sine")
    assert rows["Fan"]["alarm_values"] == "active" and rows["Mode"]["alarm_values"] == "3"
    assert rows["Mode"]["state_texts"] == rows["Mode2"]["state_texts"] == 1  # same texts share a ref
    assert "weekly" in rows["Sched"]["extra"] and "recipients" in rows["NC1"]["extra"]
    st = list(wb["StateTexts"].iter_rows(min_row=3, values_only=True))
    assert st[0][:4] == (1, "Auto", "Manual", "Off")
    net = {k: v for k, v in wb["Network"].iter_rows(min_row=3, values_only=True)}
    assert net["network.port"] == 47900 and net["simulation.time_scale"] == 1


def test_export_warns_on_cell_limit():
    cfg = parse_text(SMALL)
    cfg.devices[0].description = "x" * 40000
    _, warnings = export_xlsx(cfg)
    assert len(warnings) == 1 and "device 10: description" in warnings[0]


def _handwritten():
    wb = load_workbook(io.BytesIO(blank_template()))
    wb["Devices"].append([1, "AHU-1"])
    wb["Devices"].append([2, "Lights", None, "lighting", "{zones: 2}"])
    wb["Points"].append(_row(1, "analog-input", 1, "SAT", description="supply air", units=62, value=21.5))
    wb["Points"].append(_row(1, "multi-state-value", None, "Mode", value=1, commandable="yes", state_texts=7))
    wb["Points"].append(_row(1, "binary-output", 1, "FanCmd"))
    wb["StateTexts"].append([7, "Auto", "Manual"])
    return wb


def test_import_handwritten():
    cfg, warnings = import_xlsx(_wb_bytes(_handwritten()), base=parse_text(SMALL))
    assert warnings == []
    assert cfg.network.port == 47900  # no Network rows: base settings kept
    ahu, lights = cfg.devices
    sat, mode, fan = ahu.objects
    assert (sat.units, sat.value, sat.description) == ("degrees-celsius", 21.5, "supply air")  # unit code 62
    assert (mode.states, mode.value, mode.commandable, mode.instance) == (["Auto", "Manual"], 1, True, None)
    assert lights.template == "lighting" and lights.params == {"zones": 2} and lights.objects == []
    assert len(expand_device(lights)) > 0


def test_import_errors_name_sheet_row_column():
    wb = _handwritten()
    wb["Points"].append(_row(1, "analog-input", "abc", "Bad"))  # row 6
    wb["Points"].append(_row(3, "analog-input", 1, "Orphan"))  # row 7: unknown device
    wb["Points"].append(_row(1, "no-such-type", 1, "X"))  # row 8
    wb["Points"].append(_row(1, "binary-output", 2, "FanCmd"))  # row 9: duplicate name
    wb["Points"].append(_row(1, "multi-state-value", 2, "M2", state_texts=99))  # row 10
    wb["Points"].append(_row(1, "analog-input", 5, "B", behavior="{type: [oops"))  # row 11: bad YAML
    wb["Devices"].append(["x", "D"])  # row 5
    wb["Network"].append(["network.port", "high"])  # row 3
    with pytest.raises(XlsxImportError) as ei:
        import_xlsx(_wb_bytes(wb))
    errs = ei.value.errors
    expect = ["Devices row 5, column 'device_id'", "Points row 6, column 'instance'",
              "Points row 7, column 'device_id'", "Points row 8, column 'type'", "Points row 9, column 'name'",
              "Points row 10, column 'state_texts'", "Points row 11, column 'behavior'",
              "Network row 3, column 'value'"]
    for e in expect:
        assert any(x.startswith(e) for x in errs), (e, errs)
    assert len(errs) == len(expect), errs


def test_import_pydantic_error_maps_column_and_unknown_column_warns():
    wb = load_workbook(io.BytesIO(blank_template()))
    wb["Devices"].append([1, "D"])
    wb["Points"].append(_row(1, "analog-value", 1, "A", extra="{bogus: 1}"))
    with pytest.raises(XlsxImportError) as ei:
        import_xlsx(_wb_bytes(wb))
    assert ei.value.errors[0].startswith("Points row 3, column 'extra': bogus")
    wb = load_workbook(io.BytesIO(blank_template()))
    wb["Devices"].cell(1, 13, "comment")
    wb["Devices"].append([1, "D"])
    cfg, warnings = import_xlsx(_wb_bytes(wb))
    assert len(cfg.devices) == 1 and warnings == ["Devices: unknown column 'comment' ignored"]


def test_web_endpoints():
    try:
        from fastapi.testclient import TestClient
    except (ImportError, RuntimeError):  # TestClient needs httpx / httpx2 (not a runtime dependency)
        pytest.skip("httpx is not installed")
    engine = Engine(parse_text(SMALL))
    applied = []

    async def fake_reload(cfg, text=None):
        applied.append(cfg)
        engine.config = cfg

    engine.reload = fake_reload
    client = TestClient(create_app(engine))  # no lifespan: the BACnet stack is not started
    r = client.get("/api/config/xlsx-template")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    assert load_workbook(io.BytesIO(r.content)).sheetnames[0] == "Devices"
    r = client.get("/api/config/xlsx")
    assert r.status_code == 200 and "points.xlsx" in r.headers["content-disposition"]
    exported = r.content
    wb = _handwritten()
    wb["Points"].append(_row(1, "analog-input", 2, "U", units=99999))  # row 6: unknown unit code
    r = client.post("/api/config/import", files={"file": ("p.xlsx", _wb_bytes(wb))})
    assert r.status_code == 400 and "Points row 6, column 'units'" in "; ".join(r.json()["detail"]["errors"])
    wb["Devices"].cell(1, 13, "note")  # unknown column -> warning in the response
    wb["Points"].delete_rows(6)
    r = client.post("/api/config/import", files={"file": ("p.xlsx", _wb_bytes(wb))})
    assert r.status_code == 200 and r.json()["warnings"] == ["Devices: unknown column 'note' ignored"]
    assert "Excel workbook imported" in engine.events[-1]["message"]  # the warnings are in the response
    r = client.post("/api/config/import", files={"file": ("back.xlsx", exported)})
    assert r.status_code == 200
    assert applied[-1].model_dump(exclude_none=True) == parse_text(SMALL).model_dump(exclude_none=True)


# ---- 0.4.0 behaviour guards for the XlsxSchema port (sme-sim-common migration)

def test_state_texts_beyond_template_width_round_trip():
    texts = [f"S{i}" for i in range(1, 13)]  # 12 states > the 8 text_N columns of the blank template
    cfg = parse_text("devices:\n  - device_id: 1\n    name: D\n    objects:\n"
                     f"      - {{type: multi-state-value, instance: 1, name: M, states: [{', '.join(texts)}]}}\n")
    data, warnings = export_xlsx(cfg)
    assert warnings == []
    header = [c.value for c in load_workbook(io.BytesIO(data))["StateTexts"][1]]
    assert header == ["ref", *(f"text_{i}" for i in range(1, 13))]
    back, _ = import_xlsx(data)
    assert back.devices[0].objects[0].states == texts


def test_network_blank_value_skipped_but_key_checked():
    wb = load_workbook(io.BytesIO(blank_template()))
    wb["Devices"].append([1, "D"])
    wb["Network"].append(["network.port", 47901])
    wb["Network"].append(["network.ip", None])  # blank value: the row is skipped
    cfg, warnings = import_xlsx(_wb_bytes(wb), base=parse_text(SMALL))
    # 0.4.0: with Network rows the section is rebuilt from them alone, so a skipped key takes the model default
    assert warnings == [] and cfg.network.port == 47901 and cfg.network.ip == "auto"
    wb["Network"].append(["bogus.key", None])  # row 5: the key is checked before the blank value is skipped
    with pytest.raises(XlsxImportError) as ei:
        import_xlsx(_wb_bytes(wb))
    assert len(ei.value.errors) == 1 and ei.value.errors[0].startswith("Network row 5, column 'key': unknown key")
