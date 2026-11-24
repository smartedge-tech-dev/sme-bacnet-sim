"""Device management services from a bacpypes3 client: CreateObject / DeleteObject, TimeSynchronization /
UTCTimeSynchronization, DeviceCommunicationControl and ReinitializeDevice.

Uses BACnet port 47930 / client port 47931 so it does not clash with other tests or a running simulator.
"""

import asyncio
import time

import pytest
from bacpypes3.apdu import (
    CreateObjectACK, CreateObjectRequest, DeleteObjectRequest, DeviceCommunicationControlRequest,
    ReinitializeDeviceRequest, SimpleAckPDU, TimeSynchronizationRequest, UTCTimeSynchronizationRequest,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import CreateObjectRequestObjectSpecifier, DateTime, EngineeringUnits, PropertyValue
from bacpypes3.constructeddata import Any
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import CharacterString, Date, ObjectIdentifier, Real, Time
from bacpypes3.errors import ExecutionError

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine, detect_ip
from sme_bacnet_sim.templates import TEMPLATES, expand_device
from sme_bacnet_sim.trendlog import to_datetime

CONFIG = """
network: {ip: auto, port: 47930, virtual_network: 230, router: {device_id: 4194130}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2301
    name: Mgmt-Dev
    dcc_password: secret
    reinit_password: boot
    objects:
      - {type: av, name: Setpoint, value: 20}
      - {type: bo, name: Fan, value: 0}
      - {type: trend-log, name: TL, log_object: Setpoint, log_interval: 10}
  - device_id: 2302
    name: Tmpl-Dev
    template: @TEMPLATE@
"""

AV1 = ObjectIdentifier("analog-value,1")
BO1 = ObjectIdentifier("binary-output,1")
TL1 = ObjectIdentifier("trend-log,1")


def _code(x) -> str:
    """Error code of an error response / exception, normalized (no dashes, lower case)."""
    r = getattr(x, "reason", None) or getattr(getattr(x, "errorType", None), "errorCode", None) \
        or getattr(x, "errorCode", None) or x
    return str(r).replace("-", "").lower()


async def _call(coro, timeout=5.0):
    try:
        return await asyncio.wait_for(coro, timeout)
    except BaseException as e:  # error / reject / abort PDUs are raised by bacpypes3 (not all are Exceptions)
        return e


def _pv(prop, value):
    return PropertyValue(propertyIdentifier=prop, propertyValue=Any(value))


def test_device_management():
    asyncio.run(_flow())


async def _flow():
    ip = detect_ip()
    host = ip.split("/")[0]
    engine = Engine(parse_text(CONFIG.replace("@TEMPLATE@", next(iter(TEMPLATES)))))
    await engine.start()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194231), objectName="mgmt-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47931", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    dev_cfg = engine.config.devices[0]
    try:
        await client.nsap.update_router_references(None, Address(f"{host}:47930"), [230])
        iams = await client.who_is(address=Address("230:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2301]

        # ---- CreateObject by type with initial values
        r = await _call(client.request(CreateObjectRequest(
            objectSpecifier=CreateObjectRequestObjectSpecifier(objectType="analog-value"),
            listOfInitialValues=[_pv("object-name", CharacterString("NewAV")), _pv("present-value", Real(12.5)),
                                 _pv("units", EngineeringUnits("degrees-celsius")),
                                 _pv("description", CharacterString("made by a client"))],
            destination=addr)))
        assert isinstance(r, CreateObjectACK), r
        new_av = ObjectIdentifier("analog-value,2")
        assert r.objectIdentifier == new_av
        assert await client.read_property(addr, new_av, "object-name") == "NewAV"
        assert await client.read_property(addr, new_av, "present-value") == 12.5
        assert str(await client.read_property(addr, new_av, "units")) == "degrees-celsius"
        assert new_av in list(await client.read_property(addr, ObjectIdentifier("device,2301"), "object-list"))
        assert any(o.name == "NewAV" and o.instance == 2 and o.units == "degrees-celsius" for o in dev_cfg.objects)
        snap = engine.snapshot()["devices"][0]
        assert any(o["name"] == "NewAV" for o in snap["objects"])

        # by identifier; again -> already exists; unsupported type; unknown initial property
        bv7 = ObjectIdentifier("binary-value,7")
        r = await _call(client.request(CreateObjectRequest(
            objectSpecifier=CreateObjectRequestObjectSpecifier(objectIdentifier=bv7), destination=addr)))
        assert isinstance(r, CreateObjectACK) and r.objectIdentifier == bv7, r
        assert await client.read_property(addr, bv7, "object-name") == "binary-value-7"
        r = await _call(client.request(CreateObjectRequest(
            objectSpecifier=CreateObjectRequestObjectSpecifier(objectIdentifier=bv7), destination=addr)))
        assert _code(r) == "objectidentifieralreadyexists", r
        r = await _call(client.request(CreateObjectRequest(
            objectSpecifier=CreateObjectRequestObjectSpecifier(objectType="trend-log"), destination=addr)))
        assert _code(r) == "dynamiccreationnotsupported", r
        r = await _call(client.request(CreateObjectRequest(
            objectSpecifier=CreateObjectRequestObjectSpecifier(objectType="analog-value"),
            listOfInitialValues=[_pv("object-name", CharacterString("X")), _pv("high-limit", Real(1))],
            destination=addr)))
        assert _code(r) == "writeaccessdenied", r
        r = await _call(client.request(CreateObjectRequest(
            objectSpecifier=CreateObjectRequestObjectSpecifier(objectType="analog-value"),
            listOfInitialValues=[_pv("object-name", CharacterString("Setpoint"))], destination=addr)))
        assert _code(r) == "duplicatename", r

        # ---- DeleteObject
        r = await _call(client.request(DeleteObjectRequest(objectIdentifier=new_av, destination=addr)))
        assert isinstance(r, SimpleAckPDU), r
        assert _code(await _call(client.read_property(addr, new_av, "object-name"))) == "unknownobject"
        assert not any(o.name == "NewAV" for o in dev_cfg.objects)
        for oid in (AV1, TL1, ObjectIdentifier("device,2301")):  # referenced by TL / not a value object
            r = await _call(client.request(DeleteObjectRequest(objectIdentifier=oid, destination=addr)))
            assert _code(r) == "objectdeletionnotpermitted", (oid, r)

        # template object: recorded in `removed`, survives template re-expansion
        tmpl = engine.devices[2302]
        for p in list(tmpl.points):
            try:
                engine.delete_object(2302, ObjectIdentifier(f"{p.cfg.type},{p.cfg.instance}"), "test")
            except ExecutionError:
                continue
            assert engine.config.devices[1].removed == [p.cfg.name]
            assert p.cfg.name not in [o.name for o in expand_device(engine.config.devices[1])]
            break
        else:
            pytest.fail("no deletable template object")

        # ---- TimeSynchronization (to the device) / UTCTimeSynchronization (to the router)
        target = float(int(time.time()) - 3 * 86400)
        client.request(TimeSynchronizationRequest(time=to_datetime(target), destination=addr))
        await asyncio.sleep(0.5)
        assert abs(engine.sim_epoch + engine.sim_time - target) < 1
        target = float(int(time.time()) + 3600)
        g = time.gmtime(target)
        utc = DateTime(date=Date((g.tm_year - 1900, g.tm_mon, g.tm_mday, g.tm_wday + 1)),
                       time=Time((g.tm_hour, g.tm_min, g.tm_sec, 0)))
        client.request(UTCTimeSynchronizationRequest(time=utc, destination=Address(f"{host}:47930")))
        await asyncio.sleep(0.5)
        assert abs(engine.sim_epoch + engine.sim_time - target) < 1
        assert any(e["kind"] == "time-sync" for e in engine.events)

        # ---- DeviceCommunicationControl
        r = await _call(client.request(DeviceCommunicationControlRequest(
            enableDisable="disable", password="wrong", destination=addr)))
        assert _code(r) == "passwordfailure", r
        r = await _call(client.request(DeviceCommunicationControlRequest(
            enableDisable="disable", timeDuration=5, password="secret", destination=addr)))
        assert isinstance(r, SimpleAckPDU), r
        assert engine.snapshot()["devices"][0]["comm"] == "disable"
        h = engine.devices[2301].app.__dict__["_dcc_handle"]  # wall-clock minutes
        assert 290 < h.when() - asyncio.get_running_loop().time() <= 300.001  # float rounding of loop.time()
        r = await _call(client.read_property(addr, AV1, "present-value"), timeout=1.5)
        assert isinstance(r, BaseException), r  # ignored while disabled (no answer)
        engine.set_dcc(2301, "enable")  # web UI
        assert engine.snapshot()["devices"][0]["comm"] == "enable"
        assert await client.read_property(addr, AV1, "present-value") == 20

        # ---- ReinitializeDevice
        await client.write_property(addr, AV1, "present-value", 50.0)
        await client.write_property(addr, BO1, "present-value", "active", priority=8)
        engine.step(30)  # trend log samples
        tl = engine.devices[2301].trendlogs[0]
        assert int(tl.obj.recordCount) > 0
        r = await _call(client.request(ReinitializeDeviceRequest(
            reinitializedStateOfDevice="warmstart", password="nope", destination=addr)))
        assert _code(r) == "passwordfailure", r
        r = await _call(client.request(ReinitializeDeviceRequest(
            reinitializedStateOfDevice="start-backup", password="boot", destination=addr)))
        assert _code(r) == "optionalfunctionalitynotsupported", r
        # disabled communication still accepts ReinitializeDevice, and a restart re-enables it
        r = await _call(client.request(DeviceCommunicationControlRequest(
            enableDisable="disable", password="secret", destination=addr)))
        assert isinstance(r, SimpleAckPDU), r
        r = await _call(client.request(ReinitializeDeviceRequest(
            reinitializedStateOfDevice="warmstart", password="boot", destination=addr)))
        assert isinstance(r, SimpleAckPDU), r
        await asyncio.sleep(0.2)
        assert engine.snapshot()["devices"][0]["comm"] == "enable"
        assert await client.read_property(addr, AV1, "present-value") == 20
        assert str(await client.read_property(addr, BO1, "present-value")) == "inactive"
        assert int(tl.obj.recordCount) > 0  # warmstart keeps trend logs
        r = await _call(client.request(ReinitializeDeviceRequest(
            reinitializedStateOfDevice="coldstart", password="boot", destination=addr)))
        assert isinstance(r, SimpleAckPDU), r
        await asyncio.sleep(0.2)
        assert int(tl.obj.recordCount) == 0
        assert any(e["kind"] == "reinit" for e in engine.events)
    finally:
        client.close()
        await engine.stop()
