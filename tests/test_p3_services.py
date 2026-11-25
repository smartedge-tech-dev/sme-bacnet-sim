"""Life Safety Point / Zone, LifeSafetyOperation, TextMessage, PrivateTransfer, AddListElement / RemoveListElement.

Uses port 47986 / client port 47987 so it does not clash with other tests or a running simulator.
"""

import asyncio

import pytest
from bacpypes3.apdu import (
    AddListElementRequest, ConfirmedPrivateTransferACK, ConfirmedPrivateTransferRequest, ConfirmedTextMessageRequest,
    LifeSafetyOperationRequest, RemoveListElementRequest, SimpleAckPDU, UnconfirmedPrivateTransferRequest,
    UnconfirmedTextMessageRequest,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import Destination, DeviceObjectReference, LifeSafetyMode, LifeSafetyState
from bacpypes3.constructeddata import Any as AnyValue, ListOf
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned

from sme_bacnet_sim.alarm import NCRecipient
from sme_bacnet_sim.config import RecipientConfig, parse_text
from sme_bacnet_sim.ede import export_ede, import_ede
from sme_bacnet_sim.engine import Engine, detect_ip
from sme_bacnet_sim.lifesafety import build_life_safety, link_zones
from sme_bacnet_sim.templates import expand_device

CONFIG = """
network: {ip: auto, port: 47986, virtual_network: 286, router: {device_id: 4194186}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2861
    name: LS-Dev
    private_transfer:
      - {vendor_id: 999, service_number: 1}
      - {vendor_id: 999, service_number: 2, result: 42}
    objects:
      - {type: lsp, name: Smoke1, value: quiet}
      - {type: lsp, name: Smoke2, accepted_modes: [on, off]}
      - {type: lsz, name: Zone1, zone_members: [Smoke1]}
      - {type: nc, name: NC1, instance: 1}
  - device_id: 2862
    name: Other
"""

LSP = lambda i: ObjectIdentifier(f"life-safety-point,{i}")  # noqa: E731
LSZ = ObjectIdentifier("life-safety-zone,1")
REFS = ListOf(DeviceObjectReference)


def _code(x) -> str:
    r = getattr(x, "reason", None) or getattr(getattr(x, "errorType", None), "errorCode", None) \
        or getattr(x, "errorCode", None) or x
    return str(r).replace("-", "").lower()


async def _call(coro, timeout=5.0):
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        raise
    except BaseException as e:  # error / reject / abort PDUs are raised by bacpypes3
        return e


def _events(engine, kind):
    return [e["message"] for e in engine.events if e["kind"] == kind]


def test_config_errors():
    for bad in ("{type: lsp, name: P, value: burning}", "{type: lsp, name: P, mode: armed}",
                "{type: lsp, name: P, zone_members: [X]}", "{type: av, name: A, silenced: unsilenced}",
                "{type: lsp, name: P, operation_expected: dance}"):
        with pytest.raises(Exception):
            parse_text(f"devices: [{{device_id: 1, name: D, objects: [{bad}]}}]")
    cfg = parse_text("devices: [{device_id: 1, name: D, objects: [{type: lsz, name: Z, zone_members: [Nope]}]}]")
    with pytest.raises(ValueError, match="zone member"):
        async def build():  # bacpypes3 objects need a running event loop
            link_zones("D", [build_life_safety(1, o) for o in expand_device(cfg.devices[0])])

        asyncio.run(build())
    assert parse_text("devices: [{device_id: 1, name: D, objects: [{type: lsp, name: P, value: preAlarm}]}]") \
        .devices[0].objects[0].value == "pre-alarm"


def test_ede_roundtrip():
    files = export_ede(parse_text(CONFIG))
    main = next(v for k, v in files.items() if "state" not in k.lower())
    cfg, _ = import_ede(main)
    objs = {o.name: o for o in cfg.devices[0].objects}
    assert objs["Smoke1"].type == "life-safety-point" and objs["Smoke1"].value == "quiet"
    assert objs["Zone1"].type == "life-safety-zone"


def test_bacnet_p3_services(tmp_path):
    path = tmp_path / "sim.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    asyncio.run(_flow(path))


async def _flow(path):
    ip = detect_ip()
    engine = Engine(parse_text(path.read_text(encoding="utf-8")), str(path))
    await engine.start()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194287), objectName="p3-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47987", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47986"), [286])
        iams = await client.who_is(address=Address("286:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2861]
        rt = engine.devices[2861]
        dev_objs = {o.name: o for o in rt.cfg.objects}

        # ---- Read / RPM
        assert str(await client.read_property(addr, LSP(1), "present-value")) == "quiet"
        res = await client.read_property_multiple(addr, [LSZ, ["mode", "silenced", "operation-expected",
                                                               "zone-members"]])
        vals = {str(r[1]): r[3] for r in res}
        assert str(vals["mode"]) == "on" and str(vals["silenced"]) == "unsilenced"
        assert [m.objectIdentifier[1] for m in vals["zone-members"]] == [1]

        # ---- detector state -> latched present value, zone follows its member
        engine.set_life_safety(2861, "life-safety-point:1", "alarm")
        engine.set_life_safety(2861, "life-safety-point:1", "quiet")
        await asyncio.sleep(0.3)
        assert str(await client.read_property(addr, LSP(1), "tracking-value")) == "quiet"
        assert str(await client.read_property(addr, LSP(1), "present-value")) == "alarm"
        assert str(await client.read_property(addr, LSZ, "present-value")) == "alarm"
        snap = {o["name"]: o for o in engine.snapshot()["devices"][0]["objects"]}
        assert snap["Zone1"]["life_safety"] and snap["Zone1"]["members"] == ["Smoke1"]

        # ---- writes: mode must be accepted, tracking-value read-only, present-value only out of service
        assert await _call(client.write_property(addr, LSP(1), "mode", LifeSafetyMode("test"))) is None
        assert _code(await _call(client.write_property(addr, LSP(2), "mode", LifeSafetyMode("test")))) \
            == "valueoutofrange"
        assert _code(await _call(client.write_property(addr, LSP(1), "tracking-value", LifeSafetyState("alarm")))) \
            == "writeaccessdenied"
        assert _code(await _call(client.write_property(addr, LSP(2), "present-value", LifeSafetyState("alarm")))) \
            == "writeaccessdenied"

        # ---- LifeSafetyOperation: silence / reset on the zone also act on its members
        def op(request, oid=LSZ):
            kw = dict(requestingProcessIdentifier=7, requestingSource="tester", request=request, destination=addr)
            if oid is not None:
                kw["objectIdentifier"] = oid
            return client.request(LifeSafetyOperationRequest(**kw))

        assert isinstance(await _call(op("silence")), SimpleAckPDU)
        assert str(rt.lifesafety[0].obj.silenced) == "all-silenced"
        assert isinstance(await _call(op("unsilence-audible", LSP(1))), SimpleAckPDU)
        assert str(rt.lifesafety[0].obj.silenced) == "visible-silenced"
        assert isinstance(await _call(op("reset")), SimpleAckPDU)
        assert str(await client.read_property(addr, LSP(1), "present-value")) == "quiet"
        assert str(await client.read_property(addr, LSZ, "present-value")) == "quiet"
        assert str(await client.read_property(addr, LSP(1), "silenced")) == "unsilenced"
        assert isinstance(await _call(op("silence", None)), SimpleAckPDU)  # no object: every object
        assert all(str(x.obj.silenced) == "all-silenced" for x in rt.lifesafety)
        assert _code(await _call(op("reset", ObjectIdentifier("notification-class,1")))) == "unsupportedobjecttype"
        assert _code(await _call(op("reset", LSP(9)))) == "unknownobject"
        assert any("LifeSafetyOperation reset" in t for t in _events(engine, "life-safety"))

        # ---- AddListElement / RemoveListElement on zone-members (written back to the config)
        def change(req, oid, prop, elements):
            return client.request(req(objectIdentifier=oid, propertyIdentifier=prop,
                                      listOfElements=elements, destination=addr))

        smoke = lambda i: DeviceObjectReference(objectIdentifier=LSP(i))  # noqa: E731
        r = await _call(change(AddListElementRequest, LSZ, "zone-members", AnyValue(REFS([smoke(2), smoke(1)]))))
        assert isinstance(r, SimpleAckPDU)  # Smoke1 already a member: ignored
        assert dev_objs["Zone1"].zone_members == ["Smoke1", "Smoke2"]
        r = await _call(change(RemoveListElementRequest, LSZ, "zone-members", AnyValue(REFS([smoke(1)]))))
        assert isinstance(r, SimpleAckPDU)
        assert dev_objs["Zone1"].zone_members == ["Smoke2"]
        r = await _call(change(RemoveListElementRequest, LSZ, "zone-members", AnyValue(REFS([smoke(1)]))))
        assert _code(r) == "listelementnotfound" and r.firstFailedElementNumber == 1
        r = await _call(change(AddListElementRequest, LSP(1), "present-value", AnyValue(REFS([smoke(1)]))))
        assert _code(r) == "propertyisnotalist"
        r = await _call(change(AddListElementRequest, ObjectIdentifier("analog-value,9"), "present-value",
                               AnyValue(REFS([]))))
        assert _code(r) == "unknownobject"

        # ---- notification class recipient-list: runtime recipients and config follow
        net = engine.config.network.network_number
        dest = NCRecipient(RecipientConfig(device=2862, process_id=3, confirmed=True), net).destination()
        r = await _call(change(AddListElementRequest, ObjectIdentifier("notification-class,1"), "recipient-list",
                               AnyValue(ListOf(Destination)([dest]))))
        assert isinstance(r, SimpleAckPDU)
        nc = rt.ncs[0]
        assert [(x.cfg.device, x.cfg.process_id, x.cfg.confirmed) for x in nc.recipients] == [(2862, 3, True)]
        assert dev_objs["NC1"].recipients[0].device == 2862
        r = await _call(change(RemoveListElementRequest, ObjectIdentifier("notification-class,1"), "recipient-list",
                               AnyValue(ListOf(Destination)([dest]))))
        assert isinstance(r, SimpleAckPDU) and nc.recipients == [] and dev_objs["NC1"].recipients == []

        # ---- TextMessage (confirmed / unconfirmed from a client, sent from a simulated device)
        r = await _call(client.request(ConfirmedTextMessageRequest(
            textMessageSourceDevice=("device", 4194287), messagePriority="urgent", message="fire drill at 10:00",
            destination=addr)))
        assert isinstance(r, SimpleAckPDU)
        client.request(UnconfirmedTextMessageRequest(
            textMessageSourceDevice=("device", 4194287), messagePriority="normal", message="hello sim",
            destination=addr))
        await asyncio.sleep(0.3)
        texts = _events(engine, "text-message")
        assert any("fire drill at 10:00" in t and "urgent" in t and "device 2861" in t for t in texts)
        assert any("UnconfirmedTextMessage" in t and "hello sim" in t for t in texts)
        dest = await engine.send_text_message(2861, "from 2861", "286:2", "normal", 5, confirmed=True)
        assert dest == "286:2"
        await asyncio.sleep(0.2)
        assert any("from 2861" in t and "-> device 2862" in t and "class 5" in t
                   for t in _events(engine, "text-message"))
        assert await engine.send_text_message(2861, "to all") == "*:*"
        with pytest.raises(ValueError):
            await engine.send_text_message(2861, "x", confirmed=True)  # broadcast cannot be confirmed

        # ---- PrivateTransfer
        def pt(num, params=None, cls=ConfirmedPrivateTransferRequest):
            req = cls(vendorID=999, serviceNumber=num, destination=addr)
            if params is not None:
                req.serviceParameters = params
            return req

        r = await _call(client.request(pt(1, AnyValue(CharacterString("ping")))))
        assert isinstance(r, ConfirmedPrivateTransferACK) and r.resultBlock.cast_out(CharacterString) == "ping"
        r = await _call(client.request(pt(2)))
        assert isinstance(r, ConfirmedPrivateTransferACK) and r.resultBlock.cast_out(Unsigned) == 42
        r = await _call(client.request(pt(3)))
        assert _code(r) == "optionalfunctionalitynotsupported"
        client.request(pt(4, cls=UnconfirmedPrivateTransferRequest))
        await asyncio.sleep(0.3)
        ev = _events(engine, "private-transfer")
        assert any("service 3" in t and "not supported" in t for t in ev)
        assert any("UnconfirmedPrivateTransfer" in t and "service 4" in t for t in ev)
    finally:
        client.close()
        await engine.stop()
