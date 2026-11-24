"""BACnet Schedule and Calendar objects evaluated on the simulated clock.

Clock source and evaluation
---------------------------
bacpypes3 0.1.0's local ``ScheduleObject`` interprets itself against the device
object's ``localDate`` / ``localTime`` (always the wall clock) and re-arms with
``asyncio`` ``call_later`` in wall seconds, so ``simulation.time_scale`` would
have no effect.  Its ``present_value_changed`` hook also calls the targets'
``write_property`` coroutine without awaiting it, so the writes never happen.

We therefore keep bacpypes3's ScheduleObject (properties, datatype handling,
write monitors) and its evaluation algorithm (weekly schedule, exception
schedule with event priorities, calendar references, effective period; ASHRAE
135 clause 12.24) -- ``eval`` is re-stated in :class:`SimScheduleObject` only to
fix NULL entries -- but disable its wall-clock interpreter.  The engine calls :meth:`Schedule.evaluate` from ``step()`` with
the simulated clock (``sim_epoch + sim_time``, local time).  When the scheduled
value changes, or a time entry of the weekly / exception schedule fires (even
with an unchanged value, so a scheduled action overrides operator changes), the
schedule's Present_Value is updated and the value is written to each target's
priority array at ``priority_for_writing`` (or straight to Present_Value for
non-commandable value objects), so relinquish from a client works as usual.
A client write to the schedule's own Present_Value is forwarded to the targets
the same way and holds until the next scheduled action.

Targets may live in other simulated devices (List_Of_Object_Property_References
entries with a deviceIdentifier); they are written directly into that device's
object.  References to devices outside the simulator are listed in the property
but never written (no network writes).

Client writes to Weekly_Schedule / Exception_Schedule / Schedule_Default are
accepted (bacpypes3 local objects are writable) and mark the schedule dirty; it
is re-evaluated on the next tick.  Values of the wrong datatype put the object
into Reliability = configuration-error and evaluation stops until fixed.

Outside the Effective_Period the schedule keeps its last Present_Value and
writes nothing.

bacpypes3 has no local Calendar object, so :class:`SimCalendarObject` adds one;
its Present_Value is recomputed from Date_List on the simulated date.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bacpypes3.basetypes import (
    CalendarEntry, DailySchedule, DateRange, DeviceObjectPropertyReference, PriorityValue, Reliability,
    SpecialEvent, SpecialEventPeriod, TimeValue, WeekNDay,
)
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.errors import ExecutionError
from bacpypes3.local.object import Object as _LocalObject
from bacpypes3.local.schedule import ScheduleObject as _ScheduleObject, date_in_calendar_entry, match_date_range
from bacpypes3.object import CalendarObject as _CalendarObject
from bacpypes3.primitivedata import Date, Enumerated, Null, ObjectIdentifier, Real, Time, Unsigned

from .config import (
    ANALOG_TYPES, BINARY_TYPES, CALENDAR, INPUT_TYPES, OBJECT_TYPE_ALIASES, SCHEDULE, WEEKDAYS, WILDCARD,
    parse_calendar_entry, parse_date, parse_times, parse_weekly,
)

ANY_DATE = (WILDCARD, WILDCARD, WILDCARD, WILDCARD)
DATATYPES = {"analog": Real, "binary": Enumerated, "multistate": Unsigned}
_ON = {"1", "true", "on", "active"}
_OFF = {"0", "false", "off", "inactive"}
_UNSET = object()


def _atom(v: Any) -> Any:
    return v.get_value() if isinstance(v, AnyAtomic) else v


def sim_date_time(ts: float) -> Tuple[Date, Time]:
    lt = time.localtime(ts)
    return (Date((lt.tm_year - 1900, lt.tm_mon, lt.tm_mday, lt.tm_wday + 1)),
            Time((lt.tm_hour, lt.tm_min, lt.tm_sec, int((ts % 1) * 100))))


def to_py(v: Any) -> Any:
    """AnyAtomic / Atomic schedule value -> plain Python (None for Null)."""
    if isinstance(v, AnyAtomic):
        v = v.get_value()
    if v is None or isinstance(v, Null):
        return None
    if isinstance(v, Real):
        return float(v)
    return int(v)


def fmt_hms(t: Any) -> str:
    h, m, s = tuple(t)[:3]
    return f"{h:02d}:{m:02d}" + (f":{s:02d}" if s else "")


def fmt_date(d: Any) -> str:
    y, m, dd = tuple(d)[:3]
    return "-".join("*" if x == WILDCARD else (str(x + 1900) if i == 0 else f"{x:02d}")
                    for i, x in enumerate((y, m, dd)))


def _entry(e: Tuple) -> CalendarEntry:
    if e[0] == "date":
        return CalendarEntry(date=Date(e[1] + (WILDCARD,)))
    if e[0] == "range":
        return CalendarEntry(dateRange=DateRange(startDate=Date(e[1] + (WILDCARD,)), endDate=Date(e[2] + (WILDCARD,))))
    return CalendarEntry(weeknday=WeekNDay(bytes(e[1])))


def fmt_entry(ce: CalendarEntry) -> str:
    if ce.date is not None:
        return fmt_date(ce.date)
    if ce.dateRange is not None:
        return f"{fmt_date(ce.dateRange.startDate)}..{fmt_date(ce.dateRange.endDate)}"
    m, w, d = tuple(ce.weeknday)
    return "weeknday " + "/".join("*" if x == WILDCARD else str(x) for x in (m, w, d))


# --------------------------------------------------------------------------- BACnet objects


class SimScheduleObject(_ScheduleObject):
    """bacpypes3 ScheduleObject with the wall-clock interpreter and target writes disabled (the engine drives it)."""

    def __init__(self, datatype: type, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._datatype = datatype
        self._dirty = True
        self._internal = False  # True while the engine sets Present_Value itself
        self._pv_hook: Any = None  # Schedule.pv_written, called on a client write of Present_Value
        self._property_monitors["scheduleDefault"].append(self.schedule_changed)
        self.check_reliability()

    def eval(self, edate: Date, etime: Time) -> Optional[Tuple[Any, Any]]:  # type: ignore[override]
        """Same algorithm as bacpypes3's ``ScheduleObject.eval`` with NULL handling fixed.

        bacpypes3 tests ``isinstance(time_value.value, Null)`` but the values are ``AnyAtomic`` wrappers, so a
        NULL entry was returned as the scheduled value.  Here a NULL weekly entry reverts to Schedule_Default
        and a NULL exception entry relinquishes that special event (clause 12.24.4 / 12.24.8).
        Returns (Atomic value, next transition time today or (24, 0, 0, 0), time of the latest entry today at or
        before ``etime`` in the evaluated lists or None), or None outside the effective period.
        """
        if not match_date_range(edate, self.effectivePeriod):
            return None
        now = tuple(etime)
        earliest = (24, 0, 0, 0)
        latest: Any = None

        def scan(time_values: Any) -> Any:
            nonlocal earliest, latest
            value = None
            for tv in time_values or []:
                if tuple(tv.time) <= now:
                    latest = max(latest or tuple(tv.time), tuple(tv.time))
                    v = _atom(tv.value)
                    value = None if isinstance(v, Null) else v
                else:
                    earliest = min(earliest, tuple(tv.time))
                    break
            return value

        best: Optional[Tuple[int, Any]] = None
        for se in self.exceptionSchedule or []:
            if not self._in_period(edate, se.period):
                continue
            value = scan(se.listOfTimeValues)
            if value is not None and (best is None or int(se.eventPriority) < best[0]):
                best = (int(se.eventPriority), value)
        if best is not None:
            return best[1], earliest, latest
        value = scan(self.weeklySchedule[edate[3] - 1].daySchedule) if self.weeklySchedule else None
        return (value if value is not None else _atom(self.scheduleDefault)), earliest, latest

    def _in_period(self, edate: Date, period: Any) -> bool:
        if period.calendarEntry is not None:
            return date_in_calendar_entry(edate, period.calendarEntry)
        cal = self._app.get_object_id(period.calendarReference) if self._app else None
        if cal is None:
            raise RuntimeError("invalid calendar object reference")
        return any(date_in_calendar_entry(edate, e) for e in cal.dateList or [])

    def interpret_schedule(self) -> None:
        pass  # evaluation runs on the simulated clock, see Schedule.evaluate

    async def write_property(self, attr: Any, value: Any, index: Any = None, priority: Any = None) -> None:
        """Reject client writes of Present_Value that do not match the schedule datatype."""
        if str(attr).replace("-", "").lower() in ("presentvalue", "85") and \
                not isinstance(_atom(value), self._datatype):
            raise ExecutionError(errorClass="property", errorCode="invalidDataType")
        await super().write_property(attr, value, index, priority)

    def set_present_value(self, value: Any) -> None:
        """Engine-side update of Present_Value (not forwarded as a client write)."""
        self._internal = True
        try:
            self.presentValue = _atom(value)
        finally:
            self._internal = False

    def present_value_changed(self, old_value: Any, new_value: Any) -> None:
        # scheduled values are written by Schedule.evaluate; a client write is forwarded to the targets here
        if not self._internal and self._pv_hook is not None:
            self._pv_hook(new_value)

    def schedule_changed(self, old_value: Any = None, new_value: Any = None) -> None:
        self._dirty = True

    def check_reliability(self, old_value: Any = None, new_value: Any = None) -> None:
        """Every scheduled value must be Null or the schedule datatype, times must be specific."""
        ok = True
        try:
            values = [self.scheduleDefault]
            for ds in self.weeklySchedule or []:
                for tv in ds.daySchedule or []:
                    ok = ok and WILDCARD not in tuple(tv.time)[:3]
                    values.append(tv.value)
            for se in self.exceptionSchedule or []:
                values += [tv.value for tv in se.listOfTimeValues or []]
            atoms = [v.get_value() if isinstance(v, AnyAtomic) else v for v in values]
            ok = ok and not isinstance(atoms[0], Null) and all(isinstance(a, (Null, self._datatype)) for a in atoms)
        except Exception:
            ok = False
        self.reliability = Reliability.noFaultDetected if ok else Reliability.configurationError
        self._dirty = True


class SimCalendarObject(_LocalObject, _CalendarObject):
    """Local Calendar object (bacpypes3 0.1.0 only defines the base class)."""

    async def _post_init(self) -> None:
        pass  # Calendar has no Notification_Class to link

    def evaluate(self, ts: float) -> bool:
        d, _ = sim_date_time(ts)
        value = any(date_in_calendar_entry(d, e) for e in self.dateList or [])
        if bool(self.presentValue) != value:
            self.presentValue = value
            return True
        return False


# --------------------------------------------------------------------------- runtime


@dataclass
class Calendar:
    device_id: int
    cfg: Any  # ObjectConfig
    obj: SimCalendarObject

    @property
    def key(self) -> str:
        return f"{CALENDAR}:{self.cfg.instance}"

    def status(self) -> Dict[str, Any]:
        return {"value": bool(self.obj.presentValue), "dates": [fmt_entry(e) for e in self.obj.dateList or []]}


@dataclass
class Schedule:
    device_id: int
    cfg: Any  # ObjectConfig
    obj: SimScheduleObject
    targets: List[Any]  # engine.Point, possibly of other simulated devices
    kind: str  # analog | binary | multistate
    priority: int
    labels: List[str] = field(default_factory=list)  # display names of the targets and external references
    external: List[str] = field(default_factory=list)  # references to devices outside the simulator, never written
    current: Any = _UNSET  # Python value of Present_Value (scheduled or written by a client)
    scheduled: Any = _UNSET  # Python value last computed by the schedule
    next: Optional[Tuple[float, Any]] = None  # (sim epoch s, value) of the next change
    _next_key: Any = field(default=None, repr=False)
    _last_ts: Optional[float] = field(default=None, repr=False)  # sim epoch of the previous evaluation

    def __post_init__(self) -> None:
        self.obj._pv_hook = self.pv_written

    @property
    def key(self) -> str:
        return f"{SCHEDULE}:{self.cfg.instance}"

    def _eval(self, ts: float) -> Optional[Tuple[Any, Any]]:
        d, t = sim_date_time(ts)
        return self.obj.eval(d, t)

    def write_targets(self, value: Any) -> None:
        """Write a Python value to every target at the schedule's priority (None writes nothing)."""
        if value is None:
            return
        for p in self.targets:
            v = p.coerce(value)
            if p.commandable:
                p.obj.priorityArray[self.priority - 1] = PriorityValue(p.typed(v))
            else:
                p.obj.presentValue = v

    def pv_written(self, new_value: Any) -> None:
        """A client wrote Present_Value: forward it; it holds until the next scheduled action."""
        self.current = to_py(new_value)
        self.write_targets(self.current)

    def evaluate(self, ts: float) -> bool:
        """Re-evaluate at sim epoch ``ts``; write targets when the value changed or a time entry fired since the
        previous evaluation (write-every-scheduled-action).  Returns True on a change of the scheduled value."""
        obj = self.obj
        if obj.reliability != Reliability.noFaultDetected or obj.outOfService:
            self.next = None
            return False
        try:
            res = self._eval(ts)
        except Exception:  # e.g. a calendar reference deleted by a client
            obj.reliability = Reliability.configurationError
            return False
        dirty, obj._dirty = obj._dirty, False
        if res is None:  # outside the effective period: keep the last value, no writes
            self.next = None
            return False
        value = to_py(res[0])
        changed = value != self.scheduled
        fired = False
        if res[2] is not None and self._last_ts is not None:  # a time entry at or before now, after the last eval?
            lt = time.localtime(ts)
            h, m, s = res[2][:3]
            fired = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, s, 0, 0, -1)) > self._last_ts
        self._last_ts = ts
        if changed or fired:
            self.scheduled = self.current = value
            obj.set_present_value(res[0])
            self.write_targets(value)
        key = int(ts // 60)
        if changed or dirty or key != self._next_key or (self.next and ts >= self.next[0]):
            self._next_key = key
            self.next = self._find_next(ts, value)
        return changed

    def _find_next(self, ts: float, value: Any) -> Optional[Tuple[float, Any]]:
        """First time after ``ts`` (within ~8 days) at which the scheduled value differs from ``value``."""
        t = ts
        for _ in range(64):
            res = self._eval(t)
            if res is None:
                return None
            lt = time.localtime(t)
            h, m, s = tuple(res[1])[:3]
            nxt = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, s, 0, 0, -1))  # 24:00 -> next midnight
            if nxt <= t:
                nxt = t + 1
            res2 = self._eval(nxt)
            if res2 is None:
                return None
            if to_py(res2[0]) != value:
                return nxt, to_py(res2[0])
            if nxt - ts > 8 * 86400:
                return None
            t = nxt
        return None

    def text(self, v: Any) -> Any:
        """Display text of a scheduled value using the first target's state texts."""
        if v is None:
            return None
        p = self.targets[0] if self.targets else None
        if self.kind == "binary":
            on = bool(v)
            return ((p.cfg.active_text if p else None) or "active") if on else \
                ((p.cfg.inactive_text if p else None) or "inactive")
        if self.kind == "multistate" and p and p.cfg.states and 1 <= int(v) <= len(p.cfg.states):
            return p.cfg.states[int(v) - 1]
        return v

    def status(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"value": self.text(None if self.current is _UNSET else self.current),
                             "next": [self.next[0], self.text(self.next[1])] if self.next else None}
        if self.obj.reliability != Reliability.noFaultDetected:
            d["error"] = f"reliability {self.obj.reliability}"
        # tables are read from the BACnet properties so client writes show up in the UI
        try:
            d.update(default=self.text(to_py(self.obj.scheduleDefault)), weekly=self.weekly_table(),
                     exceptions=self.exception_table())
        except Exception as e:  # a malformed client write must not break the UI scan
            d.setdefault("error", f"{type(e).__name__}: {e}")
        return d

    def weekly_table(self) -> Dict[str, List[List[Any]]]:
        out: Dict[str, List[List[Any]]] = {}
        for day, ds in zip(WEEKDAYS, self.obj.weeklySchedule or []):
            out[day] = [[fmt_hms(tv.time), self.text(to_py(tv.value))] for tv in ds.daySchedule or []]
        return out

    def exception_table(self) -> List[Dict[str, Any]]:
        out = []
        for se in self.obj.exceptionSchedule or []:
            per = se.period
            if per.calendarEntry is not None:
                what = fmt_entry(per.calendarEntry)
            else:
                cal = self.obj._app.get_object_id(per.calendarReference) if self.obj._app else None
                what = f"calendar {cal.objectName if cal else per.calendarReference}"
            out.append({"period": what, "priority": int(se.eventPriority),
                        "times": [[fmt_hms(tv.time), self.text(to_py(tv.value))] for tv in se.listOfTimeValues or []]})
        return out


# --------------------------------------------------------------------------- builders


def build_calendar(dev: Any, oc: Any) -> Calendar:
    entries = [_entry(parse_calendar_entry(e, f"{oc.name}: dates[{i}]")) for i, e in enumerate(oc.dates or [])]
    kw: Dict[str, Any] = dict(objectIdentifier=(CALENDAR, oc.instance), objectName=oc.name,
                              presentValue=False, dateList=entries)
    if oc.description:
        kw["description"] = oc.description
    return Calendar(dev.device_id, oc, SimCalendarObject(**kw))


def _value_kind(t: str) -> str:
    return "analog" if t in ANALOG_TYPES else "binary" if t in BINARY_TYPES else "multistate"


def _parse_oid(s: str) -> Optional[ObjectIdentifier]:
    """'type:instance' / 'type,instance' (short aliases allowed) -> ObjectIdentifier, None if not that form."""
    t, sep, i = s.replace(",", ":").partition(":")
    if not sep or not i.strip().isdigit():
        return None
    t = t.strip().lower()
    try:
        return ObjectIdentifier((OBJECT_TYPE_ALIASES.get(t, t), int(i)))
    except Exception:
        return None


def build_schedule(dev: Any, oc: Any, points: List[Any], calendars: List[Calendar],
                   devices: Any = ()) -> Schedule:
    """Schedule object writing to value objects of this or another simulated device (``devices``: runtimes with
    ``cfg`` / ``points``); raises ValueError on a bad reference / value."""
    where = f"device {dev.name} ({dev.device_id}): schedule {oc.name}"
    targets, labels, external, refs = [], [], [], []
    for t in oc.targets or []:
        dref, name = (None, t) if isinstance(t, str) else (t["device"], str(t["object"]))
        if dref is None or dref in (dev.name, dev.device_id):
            other, pts = None, points
        else:
            other = next((d.cfg for d in devices if dref in (d.cfg.name, d.cfg.device_id)), None)
            if other is None:  # not simulated here: listed in the property, never written
                oid = _parse_oid(name)
                if isinstance(dref, bool) or not isinstance(dref, int) or oid is None:
                    raise ValueError(f"{where}: target device {dref!r} is not a device of this simulator; "
                                     f"use {{device: <device id>, object: <type:instance>}}")
                refs.append(DeviceObjectPropertyReference(objectIdentifier=oid, propertyIdentifier="present-value",
                                                          deviceIdentifier=("device", dref)))
                label = f"device {dref} {oid[0]}:{oid[1]}"
                labels.append(label + " (external)")
                external.append(label)
                continue
            pts = next(d.points for d in devices if d.cfg is other)
        p = next((q for q in pts if name in (q.cfg.name, q.key)), None)
        if p is None:
            p = next((q for q in pts if (oid := _parse_oid(name)) is not None
                      and (q.cfg.type, q.cfg.instance) == (str(oid[0]), oid[1])), None)
        if p is None:
            raise ValueError(f"{where}: target {name!r} is not a value object of "
                             + (f"device {other.name}" if other else "this device"))
        if p.cfg.type in INPUT_TYPES:
            raise ValueError(f"{where}: target {name!r} is an input; use an output or value object")
        targets.append(p)
        labels.append(f"{other.name}/{p.cfg.name}" if other else p.cfg.name)
        refs.append(DeviceObjectPropertyReference(objectIdentifier=(p.cfg.type, p.cfg.instance),
                                                  propertyIdentifier="present-value",
                                                  **({"deviceIdentifier": ("device", other.device_id)} if other else {})))
    kinds = {_value_kind(p.cfg.type) for p in targets}
    if len(kinds) > 1:
        raise ValueError(f"{where}: targets mix value types ({', '.join(sorted(kinds))})")
    kind = kinds.pop() if kinds else "analog"  # without targets values are REAL
    n_states = min((len(p.cfg.states or []) for p in targets), default=0)
    on_words = _ON | {(p.cfg.active_text or "").lower() for p in targets} - {""}
    off_words = _OFF | {(p.cfg.inactive_text or "").lower() for p in targets} - {""}

    def atomic(v: Any, at: str) -> Any:
        if v is None:
            return Null(())
        try:
            if kind == "analog":
                if isinstance(v, bool):
                    raise ValueError
                return Real(float(v))
            if kind == "binary":
                if isinstance(v, bool) or (isinstance(v, (int, float)) and v in (0, 1)):
                    return Enumerated(int(v))
                s = str(v).strip().lower()
                if s in on_words or s in off_words:
                    return Enumerated(1 if s in on_words else 0)
                raise ValueError
            if isinstance(v, bool):
                raise ValueError
            n = int(v)
            if float(v) != n or n < 1 or (n_states and n > n_states):
                raise ValueError
            return Unsigned(n)
        except (TypeError, ValueError):
            expected = {"analog": "a number", "binary": "0/1, true/false, ON/OFF or active/inactive",
                        "multistate": f"a state number 1..{n_states}"}[kind]
            raise ValueError(f"{where}: {at}: value {v!r} does not match the targets ({kind}: expected {expected})") \
                from None

    def time_values(entries: List[Tuple], at: str) -> List[TimeValue]:
        return [TimeValue(time=Time(hms + (0,)), value=atomic(v, at)) for hms, v in entries]

    weekly = parse_weekly(oc.weekly or {}, f"{oc.name}: weekly")
    weekly_schedule = [DailySchedule(daySchedule=time_values(day, f"weekly.{WEEKDAYS[i]}"))
                       for i, day in enumerate(weekly)]
    exceptions = []
    cal_by_name = {c.cfg.name: c for c in calendars}
    for i, ex in enumerate(oc.exceptions or []):
        at = f"exceptions[{i}]"
        if "calendar" in ex:
            cal = cal_by_name.get(ex["calendar"])
            if cal is None:
                raise ValueError(f"{where}: {at}: calendar {ex['calendar']!r} is not a calendar of this device")
            period = SpecialEventPeriod(calendarReference=(CALENDAR, cal.cfg.instance))
        else:
            period = SpecialEventPeriod(calendarEntry=_entry(parse_calendar_entry(ex["date"], f"{where}: {at}")))
        exceptions.append(SpecialEvent(period=period, eventPriority=int(ex.get("priority", 16)),
                                       listOfTimeValues=time_values(parse_times(ex.get("times") or [], at), at)))
    default_cfg = oc.default if oc.default is not None else {"analog": 0.0, "binary": 0, "multistate": 1}[kind]
    default = atomic(default_cfg, "default")
    ep = oc.effective_period or {}
    period = DateRange(startDate=Date(parse_date(ep["from"]) + (WILDCARD,)) if "from" in ep else Date(ANY_DATE),
                       endDate=Date(parse_date(ep["to"]) + (WILDCARD,)) if "to" in ep else Date(ANY_DATE))
    priority = oc.priority_for_writing or 16
    kw: Dict[str, Any] = dict(
        objectIdentifier=(SCHEDULE, oc.instance),
        objectName=oc.name,
        presentValue=default,
        scheduleDefault=default,
        weeklySchedule=weekly_schedule,
        exceptionSchedule=exceptions,
        effectivePeriod=period,
        listOfObjectPropertyReferences=refs,
        priorityForWriting=priority,
        statusFlags=[0, 0, 0, 0],
        reliability="no-fault-detected",
        outOfService=False,
    )
    if oc.description:
        kw["description"] = oc.description
    obj = SimScheduleObject(DATATYPES[kind], **kw)
    if obj.reliability != Reliability.noFaultDetected:
        raise ValueError(f"{where}: inconsistent schedule values")
    return Schedule(dev.device_id, oc, obj, targets, kind, priority, labels, external)
