"""EDE (B.I.G.-EU Engineering Data Exchange) import / export tests (no network needed)."""

import io
import zipfile
from pathlib import Path

from sme_bacnet_sim.config import load_file, parse_text
from sme_bacnet_sim.ede import (MAIN_FILE, STATE_TEXT_FILE, export_ede, export_ede_zip, import_ede, import_ede_files,
                        is_state_text_file)
from sme_bacnet_sim.templates import expand_device

DEMO = Path(__file__).resolve().parent.parent / "configs" / "demo-building.yaml"


def _key(o):
    return (o.type, o.instance, o.name, o.units, tuple(o.states or ()), o.active_text, o.inactive_text)


def test_roundtrip_demo():
    cfg = load_file(DEMO)
    files = export_ede(cfg)
    assert set(files) == {MAIN_FILE, STATE_TEXT_FILE}
    main = files[MAIN_FILE]
    assert main.startswith("#Engineering-Data-Exchange - B.I.G.-EU")
    assert "VERSION_OF_LAYOUT;2.3" in main
    assert "# keyname;device obj.-instance;object-name;object-type;" in main
    assert is_state_text_file(files[STATE_TEXT_FILE]) and not is_state_text_file(main)

    back, warnings = import_ede(main, files[STATE_TEXT_FILE], base=cfg)
    # schedules, calendars, loops and event enrollments cannot round-trip via EDE; notification classes lose their recipients
    special = ("schedule", "calendar", "notification-class", "loop", "file ", "event-enrollment")
    assert [w for w in warnings if not any(x in w for x in special)] == []
    assert back.network == cfg.network and back.simulation == cfg.simulation
    assert [(d.device_id, d.name) for d in back.devices] == [(d.device_id, d.name) for d in cfg.devices]
    for orig, imp in zip(cfg.devices, back.devices):
        exp_objs = [o for o in expand_device(orig) if o.type not in ("schedule", "calendar", "loop", "event-enrollment")]
        assert len(imp.objects) == len(exp_objs)
        assert sorted(map(_key, imp.objects), key=str) == sorted(map(_key, exp_objs), key=str)
        # imported devices are flat (no template); re-expansion keeps them unchanged
        assert sorted(map(_key, expand_device(imp)), key=str) == sorted(map(_key, imp.objects), key=str)
        # trend logs come back with their settings (vendor-specific-address column)
        tl = lambda objs: sorted((o.name, o.instance, o.log_object, o.log_property, o.log_interval, o.logging_type,
                                  o.client_cov_increment, o.buffer_size, o.enabled)
                                 for o in objs if o.type == "trend-log")
        assert tl(imp.objects) == tl(exp_objs)
        # analog hi-limit / low-limit map to the alarm limits
        lim = lambda objs: sorted((o.name, o.alarm.high_limit, o.alarm.low_limit)
                                  for o in objs if o.alarm is not None and o.type.startswith("analog"))
        assert lim(imp.objects) == lim(exp_objs)
    assert sum(o.type == "trend-log" for d in back.devices for o in d.objects) >= 3

    pump = next(d for d in back.devices if d.device_id == 1100)
    mode = next(o for o in pump.objects if o.name == "OperationMode")
    assert mode.states == ["Auto", "Manual", "Maintenance"] and mode.value == 1 and mode.commandable
    cmd = next(o for o in pump.objects if o.name == "PumpCmd")
    assert (cmd.active_text, cmd.inactive_text) == ("ON", "OFF")
    speed = next(o for o in pump.objects if o.name == "SpeedCmd")
    assert (speed.units, speed.min, speed.max, speed.value) == ("percent", 0.0, 100.0, 80.0)

    # zip export / import through the upload helper
    back2, _ = import_ede_files({"x.zip": export_ede_zip(cfg)}, base=cfg)
    assert back2 == back


SAMPLE = """﻿#Engineering-Data-Exchange - B.I.G.-EU
PROJECT_NAME,Sample
VERSION_OF_LAYOUT,2.3

# a comment line
#keyname,device obj.-instance,object-name,object-type,object-instance,description,present-value-default,min-present-value,max-present-value,settable,supports COV,hi-limit,low-limit,state-text-reference,unit-code
dev,3001,Boiler-Ctl,8,3001,"Boiler, basement",,,,,,,,,
t1,3001,FlowTemp,0,1,Flow temperature,55.5,0,120,N,Y,,,,62
sp,3001,FlowSetpoint,2,1,,60,,,Y,Y,,,,62
pump,3001,Pump,4,1,,1,,,Y,,,,1,
mode,3001,Mode,19,2,,2,,3,Y,,,,2,
cal,3001,Schedule,17,1,,,,,,,,,,
x,3002,Orphan,3,7,,,,,N,,,,,
"""

STATES = """#State-Text-File - B.I.G.-EU
PROJECT_NAME;Sample
#State-Text-Reference;Text 1;Text 2;Text 3
1;Off;On;
2;Winter;Summer;Off
"""


def test_import_handwritten_sample():
    cfg, warnings = import_ede_files({"main.csv": SAMPLE.encode("utf-8"), "st.csv": STATES.encode("cp1252")})
    assert len(warnings) == 1 and "schedule" in warnings[0]
    d1, d2 = cfg.devices
    assert (d1.device_id, d1.name, d1.description) == (3001, "Boiler-Ctl", "Boiler, basement")
    assert (d2.device_id, d2.name) == (3002, "Device-3002")
    objs = {o.name: o for o in d1.objects}
    assert objs["FlowTemp"].type == "analog-input" and objs["FlowTemp"].units == "degrees-celsius"
    assert objs["FlowTemp"].value == 55.5 and objs["FlowTemp"].max == 120
    assert objs["FlowSetpoint"].type == "analog-value" and objs["FlowSetpoint"].commandable
    assert objs["Pump"].type == "binary-output" and objs["Pump"].active_text == "On" and objs["Pump"].value == 1
    assert objs["Pump"].commandable is None  # outputs are commandable anyway
    assert objs["Mode"].instance == 2 and objs["Mode"].states == ["Winter", "Summer", "Off"]
    assert d2.objects[0].type == "binary-input"


def test_trendlog_cov_and_limits_roundtrip():
    cfg = parse_text("""
devices:
  - device_id: 7
    name: D7
    objects:
      - {type: nc, instance: 3, name: Alarms}
      - {type: av, name: Temp, value: 20, alarm: {notification_class: Alarms, high_limit: 30.5, low_limit: 10}}
      - {type: tl, name: Temp_Log, log_object: Temp, logging_type: cov, client_cov_increment: 0.5, buffer_size: 50,
         enabled: false}
""")
    f = export_ede(cfg)
    row = next(r for r in f[MAIN_FILE].splitlines() if r.startswith("D7_Temp;"))
    assert row.split(";")[11:13] == ["30.5", "10"]
    back, _ = import_ede(f[MAIN_FILE], f[STATE_TEXT_FILE])
    objs = {o.name: o for o in back.devices[0].objects}
    assert objs["Temp"].alarm.model_dump(exclude_unset=True) == {
        "notification_class": "Alarms", "high_limit": 30.5, "low_limit": 10.0}
    t = objs["Temp_Log"]
    assert (t.log_object, t.logging_type, t.client_cov_increment, t.buffer_size, t.enabled) == \
        ("Temp", "cov", 0.5, 50, False)


def test_import_trendlog_and_limits_without_extras():
    # a foreign EDE file: no vendor-specific-address, no notification class
    main = ("# keyname;device obj.-instance;object-name;object-type;object-instance;hi-limit;low-limit\n"
            "a;9;Flow;0;1;80;\n"
            "b;9;Flow_Log;20;1;;\n"
            "c;9;Other_Log;20;2;;\n")
    cfg, warnings = import_ede(main)
    objs = {o.name: o for o in cfg.devices[0].objects}
    assert objs["Flow"].alarm.high_limit == 80 and objs["Flow"].alarm.low_limit is None
    assert objs["NC-1"].type == "notification-class" and objs["Flow"].alarm.notification_class == "NC-1"
    assert objs["Flow_Log"].log_object == "Flow" and objs["Other_Log"].log_object == "Flow"
    assert objs["Flow_Log"].logging_type is None  # polled, default interval
    assert len(warnings) == 3


def test_import_multistate_without_texts_gets_placeholders():
    main = "# keyname;device obj.-instance;object-name;object-type;object-instance;max-present-value\nk;5;M;14;1;4\n"
    cfg, warnings = import_ede(main)
    assert cfg.devices[0].objects[0].states == ["State 1", "State 2", "State 3", "State 4"]
    assert len(warnings) == 1


def test_export_zip_contents():
    cfg = load_file(DEMO)
    with zipfile.ZipFile(io.BytesIO(export_ede_zip(cfg))) as z:
        assert sorted(z.namelist()) == sorted([MAIN_FILE, STATE_TEXT_FILE])
