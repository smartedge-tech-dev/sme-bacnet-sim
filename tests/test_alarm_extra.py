"""Alarm follow-ups: status-flags COV on an alarm transition, GetEnrollmentSummary enrollmentFilter, multi-state
re-alarm, BACnet writes to alarm properties (persisted in the config), demo config / COV increment defaults.

Uses BACnet port 47924 / client port 47925 so it does not clash with other tests or a running simulator.
"""

import asyncio
import math
from pathlib import Path

import pytest
from bacpypes3.apdu import (
    GetEnrollmentSummaryACK, GetEnrollmentSummaryRequest, SimpleAckPDU, SubscribeCOVRequest, WritePropertyMultipleError,
    WritePropertyMultipleRequest,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    DeviceAddress, PropertyValue, Recipient, RecipientProcess, StatusFlags, WriteAccessSpecification,
)
from bacpypes3.constructeddata import Any
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier, Real, Unsigned

from sme_bacnet_sim.behaviors import compile_expr
from sme_bacnet_sim.config import ANALOG_TYPES, ObjectConfig, dump_yaml, parse_text
from sme_bacnet_sim.engine import Engine, build_object, detect_ip
from sme_bacnet_sim.templates import AMBIENT, AMBIENT_MAX, expand_device

CLIENT_ID = 4194225
CONFIG = """
network: {ip: auto, port: 47924, virtual_network: 224, router: {device_id: 4194124}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2241
    name: Alarm-Extra
    objects:
      - type: nc
        name: NC1
        instance: 1
        recipients:
          - {device: 4194225, address: "@IP@:47925", process_id: 9, confirmed: false}
      - {type: nc, name: NC2, instance: 2}
      - type: ai
        name: Temp
        value: 20
        alarm: {notification_class: NC1, high_limit: 30, low_limit: 10, deadband: 1}
      - type: msv
        name: Mode
        value: 1
        states: [Idle, Low, High, Trip]
        alarm: {notification_class: NC1, alarm_values: [3, 4]}
"""

AI1 = ObjectIdentifier("analog-input,1")
MSV1 = ObjectIdentifier("multi-state-value,1")


class Recorder(Application):
    got: list
    cov: list

    async def do_UnconfirmedEventNotificationRequest(self, apdu) -> None:
        self.got.append(apdu)

    async def do_UnconfirmedCOVNotificationRequest(self, apdu) -> None:
        self.cov.append(apdu)


async def _wait(lst, n, timeout=3.0):
    for _ in range(int(timeout / 0.05)):
        if len(lst) >= n:
            return lst[n - 1]
        await asyncio.sleep(0.05)
    raise AssertionError(f"expected {n} notification(s), got {len(lst)}")


def _flags(n):
    v = {str(x.propertyIdentifier): x.propertyValue for x in n.listOfValues}
    return list(v["status-flags"].cast_out(StatusFlags))


def test_alarm_extras():
    asyncio.run(_flow())


async def _flow():
    ip = detect_ip()
    engine = Engine(parse_text(CONFIG.replace("@IP@", ip.split("/")[0])))
    await engine.start()
    client = Recorder.from_object_list([
        DeviceObject(objectIdentifier=("device", CLIENT_ID), objectName="alarm-extra-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47925", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    client.got, client.cov = [], []

    async def tick():
        await asyncio.sleep(0.2)  # let the scan see the write at the current sim time
        engine.step(1)
        await asyncio.sleep(0.2)

    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47924"), [224])
        iams = await client.who_is(address=Address("224:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2241]

        # alarm transition -> COV notification carrying the in-alarm status flag
        await client.request(SubscribeCOVRequest(
            subscriberProcessIdentifier=3, monitoredObjectIdentifier=AI1, issueConfirmedNotifications=False,
            lifetime=120, destination=addr))
        await _wait(client.cov, 1)
        assert _flags(client.cov[0]) == [0, 0, 0, 0]
        await engine.write(2241, "analog-input:1", 35)
        await tick()
        n = await _wait(client.got, 1)
        assert str(n.toState) == "high-limit"
        await asyncio.sleep(0.3)
        assert _flags(client.cov[-1]) == [1, 0, 0, 0]

        # enrollmentFilter: recipient (device) + process identifier of the object's notification class, over
        # the wire.  A filter matching nothing gives an ACK with an empty list (zero octets), which bacpypes3
        # 0.1.0 could not decode (client-side "invalid-tag"); fixed in sme_bacnet_sim/alarm.py.
        def enr(proc):
            return GetEnrollmentSummaryRequest(
                acknowledgmentFilter="all", destination=addr, enrollmentFilter=RecipientProcess(
                    recipient=Recipient(device=ObjectIdentifier(("device", CLIENT_ID))), processIdentifier=proc))
        ack = await client.request(enr(9))
        assert isinstance(ack, GetEnrollmentSummaryACK), ack
        assert [x.objectIdentifier for x in ack.listOfEnrollmentSummaries] == [AI1, MSV1]
        ack = await client.request(enr(8))
        assert isinstance(ack, GetEnrollmentSummaryACK), ack
        assert not ack.listOfEnrollmentSummaries
        ack = await client.request(GetEnrollmentSummaryRequest(
            acknowledgmentFilter="all", destination=addr, enrollmentFilter=RecipientProcess(
                recipient=Recipient(address=DeviceAddress(networkNumber=7, macAddress=b"")), processIdentifier=9)))
        assert not ack.listOfEnrollmentSummaries  # NC1's recipient is a device, not that address

        # WritePropertyMultiple is validated as a whole: one bad item -> nothing applied
        def wpm(*items):
            return WritePropertyMultipleRequest(destination=addr, listOfWriteAccessSpecifications=[
                WriteAccessSpecification(objectIdentifier=oid, listOfProperties=[
                    PropertyValue(propertyIdentifier=prop, propertyValue=Any(val))]) for oid, prop, val in items])
        for bad, code in (((AI1, "notification-class", Unsigned(99)), "value-out-of-range"),
                          ((AI1, "acked-transitions", Real(1.0)), "invalid-data-type"),
                          ((MSV1, "high-limit", Real(1.0)), "unknown-property"),
                          ((ObjectIdentifier("analog-value,77"), "present-value", Real(1.0)), "unknown-object")):
            with pytest.raises(WritePropertyMultipleError) as ei:
                await client.request(wpm((AI1, "deadband", Real(2.5)), bad))
            assert str(ei.value.errorType.errorCode) == code, ei.value.errorType
            assert ei.value.firstFailedWriteAttempt.objectIdentifier == bad[0]
            assert float(await client.read_property(addr, AI1, "deadband")) == 1  # first item not applied
        assert isinstance(await client.request(wpm((AI1, "deadband", Real(1.5)), (AI1, "time-delay", Unsigned(0)))),
                          SimpleAckPDU)
        assert float(await client.read_property(addr, AI1, "deadband")) == 1.5
        await client.write_property(addr, AI1, "deadband", 1.0)

        # multi-state re-alarm: offnormal -> offnormal on a different alarm value
        await engine.write(2241, "multi-state-value:1", 3)
        await tick()
        n = await _wait(client.got, 2)
        assert (str(n.fromState), str(n.toState), n.eventValues.changeOfState.newState.unsignedValue) == \
            ("normal", "offnormal", 3)
        await engine.write(2241, "multi-state-value:1", 4)
        await tick()
        n = await _wait(client.got, 3)
        assert (str(n.fromState), str(n.toState), n.eventValues.changeOfState.newState.unsignedValue) == \
            ("offnormal", "offnormal", 4)
        engine.step(5)
        await asyncio.sleep(0.3)
        assert len(client.got) == 3  # same value again: no new transition

        # BACnet writes to alarm properties take effect and land in the config
        await client.write_property(addr, AI1, "high-limit", 40.0)
        await client.write_property(addr, AI1, "time-delay", 5)
        await tick()
        engine.step(5)
        n = await _wait(client.got, 4)
        assert (str(n.fromState), str(n.toState)) == ("high-limit", "normal")
        await client.write_property(addr, AI1, "event-enable", [0, 1, 1])
        await client.write_property(addr, AI1, "limit-enable", [1, 0])
        await client.write_property(addr, MSV1, "alarm-values", [2])
        await client.write_property(addr, MSV1, "notification-class", 2)
        await tick()
        a = engine.point(2241, "analog-input:1").alarm
        assert a.event_enable == [False, True, True] and a.limit_enable == [True, False]
        assert float(await client.read_property(addr, AI1, "high-limit")) == 40
        m = engine.point(2241, "multi-state-value:1").alarm
        assert m.alarm_values == [2] and m.nc.number == 2

        objs = {o.name: o for o in engine.config.devices[0].objects}
        t = objs["Temp"].alarm
        assert (t.high_limit, t.time_delay, t.event_enable, t.limit_enable) == (40, 5, [False, True, True],
                                                                                [True, False])
        assert (objs["Mode"].alarm.alarm_values, objs["Mode"].alarm.notification_class) == ([2], "NC2")
        assert "high_limit: 40.0" in dump_yaml(engine.config)
        assert list(engine.enrollment_summary(2241, enr(9)).listOfEnrollmentSummaries)[0].objectIdentifier == AI1
        assert len(engine.enrollment_summary(2241, enr(9)).listOfEnrollmentSummaries) == 1  # Mode moved to NC2

        # event-enable to-offnormal off: the transition happens but is not notified
        await engine.write(2241, "analog-input:1", 5)
        await tick()
        engine.step(5)  # time_delay is 5 now
        await asyncio.sleep(0.3)
        # (Mode's offnormal -> normal after its alarm-values write may have been notified meanwhile)
        assert a.state == "low-limit" and len([g for g in client.got if g.eventObjectIdentifier == AI1]) == 2

        # read-only / invalid writes are refused
        async def refused(prop, value):
            try:
                await client.write_property(addr, AI1, prop, value)
            except BaseException as e:  # bacpypes3 Error* are not all Exception subclasses
                return str(e)
            return "accepted"
        assert "write-access-denied" in await refused("acked-transitions", [1, 1, 1])
        assert "value-out-of-range" in await refused("notification-class", 7)
        assert a.nc.number == 1
    finally:
        client.close()
        await engine.stop()


# ---- demo config: a fresh start stays out of alarm


def _demo():
    return parse_text((Path(__file__).parents[1] / "configs" / "demo-building.yaml").read_text(encoding="utf-8"))


def test_demo_split_ac_stays_normal():
    """RoomTemp follows (first-order lag, tiny noise) either SetPoint or the ambient curve, so it stays within
    [min, max] of its initial value, the SetPoint range and the ambient curve.  Checking those bounds against the
    alarm limits covers every simulated day without running one."""
    run = compile_expr(AMBIENT)
    peak = max(run({"hour": h / 10}) for h in range(240))
    assert math.isclose(peak, AMBIENT_MAX, abs_tol=1e-6)
    checked = 0
    for dev in _demo().devices:
        objs = {o.name: o for o in expand_device(dev)}
        if dev.template == "split_ac":
            al, sp, rt = objs["RoomTemp"].alarm, objs["SetPoint"], objs["RoomTemp"]
            hi = al.high_limit - al.deadband
            assert max(AMBIENT_MAX, sp.max, float(rt.value)) + 0.5 < hi, dev.name
            assert min(sp.min, float(rt.value)) - 0.5 > al.low_limit, dev.name
            checked += 1
        for o in objs.values():  # other alarmed points: bounded behaviors inside the limits, binaries normal
            if o.alarm is None or o.name == "RoomTemp":
                continue
            if o.type in ANALOG_TYPES:
                assert o.behavior["type"] == "random_walk", (dev.name, o.name)
                assert o.alarm.low_limit < o.behavior["min"] and o.behavior["max"] < o.alarm.high_limit
            else:
                assert not o.behavior and (o.value or 0) == 0 and o.alarm.alarm_value == "active"
    assert checked == 2


# ---- COV increment defaults


@pytest.mark.parametrize("spec, expected", [
    ({"units": "percent", "behavior": {"type": "random_walk", "min": 0, "max": 50, "step": 1}}, 0.5),
    ({"units": "kilowatts", "min": 0, "max": 200, "behavior": {"type": "expr", "expr": "1"}}, 2.0),
    ({"units": "degrees-celsius", "behavior": {"type": "follow", "target": "20"}}, 0.1),
    ({"units": "no-units", "behavior": {"type": "expr", "expr": "1"}}, 0.0),
    ({"units": "percent"}, 0.0),
    ({"units": "percent", "cov_increment": 2, "behavior": {"type": "expr", "expr": "1"}}, 2.0),
])
def test_default_cov_increment(spec, expected):
    async def run():
        return build_object(ObjectConfig(type="ai", instance=1, name="X", **spec))
    assert asyncio.run(run()).covIncrement == pytest.approx(expected)


def test_demo_points_have_cov_increment():
    async def run():
        for dev in _demo().devices:
            for o in expand_device(dev):
                if o.type in ANALOG_TYPES and o.behavior:
                    assert build_object(o).covIncrement > 0, (dev.name, o.name)
    asyncio.run(run())
