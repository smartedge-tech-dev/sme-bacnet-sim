"""Alarms: intrinsic reporting on the simulated clock, Notification Class recipients, AcknowledgeAlarm and the
GetEventInformation / GetAlarmSummary / GetEnrollmentSummary services, checked from a bacpypes3 client.

Uses BACnet port 47920 / client port 47921 so it does not clash with other tests or a running simulator.
"""

import asyncio

import pytest
from bacpypes3.apdu import (
    AcknowledgeAlarmRequest, GetAlarmSummaryACK, GetAlarmSummaryRequest, GetEnrollmentSummaryACK,
    GetEnrollmentSummaryRequest, GetEventInformationACK, GetEventInformationRequest, SimpleAckPDU,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import DateTime, TimeStamp
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

from sme_bacnet_sim.config import DeviceConfig, parse_text
from sme_bacnet_sim.engine import Engine, detect_ip
from sme_bacnet_sim.templates import expand_device

CLIENT_ID = 4194221
# paused clock: the test advances the simulated time with engine.step()
CONFIG = """
network: {ip: auto, port: 47920, virtual_network: 220, router: {device_id: 4194120}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2201
    name: Alarm-Dev
    objects:
      - type: nc
        name: NC1
        instance: 1
        priority: [10, 20, 30]
        ack_required: [true, true, false]
        recipients:
          - {device: 4194221, address: "@IP@:47921", process_id: 7, confirmed: true}
      - type: ai
        name: Temp
        value: 20
        alarm: {notification_class: NC1, high_limit: 30, low_limit: 10, deadband: 1, time_delay: 60}
      - type: bi
        name: Filter
        value: 0
        alarm: {notification_class: 1, alarm_value: active, notify_type: event}
"""

AI1 = ObjectIdentifier("analog-input,1")
BI1 = ObjectIdentifier("binary-input,1")


class Recorder(Application):
    got: list

    async def do_ConfirmedEventNotificationRequest(self, apdu) -> None:
        self.got.append(apdu)
        await self.response(SimpleAckPDU(context=apdu))

    async def do_UnconfirmedEventNotificationRequest(self, apdu) -> None:
        self.got.append(apdu)


async def _wait(lst, n, timeout=3.0):
    for _ in range(int(timeout / 0.05)):
        if len(lst) >= n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"expected {n} notification(s), got {len(lst)}")


def test_alarm_flow():
    asyncio.run(_flow())


async def _flow():
    ip = detect_ip()
    engine = Engine(parse_text(CONFIG.replace("@IP@", ip.split("/")[0])))
    await engine.start()
    client = Recorder.from_object_list([
        DeviceObject(objectIdentifier=("device", CLIENT_ID), objectName="alarm-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47921", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    client.got = []
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47920"), [220])
        iams = await client.who_is(address=Address("220:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2201]

        assert await client.read_property(addr, AI1, "notification-class") == 1
        assert await client.read_property(addr, AI1, "high-limit") == 30
        nc = await client.read_property(addr, ObjectIdentifier("notification-class,1"), "priority")
        assert list(nc) == [10, 20, 30]

        # over the high limit: nothing before time_delay (60 sim s) has elapsed
        await engine.write(2201, "analog-input:1", 35)
        await asyncio.sleep(0.2)  # let the scan see the write at the current sim time
        engine.step(30)
        await asyncio.sleep(0.3)
        assert client.got == []
        assert str(await client.read_property(addr, AI1, "event-state")) == "normal"
        engine.step(30)
        await _wait(client.got, 1)
        n = client.got[0]
        assert (str(n.fromState), str(n.toState)) == ("normal", "high-limit")
        assert (n.priority, n.notificationClass, n.processIdentifier) == (10, 1, 7)
        assert str(n.eventType) == "out-of-range" and str(n.notifyType) == "alarm" and n.ackRequired
        assert n.eventObjectIdentifier == AI1
        assert n.eventValues.outOfRange.exceededLimit == 30
        assert str(await client.read_property(addr, AI1, "event-state")) == "high-limit"
        assert (await client.read_property(addr, AI1, "status-flags"))[0] == 1  # in-alarm
        assert list(await client.read_property(addr, AI1, "acked-transitions")) == [0, 1, 1]

        # summaries
        info = await client.request(GetEventInformationRequest(destination=addr))
        assert isinstance(info, GetEventInformationACK), info
        assert [s.objectIdentifier for s in info.listOfEventSummaries] == [AI1]
        s = info.listOfEventSummaries[0]
        assert str(s.eventState) == "high-limit" and list(s.acknowledgedTransitions) == [0, 1, 1]
        assert list(s.eventPriorities) == [10, 20, 30]
        summ = await client.request(GetAlarmSummaryRequest(destination=addr))
        assert isinstance(summ, GetAlarmSummaryACK), summ
        assert [x.objectIdentifier for x in summ.listOfAlarmSummaries] == [AI1]
        enr = await client.request(GetEnrollmentSummaryRequest(acknowledgmentFilter="all", destination=addr))
        assert isinstance(enr, GetEnrollmentSummaryACK), enr
        assert [x.objectIdentifier for x in enr.listOfEnrollmentSummaries] == [AI1, BI1]
        enr = await client.request(GetEnrollmentSummaryRequest(acknowledgmentFilter="not-acked", destination=addr))
        assert [x.objectIdentifier for x in enr.listOfEnrollmentSummaries] == [AI1]

        # acknowledge the to-offnormal transition with the time stamp from the notification
        ack = await client.request(AcknowledgeAlarmRequest(
            acknowledgingProcessIdentifier=7, eventObjectIdentifier=AI1, eventStateAcknowledged="high-limit",
            timestamp=n.timestamp, acknowledgmentSource="pytest",
            timeOfAcknowledgment=TimeStamp(datetime=DateTime.now()), destination=addr))
        assert isinstance(ack, SimpleAckPDU), ack
        assert list(await client.read_property(addr, AI1, "acked-transitions")) == [1, 1, 1]
        assert not engine.point(2201, "analog-input:1").alarm.unacked
        assert any(e["kind"] == "alarm-ack" for e in engine.events)

        # inside the deadband: still high-limit; below it: to-normal after time_delay
        await engine.write(2201, "analog-input:1", 29.5)
        await asyncio.sleep(0.2)  # let the scan see the write at the current sim time
        engine.step(120)
        await asyncio.sleep(0.3)
        assert len(client.got) == 1
        await engine.write(2201, "analog-input:1", 25)
        await asyncio.sleep(0.2)  # let the scan see the write at the current sim time
        engine.step(59)
        await asyncio.sleep(0.3)
        assert len(client.got) == 1
        engine.step(1)
        await _wait(client.got, 2)
        n = client.got[1]
        assert (str(n.fromState), str(n.toState), n.priority) == ("high-limit", "normal", 30)
        assert not n.ackRequired
        info = await client.request(GetEventInformationRequest(destination=addr))
        assert list(info.listOfEventSummaries) == []

        # binary change-of-state without time delay, evaluated even while paused
        await engine.write(2201, "binary-input:1", 1)
        await asyncio.sleep(0.2)  # let the scan see the write at the current sim time
        await _wait(client.got, 3)
        n = client.got[2]
        assert n.eventObjectIdentifier == BI1 and str(n.eventType) == "change-of-state"
        assert str(n.toState) == "offnormal" and str(n.notifyType) == "event"
        assert any(e["kind"] == "alarm" for e in engine.events)
    finally:
        client.close()
        await engine.stop()


BASE = """
network: {port: 47922}
devices:
  - device_id: 1
    name: D
    objects:
"""


@pytest.mark.parametrize("objects, message", [
    ("- {type: ai, name: T, alarm: {notification_class: NC9, high_limit: 30}}", "is not a notification-class"),
    ("- {type: ai, name: T, alarm: {notification_class: 1, high_limit: 10, low_limit: 20}}", "must be below"),
    ("- {type: ai, name: T, alarm: {notification_class: 1}}", "needs high_limit and/or low_limit"),
    ("- {type: bi, name: B, alarm: {notification_class: 1}}", "needs alarm_value"),
    ("- {type: bi, name: B, alarm: {notification_class: 1, alarm_value: active, high_limit: 3}}", "not valid for"),
    ("- {type: msi, name: M, states: [a, b], alarm: {notification_class: 1, alarm_values: [c]}}", "invalid state"),
    ("- {type: nc, name: N, recipients: [{process_id: 1}]}", "needs 'device' and/or 'address'"),
    ("- {type: nc, name: N, priority: [1, 2]}", "priority needs 3 values"),
    ("- {type: ai, name: T, priority: [1, 2, 3]}", "only valid for notification-class"),
])
def test_alarm_config_errors(objects, message):
    async def run():
        Engine(parse_text(BASE + "      " + objects))._prepare(parse_text(BASE + "      " + objects))

    with pytest.raises(ValueError, match=message):
        asyncio.run(run())


def test_template_alarms():
    async def run():
        cfg = parse_text("""
devices:
  - {device_id: 1, name: AC, template: split_ac}
  - {device_id: 2, name: AHU, template: ahu}
  - {device_id: 3, name: PM, template: power_meter, params: {nominal_voltage: 100}}
  - {device_id: 4, name: PM2, template: power_meter, params: {alarms: false}}
""")
        rts = Engine(cfg)._prepare(cfg)
        assert [a.point.cfg.name for a in rts[1].alarms] == ["RoomTemp"]
        assert [a.point.cfg.name for a in rts[2].alarms] == ["FilterAlarm"]
        v = rts[3].alarms[0]
        assert (float(v.obj.highLimit), float(v.obj.lowLimit)) == (110, 90)
        assert rts[1].ncs[0].number == 1 and not rts[4].alarms and not rts[4].ncs
        # expanding an already expanded device again (template + its own dumped objects) stays valid
        dev = cfg.devices[0]
        again = DeviceConfig.model_validate({**dev.model_dump(exclude_none=True),
                                             "objects": [o.model_dump(exclude_none=True) for o in expand_device(dev)]})
        assert len(expand_device(again)) == len(expand_device(dev))

    asyncio.run(run())
