"""Client changes of Calendar date-list, Schedule list-of-object-property-references / weekly-schedule /
exception-schedule / schedule-default and template NC recipient-list are kept in the config; the event log is not duplicated after a reload; BSD ifconfig masks.

Uses BACnet port 47990 / client port 47991 so it does not clash with other tests or a running simulator.
"""

import asyncio

from bacpypes3.apdu import AddListElementRequest, RemoveListElementRequest, SimpleAckPDU
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    CalendarEntry, DailySchedule, DateRange, Destination, DeviceObjectPropertyReference, SpecialEvent,
    SpecialEventPeriod, TimeValue,
)
from bacpypes3.constructeddata import Any as AnyValue, ListOf
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Date, Enumerated, Null, ObjectIdentifier, Real, Time

from sme_bacnet_sim.alarm import NCRecipient
from sme_bacnet_sim.config import RecipientConfig, SimConfig, parse_text
from sme_bacnet_sim.engine import Engine, _ifconfig_prefix_len, detect_ip
from sme_bacnet_sim.schedule import schedule_to_cfg
from sme_bacnet_sim.web import PasteReq, create_app

CONFIG = """
network: {ip: auto, port: 47990, virtual_network: 290, router: {device_id: 4194190}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2901
    name: WB-Dev
    objects:
      - {type: bo, name: Light, value: 0}
      - {type: bo, name: Fan, value: 0}
      - {type: av, name: SP, value: 20}
      - {type: ai, name: Temp, value: 21}
      - {type: cal, name: Holidays, dates: ["2026-12-25"]}
      - {type: sch, name: Light_Sch, priority_for_writing: 12, default: 0, targets: [Light],
         weekly: {daily: [{time: "08:00", value: 1}]}}
  - device_id: 2902
    name: AHU
    template: ahu
    objects:
      - {type: bo, name: Pump, value: 0}
  - {device_id: 2903, name: AC, template: split_ac}
"""

CAL = ObjectIdentifier("calendar,1")
SCH = ObjectIdentifier("schedule,1")
ENTRIES = ListOf(CalendarEntry)
REFS = ListOf(DeviceObjectPropertyReference)


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


def _tv(h: int, m: int, v, s: int = 0) -> TimeValue:
    return TimeValue(time=Time((h, m, s, 0)), value=Null(()) if v is None else Enumerated(v))


def _ref(oid: str, device=None) -> DeviceObjectPropertyReference:
    kw = {"deviceIdentifier": ("device", device)} if device is not None else {}
    return DeviceObjectPropertyReference(objectIdentifier=ObjectIdentifier(oid), propertyIdentifier="present-value",
                                         **kw)


def test_list_properties_written_back():
    asyncio.run(_writeback())


async def _writeback():
    engine = Engine(parse_text(CONFIG))
    await engine.start()
    ip = detect_ip()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194291), objectName="wb-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47991", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47990"), [290])
        iams = await client.who_is(address=Address("290:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}
        a1, a2 = addr[2901], addr[2902]
        rt, rt2 = engine.devices[2901], engine.devices[2902]
        own = {o.name: o for o in rt.cfg.objects}

        def change(req, a, oid, prop, elements):
            return client.request(req(objectIdentifier=oid, propertyIdentifier=prop, listOfElements=elements,
                                      destination=a))

        # ---- calendar date-list: AddListElement / RemoveListElement / WriteProperty -> config dates
        rng = CalendarEntry(dateRange=DateRange(startDate=Date((126, 12, 29, 255)), endDate=Date((127, 1, 3, 255))))
        wk = CalendarEntry(weeknday=bytes([12, 255, 7]))
        r = await _call(change(AddListElementRequest, a1, CAL, "date-list", AnyValue(ENTRIES([rng, wk]))))
        assert isinstance(r, SimpleAckPDU)
        want = ["2026-12-25", {"from": "2026-12-29", "to": "2027-01-03"}, {"weeknday": [12, "*", 7]}]
        assert own["Holidays"].dates == want
        xmas = CalendarEntry(date=Date((126, 12, 25, 255)))
        r = await _call(change(RemoveListElementRequest, a1, CAL, "date-list", AnyValue(ENTRIES([xmas]))))
        assert isinstance(r, SimpleAckPDU) and own["Holidays"].dates == want[1:]
        r = await _call(client.write_property(a1, CAL, "date-list", ENTRIES([CalendarEntry(date=Date((255, 1, 1, 255)))])))
        assert r is None and own["Holidays"].dates == ["*-01-01"]

        # ---- schedule weekly-schedule / exception-schedule / schedule-default -> config weekly / exceptions / default
        sc = rt.schedules[0]
        light = rt.by_key["binary-output:1"]
        v = 1 - light.read()  # the opposite of what the schedule writes now
        r = await _call(client.write_property(a1, SCH, "weekly-schedule",
                                              [DailySchedule(daySchedule=[_tv(0, 0, v)]) for _ in range(7)]))
        assert r is None and own["Light_Sch"].weekly == {"daily": [{"time": "00:00", "value": v}]}
        await asyncio.sleep(0.3)
        assert light.read() == v  # runs at once on the new content (simulation paused)
        week = [DailySchedule(daySchedule=[_tv(17, 30, 0, 15), _tv(7, 0, 1)][::-1]) for _ in range(5)]             + [DailySchedule(daySchedule=[]) for _ in range(2)]
        r = await _call(client.write_property(a1, SCH, "weekly-schedule", week))
        want_week = {"weekdays": [{"time": "07:00", "value": 1}, {"time": "17:30:15", "value": 0}], "weekend": []}
        assert r is None and own["Light_Sch"].weekly == want_week
        rng = SpecialEventPeriod(calendarEntry=CalendarEntry(dateRange=DateRange(
            startDate=Date((126, 8, 10, 255)), endDate=Date((126, 8, 14, 255)))))
        exc = [SpecialEvent(period=SpecialEventPeriod(calendarReference=CAL), eventPriority=5,
                            listOfTimeValues=[_tv(0, 0, 0)]),
               SpecialEvent(period=rng, eventPriority=16, listOfTimeValues=[_tv(6, 0, 1), _tv(7, 0, None)])]
        r = await _call(client.write_property(a1, SCH, "exception-schedule", exc))
        want_exc = [{"calendar": "Holidays", "priority": 5, "times": [{"time": "00:00", "value": 0}]},
                    {"date": {"from": "2026-08-10", "to": "2026-08-14"}, "priority": 16,
                     "times": [{"time": "06:00", "value": 1}, {"time": "07:00", "value": None}]}]
        assert r is None and own["Light_Sch"].exceptions == want_exc
        r = await _call(change(AddListElementRequest, a1, SCH, "exception-schedule", AnyValue(ListOf(SpecialEvent)(exc))))
        assert _code(r) == "propertyisnotalist"  # an array, not a list
        r = await _call(client.write_property(a1, SCH, "schedule-default", Enumerated(1)))
        assert r is None and own["Light_Sch"].default == 1
        # the wrong datatype: accepted, configuration-error, not kept; fixed by the next write
        r = await _call(client.write_property(a1, SCH, "schedule-default", Real(2.5)))
        assert r is None and str(sc.obj.reliability) == "configuration-error" and own["Light_Sch"].default == 1
        r = await _call(client.write_property(a1, SCH, "schedule-default", Enumerated(0)))
        assert r is None and str(sc.obj.reliability) == "no-fault-detected" and own["Light_Sch"].default == 0
        # a calendar reference the config cannot name (no such calendar here) is not kept
        await sc.obj.write_property("exceptionSchedule", [SpecialEvent(
            period=SpecialEventPeriod(calendarReference=ObjectIdentifier("calendar,99")), eventPriority=1,
            listOfTimeValues=[_tv(0, 0, 1)])])
        engine.alarm_written(2901, [SCH])
        assert own["Light_Sch"].exceptions == want_exc
        await sc.obj.write_property("exceptionSchedule", exc)
        engine.alarm_written(2901, [SCH])
        # a schedule from a template: kept as an override entry that is a valid schedule on its own
        rt3 = engine.devices[2903]
        sc3 = rt3.schedules[0]
        assert not any(o.name == sc3.cfg.name for o in rt3.cfg.objects)
        sch3 = ObjectIdentifier(f"schedule,{sc3.cfg.instance}")
        r = await _call(client.write_property(addr[2903], sch3, "schedule-default", Enumerated(1)))
        assert r is None
        ov = next(o for o in rt3.cfg.objects if o.name == sc3.cfg.name)
        assert ov.default == 1 and ov.weekly == sc3.cfg.weekly
        r = await _call(client.write_property(addr[2903], sch3, "weekly-schedule", week))
        assert r is None and ov.weekly == want_week
        want = {"weekly": want_week, "exceptions": want_exc, "default": 0}
        want3 = {"weekly": want_week, "exceptions": [], "default": 1}

        # ---- schedule list-of-object-property-references -> targets written by the schedule + config
        pump = next(p for p in rt2.points if p.cfg.name == "Pump")
        r = await _call(client.write_property(a1, SCH, "list-of-object-property-references",
                                              REFS([_ref("binary-output,1"), _ref("binary-output,2"),
                                                    _ref(f"binary-output,{pump.cfg.instance}", 2902), _ref("binary-output,3", 9999)])))
        assert r is None
        assert sc.targets == [rt.by_key["binary-output:1"], rt.by_key["binary-output:2"], pump]
        assert own["Light_Sch"].targets == ["Light", "Fan", {"device": 2902, "object": "Pump"},
                                            {"device": 9999, "object": "binary-output:3"}]
        sc.write_targets(1)
        assert rt.by_key["binary-output:2"].obj.priorityArray[11].enumerated == 1 and pump.read() == 1
        r = await _call(change(RemoveListElementRequest, a1, SCH, "list-of-object-property-references",
                               AnyValue(REFS([_ref("binary-output,1")]))))
        assert isinstance(r, SimpleAckPDU) and own["Light_Sch"].targets[0] == "Fan"
        # an input / a different value kind / a missing object is rejected and changes nothing
        for bad in ("analog-input,1", "analog-value,1", "binary-output,9"):
            r = await _call(change(AddListElementRequest, a1, SCH, "list-of-object-property-references",
                                   AnyValue(REFS([_ref(bad)]))))
            assert _code(r) == "valueoutofrange", bad
            r = await _call(client.write_property(a1, SCH, "list-of-object-property-references", REFS([_ref(bad)])))
            assert _code(r) == "valueoutofrange", bad
        assert len(sc.targets) == 2 and len(sc.obj.listOfObjectPropertyReferences) == 3
        # bypassing the pre-check (as WritePropertyMultiple does) restores the configured references
        await sc.obj.write_property("listOfObjectPropertyReferences", REFS([_ref("analog-input,1")]))
        engine.alarm_written(2901, [SCH])
        assert len(sc.obj.listOfObjectPropertyReferences) == 3 and len(sc.targets) == 2

        # ---- notification class from a template: recipient-list kept as an override entry
        nc = rt2.ncs[0]
        assert not any(o.name == nc.cfg.name for o in rt2.cfg.objects)
        dest = NCRecipient(RecipientConfig(device=2901, process_id=5), 290).destination()
        r = await _call(change(AddListElementRequest, a2, ObjectIdentifier(f"notification-class,{nc.number}"),
                               "recipient-list", AnyValue(ListOf(Destination)([dest]))))
        assert isinstance(r, SimpleAckPDU)
        override = next(o for o in rt2.cfg.objects if o.name == nc.cfg.name)
        assert [x.device for x in override.recipients] == [2901]

        # ---- the saved config reproduces all of it
        cfg = SimConfig.model_validate(engine.config.model_dump(exclude_none=True))
        runtimes = engine._prepare(cfg)
        assert [p.cfg.name for p in runtimes[2901].schedules[0].targets] == ["Fan", "Pump"]
        assert runtimes[2901].calendars[0].cfg.dates == ["*-01-01"]
        assert [r.cfg.device for r in runtimes[2902].ncs[0].recipients] == [2901]
        assert schedule_to_cfg(runtimes[2901].schedules[0].obj, runtimes[2901].calendars) == want
        assert schedule_to_cfg(runtimes[2903].schedules[0].obj, runtimes[2903].calendars) == want3
    finally:
        client.close()
        await engine.stop()


class _Sock:
    def __init__(self):
        self.msgs = []

    async def accept(self):
        pass

    async def send_json(self, m):
        self.msgs.append(m)

    async def receive(self):  # the client never sends; the common /ws reads until disconnect
        await asyncio.Event().wait()


def test_paste_logged_once():
    asyncio.run(_paste_once())


def _routes(app):
    """All routes, including those of included routers (FastAPI >= 0.16x nests them in ``_IncludedRouter``)."""
    for r in app.routes:
        sub = getattr(r, "original_router", None)
        yield from (sub.routes if sub is not None else [r])


async def _paste_once():
    engine = Engine(parse_text(CONFIG))
    app = create_app(engine)
    ws = next(r.endpoint for r in _routes(app) if getattr(r, "path", None) == "/ws")
    paste = next(r.endpoint for r in _routes(app) if getattr(r, "path", None) == "/api/devices/{device_id}/objects/paste")
    await engine.start()
    sock = _Sock()
    task = asyncio.create_task(ws(sock))
    try:
        await asyncio.sleep(0.2)
        await paste(2901, PasteReq(objects=[{"type": "av", "name": "Copy1", "value": 1}]))
        engine.log_event("test", "marker")
        for _ in range(50):
            await asyncio.sleep(0.05)
            if any(m["type"] == "log" and m["event"]["message"] == "marker" for m in sock.msgs):
                break
        # the UI clears the log on every snapshot and appends live log messages
        shown = []
        for m in sock.msgs:
            if m["type"] == "snapshot":
                shown = [e["message"] for e in m["data"]["events"]]
            elif m["type"] == "log":
                shown.append(m["event"]["message"])
        assert "marker" in shown
        assert sum("pasted Copy1" in t for t in shown) == 1, shown
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.stop()


def test_ifconfig_prefix():
    out = ("en0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n"
           "\tinet6 fe80::1%en0 prefixlen 64 scopeid 0x4\n"
           "\tinet 192.168.10.23 netmask 0xffff0000 broadcast 192.168.255.255\n"
           "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n"
           "utun0: flags=8051<UP> mtu 1380\n\tinet 10.8.0.2 --> 10.8.0.1 netmask 0xffffffff\n"
           "em0: flags=8843<UP> metric 0 mtu 1500\n\tinet 172.17.0.9 netmask 255.255.240.0 broadcast 172.17.15.255\n")
    assert _ifconfig_prefix_len(out, "192.168.10.23") == 16
    assert _ifconfig_prefix_len(out, "127.0.0.1") == 8
    assert _ifconfig_prefix_len(out, "10.8.0.2") == 32
    assert _ifconfig_prefix_len(out, "172.17.0.9") == 20
    assert _ifconfig_prefix_len(out, "10.0.0.1") is None
