"""Clone: read another simulator instance (the "real device") and compare the generated config.

Uses BACnet port 47910 (simulator) / 47911 and 47912 (clone clients) and virtual network 210.
"""

import asyncio
import json

import pytest
import yaml
from bacpypes3.apdu import WritePropertyRequest
from bacpypes3.pdu import Address

from sme_bacnet_sim import clone
from sme_bacnet_sim.config import SimConfig, load_file, parse_text
from sme_bacnet_sim.engine import Engine, RouterApplication, SimApplication, detect_ip

CONFIG = """
network: {ip: auto, port: 47910, virtual_network: 210, router: {device_id: 4194110}}
simulation: {tick_seconds: 0.5}
devices:
  - device_id: 3101
    name: Real-AHU
    description: AHU on roof
    location: Roof
    model_name: AHU-X
    objects:
      - {type: notification-class, instance: 5, name: NC-Alarms, priority: [10, 20, 30],
         ack_required: [true, false, false], recipients: [{device: 3999, process_id: 7, confirmed: true}]}
      - {type: analog-input, instance: 1, name: SupplyTemp, units: degrees-celsius, value: 18.5, cov_increment: 0.5,
         description: supply air,
         alarm: {notification_class: NC-Alarms, high_limit: 30, low_limit: 5, deadband: 1, time_delay: 10}}
      - {type: analog-value, instance: 2, name: SupplyTempSP, units: degrees-celsius, value: 16, commandable: true,
         min: 10, max: 30}
      - {type: analog-output, instance: 3, name: CoolValve, units: percent, value: 0}
      - {type: binary-output, instance: 1, name: Fan, active_text: Run, inactive_text: Stop}
      - {type: binary-input, instance: 2, name: FanFault, alarm: {notification_class: 5, alarm_value: active}}
      - {type: multi-state-value, instance: 1, name: Mode, states: ["Off", Cool, Heat], value: 2, commandable: true,
         alarm: {notification_class: NC-Alarms, alarm_values: [3]}}
      - {type: accumulator, instance: 1, name: Energy, units: kilowatt-hours, value: 42, max: 99999, scale: 0.5}
      - {type: loop, instance: 1, name: SupplyLoop, controlled_object: SupplyTemp, manipulated_object: CoolValve,
         setpoint_object: SupplyTempSP, proportional_constant: 8, integral_constant: 0.2, min: 0, max: 100}
      - {type: trend-log, instance: 1, name: SupplyTemp-Log, log_object: SupplyTemp, log_interval: 30,
         buffer_size: 500}
      - {type: calendar, instance: 1, name: Holidays, dates: [2026-01-01, {from: 2026-12-29, to: 2026-12-31}]}
      - type: schedule
        instance: 1
        name: FanSchedule
        weekly: {weekdays: [{time: "07:00", value: 1}, {time: "19:00", value: 0}], weekend: []}
        exceptions: [{calendar: Holidays, priority: 10, times: []}]
        default: 0
        targets: [Fan]
      - {type: program, instance: 1, name: Seq, instance_of: Seq-v2, program_state: running}
      - {type: file, instance: 1, name: Notes, file_type: text/plain, access: record, content: hello}
      - {type: event-enrollment, instance: 1, name: SP-Watch, monitored_object: SupplyTempSP,
         event_type: out-of-range, event_parameters: {low_limit: 12, high_limit: 28, deadband: 0.5},
         notification_class: NC-Alarms, time_delay: 5}
      - {type: life-safety-point, instance: 1, name: Smoke-1, value: quiet}
      - {type: life-safety-zone, instance: 1, name: Zone-1, zone_members: [Smoke-1]}
  - device_id: 3102
    name: Real-Meter
    objects:
      - {type: analog-input, instance: 1, name: Power, units: kilowatts, value: 3.2}
"""

ALLOWED = {"WhoIsRequest", "ReadPropertyRequest", "ReadPropertyMultipleRequest"}


def _args(tmp_path, port, *extra):
    ip = detect_ip()
    return clone.build_parser().parse_args(
        ["--address", f"{ip.split('/')[0]}:47910", "--network", "210", "--who-is", "3100-3199",
         "--ip", ip, "--port", str(port), "--rate", "200", "--timeout", "2", "-o", str(tmp_path / f"c{port}.yaml"),
         *extra])


def test_clone_roundtrip(tmp_path, monkeypatch):
    received = []
    for cls in (SimApplication, RouterApplication):
        orig = cls.indication

        async def spy(self, apdu, _orig=orig):
            received.append(type(apdu).__name__)
            await _orig(self, apdu)

        monkeypatch.setattr(cls, "indication", spy)

    async def go():
        engine = Engine(parse_text(CONFIG))
        await engine.start()
        try:
            r1 = await clone.run_clone(_args(tmp_path, 47911), progress=lambda m: None)
            r2 = await clone.run_clone(_args(tmp_path, 47912, "--no-rpm", "--devices", "3101"),
                                       progress=lambda m: None)
            a3 = _args(tmp_path, 47913, "--resume")
            a3.output = str(tmp_path / "c47911.yaml")
            r3 = await clone.run_clone(a3, progress=lambda m: None)  # everything already there: Who-Is only
            assert r3["services"] == ["who-is"] and [d["device_id"] for d in r3["devices"]] == [3101, 3102]
            cloned = load_file(tmp_path / "c47911.yaml")
            Engine(cloned)._prepare(cloned)  # the simulator accepts the generated config
        finally:
            await engine.stop()
        return r1, r2

    r1, r2 = asyncio.run(go())
    # read-only: the "real devices" only ever received these services, and the client only sent them
    assert received and set(received) <= ALLOWED, set(received)
    assert set(r1["services"]) == {"who-is", "read-property", "read-property-multiple"}
    assert set(r2["services"]) == {"who-is", "read-property"}

    out = tmp_path / "c47911.yaml"
    cloned = load_file(out)  # valid SimConfig with default network settings
    assert cloned.network == SimConfig().network
    orig = parse_text(CONFIG)
    assert [d.device_id for d in cloned.devices] == [3101, 3102]
    for od, cd in zip(orig.devices, cloned.devices):
        assert (cd.name, cd.description, cd.location, cd.model_name) == (od.name, od.description, od.location,
                                                                          od.model_name or "custom")
        assert sorted((o.type, o.instance, o.name) for o in cd.objects) == sorted((o.type, o.instance, o.name)
                                                                              for o in od.objects)
    c = {o.name: o for o in cloned.devices[0].objects}
    o = {o.name: o for o in orig.devices[0].objects}
    assert c["SupplyTemp"].units == "degrees-celsius" and c["SupplyTemp"].cov_increment == 0.5
    assert c["SupplyTemp"].value == 18.5 and c["SupplyTemp"].description == "supply air"
    a = c["SupplyTemp"].alarm
    assert (a.notification_class, a.high_limit, a.low_limit, a.deadband, a.time_delay) == ("NC-Alarms", 30, 5, 1, 10)
    assert c["SupplyTempSP"].commandable and c["SupplyTempSP"].value == 16 and (c["SupplyTempSP"].min,
                                                                                 c["SupplyTempSP"].max) == (10, 30)
    assert (c["Fan"].active_text, c["Fan"].inactive_text) == ("Run", "Stop")
    assert c["FanFault"].alarm.alarm_value == "active"
    assert c["Mode"].states == ["Off", "Cool", "Heat"] and c["Mode"].value == 2 and c["Mode"].alarm.alarm_values == [3]
    nc = c["NC-Alarms"]
    assert nc.priority == [10, 20, 30] and nc.ack_required == [True, False, False]
    assert [(r.device, r.process_id, r.confirmed) for r in nc.recipients] == [(3999, 7, True)]
    assert (c["Energy"].value, c["Energy"].max, c["Energy"].scale) == (42, 99999, 0.5)
    lp = c["SupplyLoop"]
    assert (lp.controlled_object, lp.manipulated_object, lp.setpoint_object, lp.proportional_constant,
            lp.integral_constant, lp.min, lp.max) == ("SupplyTemp", "CoolValve", "SupplyTempSP", 8, 0.2, 0, 100)
    tl = c["SupplyTemp-Log"]
    assert (tl.log_object, tl.log_interval, tl.buffer_size) == ("SupplyTemp", 30, 500)
    assert c["Holidays"].dates == ["2026-01-01", {"from": "2026-12-29", "to": "2026-12-31"}]
    sc = c["FanSchedule"]
    assert sc.weekly == {"weekdays": [{"time": "07:00", "value": 1}, {"time": "19:00", "value": 0}], "weekend": []}
    assert sc.exceptions == [{"calendar": "Holidays", "priority": 10, "times": []}]
    assert sc.targets == ["Fan"] and sc.default == 0
    assert (c["Seq"].program_state, c["Seq"].instance_of) == ("running", "Seq-v2")
    assert (c["Notes"].file_type, c["Notes"].access, c["Notes"].content) == ("text/plain", "record", None)
    ee = c["SP-Watch"]
    assert (ee.monitored_object, ee.event_type, ee.notification_class, ee.time_delay) == (
        "SupplyTempSP", "out-of-range", "NC-Alarms", 5)
    assert ee.event_parameters == {"low_limit": 12, "high_limit": 28, "deadband": 0.5}
    assert c["Smoke-1"].value == "quiet" and c["Zone-1"].zone_members == ["Smoke-1"]
    assert any("file content is not cloned" in w for w in r1["warnings"])

    # RP-only run gives the same device
    rp = yaml.safe_load((tmp_path / "c47912.yaml").read_text(encoding="utf-8"))["devices"]
    rpm = yaml.safe_load(out.read_text(encoding="utf-8"))["devices"]
    for d in rp + rpm:  # the loop output moves between the two reads
        for o in d["objects"]:
            if o["type"] == "loop":
                o.pop("value")
    assert rp == rpm[:1]

    lines = [json.loads(x) for x in (tmp_path / "c47911.yaml.log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {x["kind"] for x in lines} >= {"who-is", "i-am", "read-property", "read-property-multiple", "warning"}


def test_read_only_guard():
    app = clone.ReadOnlyApplication.__new__(clone.ReadOnlyApplication)
    with pytest.raises(clone.ReadOnlyViolation):
        app.request(WritePropertyRequest(destination=Address("1.2.3.4")))


def test_cli_needs_target(tmp_path, capsys):
    from sme_bacnet_sim.__main__ import main
    assert main(["clone", "-o", str(tmp_path / "x.yaml")]) == 2
    assert "give a target" in capsys.readouterr().err
    assert clone.parse_range("5-9") == (5, 9) and clone.parse_range("7") == (7, 7)
    with pytest.raises(ValueError):
        clone.parse_range("9-5")


def test_port_in_use():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 47914))
    try:
        with pytest.raises(OSError, match="--port"):
            clone.check_port("127.0.0.1/8", 47914)
    finally:
        s.close()


def test_object_list_file(tmp_path):
    f = tmp_path / "objects.json"
    f.write_text(json.dumps([{"deviceID": 1011, "objectList": [
        {"objectType": "analogInput", "objectInstance": 1, "properties": ["presentValue"]},
        {"objectType": "multiStateValue", "objectInstance": 4}]}]), encoding="utf-8")
    lists = clone.load_object_lists(str(f))
    assert [(str(o[0]), o[1]) for o in lists[1011]] == [("analog-input", 1), ("multi-state-value", 4)]

    class NoObjectList:  # a device whose object-list cannot be read at all
        async def read(self, *a):
            raise asyncio.TimeoutError()

    warnings = []
    cl = clone.Cloner(NoObjectList(), None, None, object_lists=lists)
    got = asyncio.run(cl._object_list(None, None, 1011, warnings.append))
    assert got == lists[1011] and "object-list-file" in warnings[0]
    with pytest.raises(clone.ObjectListError):
        asyncio.run(cl._object_list(None, None, 1012, warnings.append))
