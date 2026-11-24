"""End-to-end test: a bacpypes3 client talks to the simulator through the router.

Run:  python -m pytest -q
Uses BACnet port 47900 / client port 47901 so it does not clash with a running simulator.
"""

import asyncio

import pytest
from bacpypes3.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

from sme_bacnet_sim.behaviors import ExpressionError, compile_expr
from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine, detect_ip

CONFIG = """
network: {ip: auto, port: 47900, virtual_network: 200, router: {device_id: 4194100}}
simulation: {tick_seconds: 0.2}
devices:
  - {device_id: 2001, name: AC-1, template: split_ac}
  - {device_id: 2002, name: Light-1, template: lighting, params: {zones: 2}}
"""


def test_expression_sandbox():
    assert compile_expr("clamp(a * 2, 0, 5)")({"a": 4}) == 5
    for bad in ("__import__('os')", "a.__class__", "(lambda: 1)()", "[x for x in a]"):
        with pytest.raises(ExpressionError):
            compile_expr(bad)


def test_bacnet_roundtrip():
    asyncio.run(_roundtrip())


async def _roundtrip():
    engine = Engine(parse_text(CONFIG))
    await engine.start()
    ip = detect_ip()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194200), objectName="test-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47901", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        router = Address(f"{ip.split('/')[0]}:47900")
        await client.nsap.update_router_references(None, router, [200])

        iams = await client.who_is(address=Address("200:*"), timeout=2)
        found = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}
        assert set(found) == {2001, 2002}

        ac = found[2001]
        names = await client.read_property(ac, ObjectIdentifier("device,2001"), "object-list")
        assert ObjectIdentifier("analog-value,1") in names

        # command the AC on at priority 8 and lower the set point
        await client.write_property(ac, ObjectIdentifier("binary-output,1"), "present-value", "active", priority=8)
        await client.write_property(ac, ObjectIdentifier("analog-value,1"), "present-value", 18.0, priority=8)
        await asyncio.sleep(0.6)

        status = await client.read_property(ac, ObjectIdentifier("binary-input,1"), "present-value")
        assert status == 1  # RunStatus follows OnOff
        sp = engine.point(2001, "analog-value:1")
        assert sp.read() == 18.0 and sp.obj.currentCommandPriority.unsigned == 8
        assert any(e["kind"] == "bacnet-write" for e in engine.events)

        # reload with one device removed keeps the stack serving
        cfg = engine.config.model_copy(deep=True)
        cfg.devices = cfg.devices[1:]
        await engine.reload(cfg)
        await asyncio.sleep(0.2)
        iams = await client.who_is(address=Address("200:*"), timeout=2)
        assert {i.iAmDeviceIdentifier[1] for i in iams} == {2002}
    finally:
        client.close()
        await engine.stop()
