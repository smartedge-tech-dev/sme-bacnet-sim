"""COV: SubscribeCOV (confirmed / unconfirmed, lifetime, covIncrement, status flags) and SubscribeCOVProperty,
checked from a bacpypes3 client.

Uses BACnet port 47940 / client port 47941 so it does not clash with other tests or a running simulator.
"""

import asyncio

from bacpypes3.apdu import SimpleAckPDU, SubscribeCOVPropertyRequest, SubscribeCOVRequest
from bacpypes3.app import Application
from bacpypes3.basetypes import PropertyReference, StatusFlags
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier, Real

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine, detect_ip

CONFIG = """
network: {ip: auto, port: 47940, virtual_network: 240, router: {device_id: 4194140}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2401
    name: Cov-Dev
    objects:
      - {type: av, name: Setpoint, value: 20, cov_increment: 1.0}
      - {type: bv, name: Mode, value: 0}
"""

AV1 = ObjectIdentifier("analog-value,1")
BV1 = ObjectIdentifier("binary-value,1")


class Recorder(Application):
    got: list

    async def do_ConfirmedCOVNotificationRequest(self, apdu) -> None:
        self.got.append(apdu)
        await self.response(SimpleAckPDU(context=apdu))

    async def do_UnconfirmedCOVNotificationRequest(self, apdu) -> None:
        self.got.append(apdu)


def _values(n):
    return {str(pv.propertyIdentifier): pv.propertyValue for pv in n.listOfValues}


def test_cov():
    asyncio.run(_flow())


async def _flow():
    ip = detect_ip()
    engine = Engine(parse_text(CONFIG))
    await engine.start()
    client = Recorder.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194241), objectName="cov-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47941", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    client.got = []

    def notes(proc):
        return [n for n in client.got if n.subscriberProcessIdentifier == proc]

    async def wait(proc, n, timeout=3.0):
        for _ in range(int(timeout / 0.05)):
            if len(notes(proc)) >= n:
                return notes(proc)[-1]
            await asyncio.sleep(0.05)
        raise AssertionError(f"process {proc}: expected {n} notification(s), got {len(notes(proc))}")

    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47940"), [240])
        iams = await client.who_is(address=Address("240:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2401]

        # confirmed SubscribeCOV with lifetime: initial notification
        ack = await client.request(SubscribeCOVRequest(
            subscriberProcessIdentifier=1, monitoredObjectIdentifier=AV1, issueConfirmedNotifications=True,
            lifetime=60, destination=addr))
        assert isinstance(ack, SimpleAckPDU), ack
        n = await wait(1, 1)
        assert 0 < n.timeRemaining <= 60
        assert float(_values(n)["present-value"].cast_out(Real)) == 20

        # below covIncrement (1.0): nothing; above: notification
        await engine.write(2401, "analog-value:1", 20.5)
        await asyncio.sleep(0.3)
        assert len(notes(1)) == 1
        await engine.write(2401, "analog-value:1", 21.5)
        await wait(1, 2)

        # write from a BACnet client
        await client.write_property(addr, AV1, "present-value", 25.0)
        await wait(1, 3)

        # status flags: out-of-service alone triggers a notification
        engine.set_oos(2401, "analog-value:1", True)
        n = await wait(1, 4)
        assert list(_values(n)["status-flags"].cast_out(StatusFlags)) == [0, 0, 0, 1]

        # unconfirmed SubscribeCOV, lifetime 2 s; value changed like a behavior does (direct assignment)
        ack = await client.request(SubscribeCOVRequest(
            subscriberProcessIdentifier=2, monitoredObjectIdentifier=BV1, issueConfirmedNotifications=False,
            lifetime=2, destination=addr))
        assert isinstance(ack, SimpleAckPDU), ack
        await wait(2, 1)
        engine.point(2401, "binary-value:1").obj.presentValue = "active"
        await wait(2, 2)
        await asyncio.sleep(2.3)  # subscription expired
        engine.point(2401, "binary-value:1").obj.presentValue = "inactive"
        await asyncio.sleep(0.3)
        assert len(notes(2)) == 2

        # SubscribeCOVProperty with its own increment (5.0)
        ack = await client.request(SubscribeCOVPropertyRequest(
            subscriberProcessIdentifier=3, monitoredObjectIdentifier=AV1, issueConfirmedNotifications=True,
            lifetime=60, monitoredPropertyIdentifier=PropertyReference(propertyIdentifier="present-value"),
            covIncrement=5.0, destination=addr))
        assert isinstance(ack, SimpleAckPDU), ack
        n = await wait(3, 1)
        assert set(_values(n)) == {"present-value", "status-flags"}
        await engine.write(2401, "analog-value:1", 27)
        await asyncio.sleep(0.3)
        assert len(notes(3)) == 1
        await engine.write(2401, "analog-value:1", 31)
        await wait(3, 2)
        # cancel
        ack = await client.request(SubscribeCOVPropertyRequest(
            subscriberProcessIdentifier=3, monitoredObjectIdentifier=AV1,
            monitoredPropertyIdentifier=PropertyReference(propertyIdentifier="present-value"), destination=addr))
        assert isinstance(ack, SimpleAckPDU), ack
        await engine.write(2401, "analog-value:1", 50)
        await asyncio.sleep(0.3)
        assert len(notes(3)) == 2
    finally:
        client.close()
        await engine.stop()
