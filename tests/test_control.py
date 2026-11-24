"""Accumulator, Pulse Converter and Loop: config, runtime (pulse counting, PID) and BACnet access.

The BACnet part uses port 47960 / client port 47961 so it does not clash with other tests or a running simulator.
"""

import asyncio

import pytest
from bacpypes3.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.ede import export_ede, import_ede
from sme_bacnet_sim.engine import Engine, detect_ip

OBJECTS = """
      - {type: acc, name: Pulses, max: 999, units: kilowatt-hours, scale: 0.1, prescale: [1, 1],
         behavior: {type: pulse, rate: 10}}
      - {type: pc, name: Energy, input_object: Pulses, scale_factor: 0.5, units: kilowatt-hours}
      - {type: ai, name: Temp, units: degrees-celsius, value: 30,
         behavior: {type: follow, target: "30 - Valve / 10", tau: 5}}
      - {type: ao, name: Valve, units: percent, min: 0, max: 100}
      - {type: av, name: TempSP, units: degrees-celsius, value: 24}
      - {type: loop, name: TempLoop, controlled_object: Temp, manipulated_object: Valve, setpoint_object: TempSP,
         proportional_constant: 5, integral_constant: 0.5, min: 0, max: 100, units: percent,
         priority_for_writing: 10}
"""
CONFIG = """
network: {ip: auto, port: 47960, virtual_network: 245, router: {device_id: 4194160}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2451
    name: Ctl-Dev
    objects:
""" + OBJECTS


def _runtime(text=CONFIG):
    e = Engine(parse_text(text))
    e.devices = e._prepare(e.config)
    return e, next(iter(e.devices.values()))


def _p(rt, name):
    return next(p for p in rt.points if p.cfg.name == name)


def test_pulse_accumulator_and_converter():
    async def run():
        e, rt = _runtime()
        for _ in range(250):  # 2500 pulses: the accumulator wraps twice at max 999
            e.step(1.0)
        assert _p(rt, "Pulses").read() == 2500 % 1000
        pc = _p(rt, "Energy")
        assert pc.read() == pytest.approx(2500 * 0.5)
        assert int(pc.obj.count) == 500
        pc.obj.outOfService = True  # out of service: count tracked, present value frozen
        e.step(1.0)
        assert pc.read() == pytest.approx(1250.0) and int(pc.obj.count) == 510
    asyncio.run(run())


@pytest.mark.parametrize("action,target,start", [("direct", "30 - Valve / 10", 30.0),
                                                 ("reverse", "18 + Valve / 10", 18.0)])
def test_pid_converges(action, target, start):
    text = CONFIG.replace('"30 - Valve / 10"', f'"{target}"').replace("value: 30,", f"value: {start},") \
        .replace("priority_for_writing: 10}", f"priority_for_writing: 10, action: {action}}}")
    async def run():
        e, rt = _runtime(text)
        for _ in range(400):
            e.step(1.0)
        loop, valve = _p(rt, "TempLoop"), _p(rt, "Valve")
        assert _p(rt, "Temp").read() == pytest.approx(24.0, abs=0.05)
        assert valve.read() == pytest.approx(60.0, abs=1.0) and loop.read() == pytest.approx(valve.read())
        assert valve.obj.currentCommandPriority.unsigned == 10
        assert float(loop.obj.controlledVariableValue) == pytest.approx(24.0, abs=0.05)
        loop.obj.outOfService = True  # no computation, no output write
        _p(rt, "TempSP").obj.presentValue = 20.0
        before = valve.read()
        for _ in range(20):
            e.step(1.0)
        assert valve.read() == before
    asyncio.run(run())


def test_config_errors():
    bad = [
        "- {type: loop, name: L, manipulated_object: B, setpoint: 1}",  # no controlled object
        "- {type: loop, name: L, controlled_object: A, manipulated_object: B}",  # no setpoint
        "- {type: acc, name: A, max: 0}",
        "- {type: pc, name: P, commandable: true}",
        "- {type: acc, name: A, alarm: {notification_class: 1, high_limit: 5}}",
    ]
    for b in bad:
        with pytest.raises(Exception):
            parse_text(f"devices: [{{device_id: 1, name: D, objects: [{b[2:]}]}}]")
    async def run():
        with pytest.raises(ValueError, match="not an accumulator"):
            _runtime(CONFIG.replace("input_object: Pulses", "input_object: Temp"))
    asyncio.run(run())


def test_ede_roundtrip():
    files = export_ede(parse_text(CONFIG))
    main = next(v for k, v in files.items() if "State" not in k and "state" not in k)
    cfg, warnings = import_ede(main)
    objs = {o.name: o for o in cfg.devices[0].objects}
    assert objs["Pulses"].type == "accumulator" and objs["Pulses"].units == "kilowatt-hours"
    assert objs["Pulses"].max == 999
    assert objs["Energy"].type == "pulse-converter"
    assert "TempLoop" not in objs and any("TempLoop" in w for w in warnings)


def test_bacnet_access():
    asyncio.run(_flow())


async def _flow():
    ip = detect_ip()
    engine = Engine(parse_text(CONFIG))
    await engine.start()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194261), objectName="ctl-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47961", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    acc, pc, loop = (ObjectIdentifier(x) for x in ("accumulator,1", "pulse-converter,1", "loop,1"))
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47960"), [245])
        iams = await client.who_is(address=Address("245:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2451]
        rt = engine.devices[2451]
        async with engine._lock:
            for _ in range(10):
                engine.step(1.0)

        assert await client.read_property(addr, acc, "present-value") == 100
        assert await client.read_property(addr, acc, "max-pres-value") == 999
        assert float((await client.read_property(addr, acc, "scale")).floatScale) == pytest.approx(0.1)
        assert await client.read_property(addr, pc, "present-value") == pytest.approx(50.0)
        assert await client.read_property(addr, pc, "scale-factor") == pytest.approx(0.5)
        ref = await client.read_property(addr, pc, "input-reference")
        assert tuple(ref.objectIdentifier) == (ObjectIdentifier("accumulator,1")[0], 1)
        res = await client.read_property_multiple(addr, [loop, ["present-value", "setpoint", "action",
                                                                "manipulated-variable-reference"]])
        vals = {str(r[1]): r[3] for r in res}
        assert vals["setpoint"] == pytest.approx(24.0) and str(vals["action"]) == "direct"
        assert tuple(vals["manipulated-variable-reference"].objectIdentifier)[1] == 1

        # writable parameters: tuning constants, adjust-value (plain property)
        await client.write_property(addr, loop, "proportional-constant", 2.5)
        await client.write_property(addr, pc, "adjust-value", 3.0)
        assert float(_p(rt, "TempLoop").obj.proportionalConstant) == 2.5
        assert await client.read_property(addr, pc, "adjust-value") == pytest.approx(3.0)

        # COV on pulse converter (COV increment criteria) and loop (generic criteria)
        for i, oid in enumerate((pc, loop), start=1):
            async with client.change_of_value(addr, oid, i, True, 60) as scm:
                first = await asyncio.wait_for(scm.get_value(), 3)
                assert str(first[0]) == "present-value"
                async with engine._lock:
                    engine.step(1.0)
                engine.request_scan()
                await asyncio.wait_for(scm.get_value(), 3)
    finally:
        client.close()
        await engine.stop()
