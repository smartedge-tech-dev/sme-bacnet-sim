"""Schedule / Calendar objects: evaluation on the simulated clock, target writes, BACnet access, validation.

Uses BACnet port 47920 / client port 47921 so it does not clash with other tests or a running simulator.
"""

import asyncio
import datetime
import time

import pytest
from bacpypes3.app import Application
from bacpypes3.basetypes import DailySchedule, TimeValue
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Enumerated, ObjectIdentifier, Time

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine, detect_ip
from sme_bacnet_sim.schedule import to_py


def _ts(day_offset: int, h: int, m: int = 0) -> float:
    """Local epoch seconds of a fixed Monday (+ day_offset days) at h:m."""
    d = datetime.date(2026, 11, 23)
    d -= datetime.timedelta(days=d.weekday())
    return time.mktime((d.year, d.month, d.day + day_offset, h, m, 0, 0, 0, -1))


WED = datetime.date.fromtimestamp(_ts(2, 12)).isoformat()

CONFIG = f"""
network: {{ip: auto, port: 47920, virtual_network: 220, router: {{device_id: 4194120}}}}
simulation: {{tick_seconds: 0.1, time_scale: 600}}
devices:
  - device_id: 2201
    name: SCH-Dev
    objects:
      - {{type: bo, name: Light, value: 0, active_text: "ON", inactive_text: "OFF"}}
      - {{type: av, name: Setpoint, value: 20, commandable: true}}
      - {{type: cal, name: Holidays, dates: ["{WED}", {{from: "2026-12-29", to: "2027-01-03"}}]}}
      - type: sch
        name: Light_Sch
        priority_for_writing: 12
        default: "OFF"
        targets: [Light]
        weekly:
          weekdays: [{{time: "08:00", value: "ON"}}, {{time: "18:00", value: "OFF"}}]
        exceptions:
          - {{calendar: Holidays, priority: 10, times: [{{time: "00:00", value: "OFF"}}]}}
      - type: sch
        name: SP_Sch
        targets: [Setpoint]
        default: 18
        weekly: {{daily: [{{time: "06:30", value: 22.5}}, {{time: "21:00", value: null}}]}}
"""

BO1 = ObjectIdentifier("binary-output,1")
SCH1 = ObjectIdentifier("schedule,1")


def _jump(engine: Engine, ts: float) -> None:
    """Move the simulated clock to ts and run one (zero-length) step."""
    engine.sim_time = ts - engine.sim_epoch
    engine.step(0)


def test_schedule_on_sim_clock():
    asyncio.run(_schedule())


async def _schedule():
    engine = Engine(parse_text(CONFIG))
    engine.sim_epoch = _ts(0, 17, 55)  # Monday 17:55 simulated
    await engine.start()
    ip = detect_ip()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194220), objectName="sch-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47921", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        rt = engine.devices[2201]
        light = rt.by_key["binary-output:1"]
        sch = rt.schedules[0]
        assert light.read() == 1 and sch.current == 1  # initial evaluation at Monday 17:55
        assert light.obj.currentCommandPriority.unsigned == 12
        assert sch.next is not None and sch.next[0] == _ts(0, 18) and sch.next[1] == 0

        # time_scale 600 (60 sim s per tick): the BO must switch off exactly when the sim clock passes 18:00
        samples = []
        for _ in range(100):
            await asyncio.sleep(0.03)
            samples.append((engine.sim_epoch + engine.sim_time, light.read()))
            if samples[-1][0] > _ts(0, 18, 5):
                break
        assert samples[-1][0] > _ts(0, 18, 5)
        assert all(v == (1 if ts < _ts(0, 18) else 0) for ts, v in samples)
        assert light.obj.currentCommandPriority.unsigned == 12  # the inactive value is commanded at 12, too
        engine.set_simulation(running=False)
        await asyncio.sleep(0.15)

        # BACnet client: weekly-schedule, present-value, priority array of the target
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47920"), [220])
        iams = await client.who_is(address=Address("220:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2201]
        ws = await client.read_property(addr, SCH1, "weekly-schedule")
        assert len(ws) == 7
        assert [(tuple(tv.time)[:2], to_py(tv.value)) for tv in ws[0].daySchedule] == [((8, 0), 1), ((18, 0), 0)]
        assert ws[5].daySchedule == [] and ws[6].daySchedule == []
        assert to_py(await client.read_property(addr, SCH1, "present-value")) == 0
        assert await client.read_property(addr, SCH1, "priority-for-writing") == 12
        refs = await client.read_property(addr, SCH1, "list-of-object-property-references")
        assert [r.objectIdentifier for r in refs] == [BO1]
        pa = await client.read_property(addr, BO1, "priority-array")
        assert pa[11].enumerated == 0 and all(pa[i].null is not None for i in range(16) if i != 11)

        # Tuesday: off before 08:00, on at 08:00 sharp
        _jump(engine, _ts(1, 7, 59))
        assert light.read() == 0
        _jump(engine, _ts(1, 8))
        assert light.read() == 1 and sch.next[0] == _ts(1, 18)

        # relinquish at the schedule priority: the BO falls back; the schedule writes again on the next transition
        await engine.relinquish(2201, "binary-output:1", 12)
        assert light.read() == 0 and light.obj.currentCommandPriority.null is not None
        _jump(engine, _ts(1, 12))
        assert light.read() == 0
        _jump(engine, _ts(1, 18))
        assert light.read() == 0 and light.obj.currentCommandPriority.unsigned == 12

        # Wednesday is in the Holidays calendar: the exception (priority 10) overrides the weekly ON
        _jump(engine, _ts(2, 12))
        assert rt.calendars[0].obj.presentValue and light.read() == 0
        assert await client.read_property(addr, ObjectIdentifier("calendar,1"), "present-value") == 1
        _jump(engine, _ts(3, 12))  # Thursday: normal weekday
        assert not rt.calendars[0].obj.presentValue and light.read() == 1

        # REAL schedule with a Null entry: back to schedule-default at 21:00
        sp = rt.by_key["analog-value:1"]
        assert sp.read() == 22.5 and sp.obj.currentCommandPriority.unsigned == 16
        _jump(engine, _ts(3, 21, 30))
        assert sp.read() == 18.0

        # a client rewrites the weekly schedule: ON all day on every day, picked up while paused
        new_week = [DailySchedule(daySchedule=[TimeValue(time=Time((0, 0, 0, 0)), value=Enumerated(1))])
                    for _ in range(7)]
        _jump(engine, _ts(5, 10))  # Saturday 10:00, default OFF
        assert light.read() == 0
        await client.write_property(addr, SCH1, "weekly-schedule", new_week)
        await asyncio.sleep(0.3)
        assert light.read() == 1
        ws = await client.read_property(addr, SCH1, "weekly-schedule")
        assert [(tuple(tv.time)[:2], to_py(tv.value)) for tv in ws[5].daySchedule] == [((0, 0), 1)]

        # snapshot rows for the UI
        snap = {o["name"]: o for o in engine.snapshot()["devices"][0]["objects"]}
        assert snap["Light_Sch"]["schedule"] and snap["Light_Sch"]["targets"] == ["Light"]
        assert snap["Light_Sch"]["value"] == "ON" and snap["Light_Sch"]["weekly"]["sat"] == [["00:00", "ON"]]
        assert snap["Light_Sch"]["exceptions"][0]["period"] == "calendar Holidays"
        assert snap["Holidays"]["calendar"] and snap["Holidays"]["dates"][0] == WED
    finally:
        client.close()
        await engine.stop()


def _prepare(text):
    async def run():
        cfg = parse_text(text)
        return Engine(cfg)._prepare(cfg)
    return asyncio.run(run())


def test_schedule_validation():
    with pytest.raises(ValueError, match=r"SCH-Dev.*Light_Sch.*target 'Nope'"):
        _prepare(CONFIG.replace("targets: [Light]", "targets: [Nope]"))
    with pytest.raises(ValueError, match=r"calendar 'Xmas' is not a calendar"):
        _prepare(CONFIG.replace("calendar: Holidays", "calendar: Xmas"))
    with pytest.raises(ValueError, match=r"value 2\.5 does not match the targets \(binary"):
        _prepare(CONFIG.replace('value: "ON"}', "value: 2.5}", 1))
    with pytest.raises(ValueError, match=r"targets mix value types"):
        _prepare(CONFIG.replace("targets: [Light]", "targets: [Light, Setpoint]"))
    with pytest.raises(ValueError, match="invalid time"):
        parse_text(CONFIG.replace('"08:00"', '"25:00"'))
    with pytest.raises(ValueError, match="exactly one of 'date' or 'calendar'"):
        parse_text(CONFIG.replace("calendar: Holidays,", f"calendar: Holidays, date: {WED},"))
    with pytest.raises(ValueError, match="priority must be 1..16"):
        parse_text(CONFIG.replace("priority: 10", "priority: 17"))
    with pytest.raises(ValueError, match="needs 'weekly' and/or 'exceptions'"):
        parse_text("devices: [{device_id: 9, name: D, objects: [{type: sch, name: S, targets: [X]}]}]")
    with pytest.raises(ValueError, match="invalid date"):
        parse_text(CONFIG.replace(f'"{WED}"', '"2026-13-01"'))
    # unquoted YAML 18:00 is a sexagesimal int; it is still read as 18:00
    rts = _prepare(CONFIG.replace('"18:00"', "18:00"))
    assert tuple(rts[2201].schedules[0].obj.weeklySchedule[0].daySchedule[1].time)[:2] == (18, 0)


def test_templates_have_schedules():
    rts = _prepare("""
devices:
  - {device_id: 1, name: L, template: lighting}
  - {device_id: 2, name: AC, template: split_ac}
  - {device_id: 3, name: AC2, template: split_ac, params: {schedule: false}}
""")
    assert [(s.cfg.name, [p.cfg.name for p in s.targets]) for s in rts[1].schedules] == [("Zone1_Schedule", ["Zone1_Cmd"])]
    assert [[p.cfg.name for p in s.targets] for s in rts[2].schedules] == [["OnOff"]]
    assert rts[3].schedules == []


# ---------------------------------------------------------------- cross-device targets, Present_Value writes,
# write-every-scheduled-action, exception date ranges / weekNDay, COV subscriptions across ReinitializeDevice

CONFIG_X = """
network: {ip: auto, port: 47926, virtual_network: 226, router: {device_id: 4194126}}
simulation: {tick_seconds: 0.1, time_scale: 1}
devices:
  - device_id: 2261
    name: SCH-A
    objects:
      - {type: bo, name: Light, value: 0}
      - type: sch
        name: Mix_Sch
        priority_for_writing: 9
        default: "OFF"
        targets: [Light, {device: SCH-B, object: Fan}, {device: 999999, object: "av:5"}]
        weekly:
          weekdays: [{time: "08:00", value: "ON"}, {time: "12:00", value: "ON"}, {time: "18:00", value: "OFF"}]
  - device_id: 2262
    name: SCH-B
    objects:
      - {type: bo, name: Fan, value: 0}
"""

SCH_X = ObjectIdentifier("schedule,1")


def test_schedule_cross_device_and_writes():
    asyncio.run(_cross())


async def _cross():
    from bacpypes3.apdu import SubscribeCOVRequest
    from bacpypes3.basetypes import CalendarEntry, DateRange, SpecialEvent, SpecialEventPeriod, WeekNDay
    from bacpypes3.primitivedata import Date, Real

    engine = Engine(parse_text(CONFIG_X))
    engine.sim_epoch = _ts(0, 7)  # Monday 07:00 simulated
    await engine.start()
    engine.set_simulation(running=False)
    ip = detect_ip()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194226), objectName="schx-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47927", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        sc = engine.devices[2261].schedules[0]
        light = engine.devices[2261].by_key["binary-output:1"]
        fan = engine.devices[2262].by_key["binary-output:1"]
        refs = sc.obj.listOfObjectPropertyReferences
        assert refs[0].deviceIdentifier is None
        assert refs[1].deviceIdentifier == ObjectIdentifier("device,2262")
        assert refs[2].deviceIdentifier == ObjectIdentifier("device,999999")
        assert refs[2].objectIdentifier == ObjectIdentifier("analog-value,5")
        assert sc.labels == ["Light", "SCH-B/Fan", "device 999999 analog-value:5 (external)"]
        assert any("999999" in e["text"] and "not written" in e["text"] for e in engine.events)
        assert light.read() == 0 and fan.read() == 0
        assert fan.obj.currentCommandPriority.unsigned == 9  # cross-device write at priority_for_writing

        _jump(engine, _ts(0, 8))
        assert light.read() == 1 and fan.read() == 1

        # client write of the schedule's own Present_Value: forwarded to all targets, holds until the next action
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47926"), [226])
        iams = await client.who_is(address=Address("226:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2261]
        _jump(engine, _ts(0, 9))
        await client.write_property(addr, SCH_X, "present-value", Enumerated(0))
        assert light.read() == 0 and fan.read() == 0 and fan.obj.currentCommandPriority.unsigned == 9
        assert to_py(await client.read_property(addr, SCH_X, "present-value")) == 0
        with pytest.raises(BaseException, match="invalid-data-type"):
            await client.write_property(addr, SCH_X, "present-value", Real(1.5))  # wrong datatype
        _jump(engine, _ts(0, 11))
        assert light.read() == 0 and fan.read() == 0  # no write between scheduled actions

        # the 12:00 entry (value unchanged: ON) fires and writes again
        _jump(engine, _ts(0, 12))
        assert light.read() == 1 and fan.read() == 1
        await engine.relinquish(2262, "binary-output:1", 9)  # operator change
        _jump(engine, _ts(0, 13))
        assert fan.read() == 0  # not overwritten each tick

        # COV subscriptions survive ReinitializeDevice; the schedule re-commands the relinquished slot
        addr_b = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2262]
        await client.request(SubscribeCOVRequest(
            subscriberProcessIdentifier=7, monitoredObjectIdentifier=ObjectIdentifier("binary-output,1"),
            issueConfirmedNotifications=False, lifetime=300, destination=addr_b))
        dets = engine.devices[2262].app._cov_detections
        assert len(dets[ObjectIdentifier("binary-output,1")].cov_subscriptions) == 1
        await engine.reinitialize(2262, False, "test")
        assert len(dets[ObjectIdentifier("binary-output,1")].cov_subscriptions) == 1
        assert fan.read() == 1 and fan.obj.currentCommandPriority.unsigned == 9
        await client.request(SubscribeCOVRequest(  # cancel
            subscriberProcessIdentifier=7, monitoredObjectIdentifier=ObjectIdentifier("binary-output,1"),
            destination=addr_b))
        assert ObjectIdentifier("binary-output,1") not in dets  # cancelled (avoids a pending subscription at shutdown)

        # Exception_Schedule written over BACnet: weekNDay (every Tuesday) and a date range (this Wednesday)
        wed = datetime.date.fromtimestamp(_ts(2, 12))
        off = [TimeValue(time=Time((0, 0, 0, 0)), value=Enumerated(0))]
        await client.write_property(addr, SCH_X, "exception-schedule", [
            SpecialEvent(period=SpecialEventPeriod(calendarEntry=CalendarEntry(weeknday=WeekNDay(bytes([255, 255, 2])))),
                         eventPriority=4, listOfTimeValues=off),
            SpecialEvent(period=SpecialEventPeriod(calendarEntry=CalendarEntry(dateRange=DateRange(
                startDate=Date((wed.year - 1900, wed.month, wed.day, 255)),
                endDate=Date((wed.year - 1900, wed.month, wed.day, 255))))), eventPriority=4, listOfTimeValues=off),
        ])
        for day, expect in ((1, 0), (2, 0), (3, 1)):  # Tuesday, Wednesday off; Thursday normal
            _jump(engine, _ts(day, 10))
            assert light.read() == expect and fan.read() == expect, day
        periods = [e["period"] for e in sc.exception_table()]
        assert periods == ["weeknday */*/2", f"{wed.isoformat()}..{wed.isoformat()}"]
    finally:
        client.close()
        await engine.stop()


def test_schedule_exception_ranges_weeknday():
    from bacpypes3.primitivedata import Date
    text = """
devices:
  - device_id: 1
    name: D
    objects:
      - {type: av, name: SP, commandable: true}
      - type: sch
        name: S
        default: 10
        targets: [SP]
        exceptions:
          - {date: {from: "2026-12-24", to: "2026-12-26"}, priority: 3, times: [{time: "00:00", value: 30}]}
          - {date: {weeknday: ["*", 6, 5]}, priority: 5, times: [{time: "00:00", value: 40}]}  # last Friday
          - {date: {weeknday: [14, 1, "*"]}, priority: 6, times: [{time: "00:00", value: 50}]}  # 1st week, even months
          - {date: "*-*-15", priority: 7, times: [{time: "00:00", value: 60}]}
"""
    sc = _prepare(text)[1].schedules[0]

    def at(iso):
        d = datetime.date.fromisoformat(iso)
        return to_py(sc.obj.eval(Date((d.year - 1900, d.month, d.day, d.isoweekday())), Time((12, 0, 0, 0)))[0])

    assert at("2026-12-25") == 30  # range (priority 3) beats the last-Friday weekNDay
    assert at("2026-11-27") == 40 and at("2027-01-29") == 40  # last Friday of the month (week 6)
    assert at("2026-11-20") == 10
    assert at("2026-12-03") == 50 and at("2026-11-03") == 10  # even months only
    assert at("2026-11-15") == 60
    with pytest.raises(ValueError, match="invalid weeknday"):
        parse_text(text.replace('[14, 1, "*"]', '[15, 1, "*"]'))
    # target validation
    with pytest.raises(ValueError, match=r"targets\[0\]"):
        parse_text(text.replace("targets: [SP]", "targets: [{dev: 2, object: X}]"))
    with pytest.raises(ValueError, match="not a device of this simulator"):
        _prepare(text.replace("targets: [SP]", "targets: [{device: Nope, object: X}]"))
    with pytest.raises(ValueError, match="not a device of this simulator"):
        _prepare(text.replace("targets: [SP]", "targets: [{device: 77, object: X}]"))
