"""Event Enrollment (algorithmic reporting): out-of-range and change-of-state notifications, AcknowledgeAlarm,
GetEventInformation / GetAlarmSummary, BACnet writes to Event_Parameters written back to the config.

Uses BACnet port 47980 / client port 47981 so it does not clash with other tests or a running simulator.
"""

import asyncio

import pytest
from bacpypes3.apdu import (
    AcknowledgeAlarmRequest, GetAlarmSummaryACK, GetAlarmSummaryRequest, GetEventInformationACK,
    GetEventInformationRequest, SimpleAckPDU,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import DateTime, EventParameter, EventParameterOutOfRange, TimeStamp
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.ede import export_ede, import_ede
from sme_bacnet_sim.engine import Engine, detect_ip

CLIENT_ID = 4194281
CONFIG = """
network: {ip: auto, port: 47980, virtual_network: 280, router: {device_id: 4194180}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2801
    name: EE-Dev
    objects:
      - type: nc
        name: NC1
        instance: 1
        priority: [10, 20, 30]
        ack_required: [true, true, false]
        recipients:
          - {device: 4194281, address: "@IP@:47981", process_id: 9, confirmed: true}
      - {type: ai, name: Temp, value: 20, units: degrees-celsius}
      - {type: msv, name: Mode, value: 1, states: [auto, manual, "off"]}
      - type: ee
        name: TempWatch
        monitored_object: Temp
        event_type: out-of-range
        event_parameters: {low_limit: 10, high_limit: 30, deadband: 1}
        notification_class: NC1
        time_delay: 30
      - type: ee
        name: ModeWatch
        monitored_object: Mode
        event_type: change-of-state
        event_parameters: {alarm_values: ["off"]}
        notification_class: 1
        notify_type: event
"""

EE1 = ObjectIdentifier("event-enrollment,1")
EE2 = ObjectIdentifier("event-enrollment,2")


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


def test_event_enrollment_flow():
    asyncio.run(_flow())


async def _flow():
    ip = detect_ip()
    engine = Engine(parse_text(CONFIG.replace("@IP@", ip.split("/")[0])))
    await engine.start()
    client = Recorder.from_object_list([
        DeviceObject(objectIdentifier=("device", CLIENT_ID), objectName="ee-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47981", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    client.got = []
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47980"), [280])
        iams = await client.who_is(address=Address("280:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2801]

        assert str(await client.read_property(addr, EE1, "event-type")) == "out-of-range"
        ep = await client.read_property(addr, EE1, "event-parameters")
        assert (ep.outOfRange.highLimit, ep.outOfRange.lowLimit, ep.outOfRange.timeDelay) == (30, 10, 30)
        ref = await client.read_property(addr, EE1, "object-property-reference")
        assert ref.objectIdentifier == ObjectIdentifier("analog-input,1")
        assert await client.read_property(addr, EE1, "notification-class") == 1

        # out-of-range: high limit after the 30 s time delay
        await engine.write(2801, "analog-input:1", 35)
        await asyncio.sleep(0.2)
        engine.step(29)
        await asyncio.sleep(0.3)
        assert client.got == []
        engine.step(1)
        await _wait(client.got, 1)
        n = client.got[0]
        assert n.eventObjectIdentifier == EE1
        assert (str(n.fromState), str(n.toState), str(n.eventType)) == ("normal", "high-limit", "out-of-range")
        assert (n.priority, n.processIdentifier) == (10, 9) and n.ackRequired
        assert n.eventValues.outOfRange.exceededLimit == 30 and n.eventValues.outOfRange.exceedingValue == 35
        assert str(await client.read_property(addr, EE1, "event-state")) == "high-limit"

        # change-of-state: no time delay, evaluated while paused
        await engine.write(2801, "multi-state-value:1", 3)
        await asyncio.sleep(0.2)
        await _wait(client.got, 2)
        n = client.got[1]
        assert n.eventObjectIdentifier == EE2 and str(n.eventType) == "change-of-state"
        assert str(n.toState) == "offnormal" and str(n.notifyType) == "event"
        assert n.eventValues.changeOfState.newState.unsignedValue == 3

        info = await client.request(GetEventInformationRequest(destination=addr))
        assert isinstance(info, GetEventInformationACK), info
        assert [s.objectIdentifier for s in info.listOfEventSummaries] == [EE1, EE2]
        summ = await client.request(GetAlarmSummaryRequest(destination=addr))
        assert isinstance(summ, GetAlarmSummaryACK), summ
        assert [x.objectIdentifier for x in summ.listOfAlarmSummaries] == [EE1]  # EE2 is notify-type event

        # AcknowledgeAlarm of the event enrollment
        ack = await client.request(AcknowledgeAlarmRequest(
            acknowledgingProcessIdentifier=9, eventObjectIdentifier=EE1, eventStateAcknowledged="high-limit",
            timestamp=client.got[0].timestamp, acknowledgmentSource="pytest",
            timeOfAcknowledgment=TimeStamp(datetime=DateTime.now()), destination=addr))
        assert isinstance(ack, SimpleAckPDU), ack
        assert list(await client.read_property(addr, EE1, "acked-transitions")) == [1, 1, 1]
        engine.acknowledge(2801, "event-enrollment:2")  # web UI
        assert not engine.devices[2801].ees[1].alarm.unacked

        # UI snapshot lists the enrollments with their alarm state
        snap = {o["k"]: o for o in engine.snapshot()["devices"][0]["objects"]}
        assert snap["event-enrollment:1"]["event_state"] == "high-limit"
        assert snap["event-enrollment:1"]["monitored"] == "Temp"

        # write Event_Parameters: new high limit, kept in the config
        await client.write_property(addr, EE1, "event-parameters", EventParameter(outOfRange=EventParameterOutOfRange(
            timeDelay=0, lowLimit=10.0, highLimit=40.0, deadband=1.0)))
        await asyncio.sleep(0.2)
        oc = next(o for o in engine.config.devices[0].objects if o.name == "TempWatch")
        assert oc.event_parameters["high_limit"] == 40 and oc.time_delay == 0
        engine.step(1)
        await _wait(client.got, 3)
        assert (str(client.got[2].fromState), str(client.got[2].toState)) == ("high-limit", "normal")

        # EDE export carries the event enrollments; import skips them with a warning
        main = next(iter(export_ede(engine.config).values()))
        assert "TempWatch" in main and "ModeWatch" in main
        _, warnings = import_ede(main)
        assert any("event-enrollment" in w for w in warnings)
    finally:
        client.close()
        await engine.stop()


BASE = """
network: {port: 47982}
devices:
  - device_id: 1
    name: D
    objects:
      - {type: nc, name: N, instance: 1}
      - {type: ai, name: T}
      - {type: bi, name: B}
"""


@pytest.mark.parametrize("obj, message", [
    ("{type: ee, name: E, monitored_object: X, event_type: out-of-range, notification_class: 1, "
     "event_parameters: {low_limit: 1, high_limit: 2}}", "is not a value object"),
    ("{type: ee, name: E, monitored_object: T, event_type: out-of-range, notification_class: 9, "
     "event_parameters: {low_limit: 1, high_limit: 2}}", "is not a notification-class"),
    ("{type: ee, name: E, monitored_object: B, event_type: out-of-range, notification_class: 1, "
     "event_parameters: {low_limit: 1, high_limit: 2}}", "needs an analog"),
    ("{type: ee, name: E, monitored_object: T, event_type: floating-limit, notification_class: 1}", "not supported"),
    ("{type: ee, name: E, monitored_object: B, event_type: change-of-state, notification_class: 1, "
     "event_parameters: {alarm_values: [maybe]}}", "invalid binary value"),
    ("{type: ai, name: A, monitored_object: T}", "only valid for event-enrollment"),
])
def test_event_enrollment_config_errors(obj, message):
    text = BASE + "      - " + obj

    async def run():
        cfg = parse_text(text)
        Engine(cfg)._prepare(cfg)

    with pytest.raises(ValueError, match=message):
        asyncio.run(run())
