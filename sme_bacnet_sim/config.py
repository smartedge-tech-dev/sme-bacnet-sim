"""Configuration model and file loading (YAML / JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# short aliases accepted in config files
OBJECT_TYPE_ALIASES = {
    "ai": "analog-input",
    "ao": "analog-output",
    "av": "analog-value",
    "bi": "binary-input",
    "bo": "binary-output",
    "bv": "binary-value",
    "msi": "multi-state-input",
    "mso": "multi-state-output",
    "msv": "multi-state-value",
    "tl": "trend-log",
    "sch": "schedule",
    "cal": "calendar",
    "nc": "notification-class",
    "acc": "accumulator",
    "pc": "pulse-converter",
    "loop": "loop",
    "file": "file",
    "prog": "program",
    "program": "program",
    "ee": "event-enrollment",
    "lsp": "life-safety-point",
    "lsz": "life-safety-zone",
}
TREND_LOG = "trend-log"
SCHEDULE = "schedule"
CALENDAR = "calendar"
NOTIFICATION_CLASS = "notification-class"
# objects that are not value objects ("points"); the engine builds them separately
FILE = "file"
PROGRAM = "program"
EVENT_ENROLLMENT = "event-enrollment"
LIFE_SAFETY_POINT = "life-safety-point"
LIFE_SAFETY_ZONE = "life-safety-zone"
LIFE_SAFETY_TYPES = {LIFE_SAFETY_POINT, LIFE_SAFETY_ZONE}
LS_FIELDS = ("mode", "accepted_modes", "operation_expected", "silenced")
SPECIAL_TYPES = {TREND_LOG, SCHEDULE, CALENDAR, NOTIFICATION_CLASS, FILE, PROGRAM, EVENT_ENROLLMENT} | LIFE_SAFETY_TYPES
# event-enrollment: supported event types and the keys of their event_parameters
EE_PARAMETERS = {"out-of-range": {"low_limit", "high_limit", "deadband"}, "change-of-state": {"alarm_values"}}
EE_FIELDS = ("monitored_object", "event_type", "event_parameters", "notification_class", "event_enable",
             "notify_type", "time_delay", "time_delay_normal")
OBJECT_TYPES = set(OBJECT_TYPE_ALIASES.values()) - SPECIAL_TYPES
ANALOG_TYPES = {"analog-input", "analog-output", "analog-value"}
BINARY_TYPES = {"binary-input", "binary-output", "binary-value"}
MULTISTATE_TYPES = {"multi-state-input", "multi-state-output", "multi-state-value"}
OUTPUT_TYPES = {"analog-output", "binary-output", "multi-state-output"}
INPUT_TYPES = {"analog-input", "binary-input", "multi-state-input"}
ACCUMULATOR = "accumulator"
PULSE_CONVERTER = "pulse-converter"
LOOP = "loop"
CONTROL_TYPES = {ACCUMULATOR, PULSE_CONVERTER, LOOP}  # value objects with their own runtime (control.py)
REAL_TYPES = ANALOG_TYPES | {PULSE_CONVERTER, LOOP}  # Real present value


WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# shortcuts accepted as keys of a schedule's ``weekly`` mapping
WEEKDAY_GROUPS = {"weekdays": WEEKDAYS[:5], "weekend": WEEKDAYS[5:], "daily": WEEKDAYS}
WILDCARD = 255  # BACnet "unspecified" octet


def parse_time(v: Any) -> tuple:
    """"HH:MM[:SS]" -> (h, m, s).

    Unquoted YAML 1.1 reads ``18:00`` as the sexagesimal int 1080 (``08:00`` stays a string because
    of the leading zero), so ints are accepted too: < 1440 means HH:MM, otherwise HH:MM:SS.
    """
    if isinstance(v, bool):
        raise ValueError(f"invalid time {v!r}")
    if isinstance(v, int):
        h, m, sec = (v // 60, v % 60, 0) if v < 1440 else (v // 3600, v // 60 % 60, v % 60)
    else:
        parts = str(v).strip().split(":")
        if len(parts) not in (2, 3) or not all(x.isdigit() for x in parts):
            raise ValueError(f"invalid time {v!r} (expected HH:MM or HH:MM:SS)")
        h, m, sec = (int(x) for x in (parts + ["0"])[:3])
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= sec <= 59):
        raise ValueError(f"invalid time {v!r}")
    return h, m, sec


def parse_date(v: Any) -> tuple:
    """"YYYY-MM-DD" (``*`` = any year / month / day) or a YAML date -> (year-1900 | 255, month | 255, day | 255)."""
    if hasattr(v, "year") and hasattr(v, "month"):
        return v.year - 1900, v.month, v.day
    parts = str(v).strip().split("-")
    bad = ValueError(f"invalid date {v!r} (expected YYYY-MM-DD, '*' as wildcard)")
    if len(parts) != 3:
        raise bad
    try:
        y, m, d = (WILDCARD if x == "*" else int(x) for x in parts)
    except ValueError:
        raise bad from None
    if (y != WILDCARD and not 1900 <= y <= 2154) or (m != WILDCARD and not 1 <= m <= 12) \
            or (d != WILDCARD and not 1 <= d <= 31):
        raise bad
    return (y if y == WILDCARD else y - 1900), m, d


def parse_times(entries: Any, where: str) -> List[tuple]:
    """[{time, value}, ...] -> sorted [((h, m, s), value), ...]; value None means relinquish (Null)."""
    if not isinstance(entries, list):
        raise ValueError(f"{where}: expected a list of {{time, value}}")
    out = []
    for e in entries:
        if not isinstance(e, dict) or "time" not in e or set(e) - {"time", "value"}:
            raise ValueError(f"{where}: entries need 'time' and 'value', got {e!r}")
        out.append((parse_time(e["time"]), e.get("value")))
    return sorted(out, key=lambda x: x[0])


def parse_weekly(weekly: Dict[str, Any], where: str) -> List[List[tuple]]:
    """weekly mapping -> 7 sorted day lists (Monday first); later keys override earlier ones."""
    days: List[List[tuple]] = [[] for _ in WEEKDAYS]
    for key, entries in weekly.items():
        k = str(key).strip().lower()
        names = WEEKDAY_GROUPS.get(k, [k[:3]])
        if any(n not in WEEKDAYS for n in names):
            raise ValueError(f"{where}: unknown weekday {key!r} (mon..sun, weekdays, weekend, daily)")
        times = parse_times(entries or [], f"{where}.{key}")
        for n in names:
            days[WEEKDAYS.index(n)] = times
    return days


def parse_calendar_entry(e: Any, where: str) -> tuple:
    """Calendar date entry -> ("date", ymd) | ("range", ymd, ymd) | ("weeknday", (month, week, dow))."""
    if isinstance(e, dict):
        if set(e) == {"from", "to"}:
            return "range", parse_date(e["from"]), parse_date(e["to"])
        if set(e) == {"weeknday"} and isinstance(e["weeknday"], list) and len(e["weeknday"]) == 3:
            m, w, d = (WILDCARD if x in ("*", None) else int(x) for x in e["weeknday"])
            if not ((1 <= m <= 14 or m == WILDCARD) and (1 <= w <= 9 or w == WILDCARD)
                    and (1 <= d <= 7 or d == WILDCARD)):
                raise ValueError(f"{where}: invalid weeknday {e['weeknday']!r}")
            return "weeknday", (m, w, d)
        raise ValueError(f"{where}: expected a date, {{from, to}} or {{weeknday: [month, week, dow]}}, got {e!r}")
    return "date", parse_date(e)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def ms_index(v: Any, states: Optional[List[str]], oc: Any = None) -> int:
    """State number (1-based) or state text -> state number; binary objects: 1 = inactive, 2 = active."""
    if oc is not None and oc.type in BINARY_TYPES:
        s = str(v).strip().lower()
        if s in ("1", "true", "on", "active") or (oc.active_text and s == oc.active_text.lower()):
            return 2
        if s in ("0", "false", "off", "inactive") or (oc.inactive_text and s == oc.inactive_text.lower()):
            return 1
        raise ValueError(f"invalid binary value {v!r} (active / inactive)")
    names = [str(x).strip().lower() for x in (states or [])]
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= len(names):
        return v
    s = str(v).strip().lower()
    if s in names:
        return names.index(s) + 1
    raise ValueError(f"invalid state {v!r} (1..{len(names)} or a state text)")


class RecipientConfig(_Model):
    """Notification-class recipient: a device (resolved with Who-Is unless an address is given) or an address."""

    device: Optional[int] = Field(default=None, ge=0, le=4194302)
    address: Optional[str] = None  # "<net>:<mac>" or "<ip>:<port>" (BACnet/IP side of the router)
    process_id: int = Field(default=0, ge=0, le=4294967295)
    confirmed: bool = False
    transitions: List[bool] = Field(default_factory=lambda: [True, True, True])  # to-offnormal, to-fault, to-normal
    from_time: Any = None  # default 00:00:00
    to_time: Any = None  # default 23:59:59
    days: Optional[List[str]] = None  # mon..sun / weekdays / weekend / daily; default every day

    @model_validator(mode="after")
    def _check(self) -> "RecipientConfig":
        if self.device is None and self.address is None:
            raise ValueError("recipient needs 'device' and/or 'address' (an address skips the Who-Is lookup)")
        if self.address is not None and ":" not in self.address:
            raise ValueError(f"recipient address {self.address!r}: expected '<net>:<mac>' or '<ip>:<port>'")
        if len(self.transitions) != 3:
            raise ValueError("recipient transitions needs 3 flags [to-offnormal, to-fault, to-normal]")
        for t in (self.from_time, self.to_time):
            if t is not None:
                parse_time(t)
        if self.days is not None:
            days: List[str] = []
            for d in self.days:
                k = str(d).strip().lower()
                names = WEEKDAY_GROUPS.get(k, [k[:3]])
                if any(n not in WEEKDAYS for n in names):
                    raise ValueError(f"recipient days: unknown weekday {d!r}")
                days += names
            self.days = days
        return self


class AlarmConfig(_Model):
    """Intrinsic reporting of a value object (see sme_bacnet_sim/alarm.py)."""

    notification_class: Union[int, str]  # notification-class object name or instance in the same device
    high_limit: Optional[float] = None  # analog
    low_limit: Optional[float] = None  # analog
    deadband: float = Field(default=0.0, ge=0)  # analog
    limit_enable: Optional[List[bool]] = None  # analog [low, high]; default: the limits that are set
    alarm_value: Any = None  # binary: active / inactive
    alarm_values: Optional[List[Any]] = None  # multi-state: state numbers or texts
    fault_values: Optional[List[Any]] = None  # multi-state
    time_delay: int = Field(default=0, ge=0)  # sim seconds
    time_delay_normal: Optional[int] = Field(default=None, ge=0)  # sim seconds; default time_delay
    event_enable: List[bool] = Field(default_factory=lambda: [True, True, True])
    notify_type: Literal["alarm", "event"] = "alarm"

    def check(self, oc: "ObjectConfig") -> None:
        n = f"{oc.name}: alarm"
        if len(self.event_enable) != 3:
            raise ValueError(f"{n}: event_enable needs 3 flags [to-offnormal, to-fault, to-normal]")
        analog = ("high_limit", "low_limit", "limit_enable")
        if oc.type in ANALOG_TYPES:
            bad = [k for k in ("alarm_value", "alarm_values", "fault_values") if getattr(self, k) is not None]
        elif oc.type in BINARY_TYPES:
            bad = [k for k in analog + ("alarm_values", "fault_values") if getattr(self, k) is not None]
        else:
            bad = [k for k in analog + ("alarm_value",) if getattr(self, k) is not None]
        if self.deadband and oc.type not in ANALOG_TYPES:
            bad.append("deadband")
        if bad:
            raise ValueError(f"{n}: {', '.join(bad)} not valid for {oc.type}")
        if oc.type in ANALOG_TYPES:
            hi, lo = self.high_limit, self.low_limit
            if hi is None and lo is None:
                raise ValueError(f"{n}: analog alarm needs high_limit and/or low_limit")
            if hi is not None and lo is not None and lo >= hi:
                raise ValueError(f"{n}: low_limit ({lo}) must be below high_limit ({hi})")
            if self.limit_enable is not None:
                if len(self.limit_enable) != 2:
                    raise ValueError(f"{n}: limit_enable needs 2 flags [low, high]")
                if self.limit_enable[0] and lo is None or self.limit_enable[1] and hi is None:
                    raise ValueError(f"{n}: limit_enable enables a limit that is not set")
        elif oc.type in BINARY_TYPES:
            if self.alarm_value is None:
                raise ValueError(f"{n}: binary alarm needs alarm_value")
            ms_index(self.alarm_value, None, oc)
        else:
            if not self.alarm_values and not self.fault_values:
                raise ValueError(f"{n}: multi-state alarm needs alarm_values and/or fault_values")
            av = {ms_index(v, oc.states) for v in self.alarm_values or []}
            fv = {ms_index(v, oc.states) for v in self.fault_values or []}
            if av & fv:
                raise ValueError(f"{n}: states {sorted(av & fv)} are both alarm and fault values")


class ObjectConfig(_Model):
    type: str
    instance: Optional[int] = None  # auto-assigned per type when omitted
    name: str
    description: str = ""
    units: Optional[str] = None  # BACnet EngineeringUnits, e.g. degrees-celsius
    value: Any = None  # initial present value
    states: Optional[List[str]] = None  # multi-state state texts
    active_text: Optional[str] = None
    inactive_text: Optional[str] = None
    commandable: Optional[bool] = None  # outputs are always commandable
    cov_increment: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    behavior: Optional[Dict[str, Any]] = None
    # trend-log only (None = default, so value objects do not carry these keys when dumped)
    log_object: Optional[str] = None  # name of the logged object in the same device
    log_property: Optional[str] = None  # default present-value
    log_interval: Optional[float] = Field(default=None, gt=0)  # sim seconds, default 60
    buffer_size: Optional[int] = Field(default=None, ge=1, le=100000)  # default 1000
    enabled: Optional[bool] = None  # default true
    logging_type: Optional[Literal["polled", "cov"]] = None  # default polled
    client_cov_increment: Optional[float] = Field(default=None, gt=0)  # cov mode; default: target's COV increment
    # schedule only (see sme_bacnet_sim/schedule.py)
    weekly: Optional[Dict[str, Any]] = None  # mon..sun / weekdays / weekend / daily -> [{time, value}]
    exceptions: Optional[List[Dict[str, Any]]] = None  # [{date (any calendar entry) | calendar, priority, times}]
    default: Any = None  # schedule-default; 0 / inactive / 1 by value type when omitted
    targets: Optional[List[Any]] = None  # object names of this device, or {device, object} in another device
    priority_for_writing: Optional[int] = Field(default=None, ge=1, le=16)  # default 16
    effective_period: Optional[Dict[str, Any]] = None  # {from, to}; default: always
    # calendar only
    dates: Optional[List[Any]] = None  # dates, {from, to} ranges, {weeknday: [month, week, dow]}
    # notification-class only (see sme_bacnet_sim/alarm.py); instance = notification class number
    priority: Optional[List[int]] = None  # [to-offnormal, to-fault, to-normal], default [100, 100, 200]
    ack_required: Optional[List[bool]] = None  # default [true, true, false]
    recipients: Optional[List[RecipientConfig]] = None
    # value objects: intrinsic reporting
    alarm: Optional[AlarmConfig] = None
    # accumulator only (max = max-pres-value)
    scale: Optional[float] = None  # scale (floatScale), default 1.0
    prescale: Optional[List[int]] = None  # [multiplier, modulo_divide]; stored, not applied
    # pulse-converter only
    scale_factor: Optional[float] = None  # present-value units per input count, default 1.0
    input_object: Optional[str] = None  # name of an accumulator of the same device (input-reference)
    # loop only (min / max = minimum-output / maximum-output, units = output-units)
    controlled_object: Optional[str] = None  # controlled-variable-reference: present-value of this object
    manipulated_object: Optional[str] = None  # manipulated-variable-reference: present-value of this object
    setpoint: Optional[float] = None  # setpoint (used when setpoint_object is not given)
    setpoint_object: Optional[str] = None  # setpoint-reference: present-value of this object
    proportional_constant: Optional[float] = None  # default 1.0
    integral_constant: Optional[float] = None  # default 0.0 (per second)
    derivative_constant: Optional[float] = None  # default 0.0 (seconds)
    bias: Optional[float] = None  # default 0.0
    action: Optional[Literal["direct", "reverse"]] = None  # default direct
    update_interval: Optional[float] = Field(default=None, gt=0)  # sim seconds, default 1
    # file only (see sme_bacnet_sim/fileprog.py)
    file_type: Optional[str] = None  # File_Type (MIME type), default text/plain
    access: Optional[Literal["stream", "record"]] = None  # File_Access_Method, default stream
    content: Optional[str] = None  # initial content (record access: one record per line)
    path: Optional[str] = None  # or: file to load, relative to the config file (never written back)
    read_only: Optional[bool] = None  # Read_Only, default false
    # program only
    program_state: Optional[Literal["idle", "running", "halted"]] = None  # initial Program_State, default idle
    instance_of: Optional[str] = None  # Instance_Of, default the object name
    program_location: Optional[str] = None  # Program_Location
    # event-enrollment only (algorithmic reporting, see sme_bacnet_sim/eventenroll.py)
    monitored_object: Optional[str] = None  # object of the same device whose present-value is monitored
    event_type: Optional[str] = None  # out-of-range | change-of-state
    event_parameters: Optional[Dict[str, Any]] = None  # out-of-range: low_limit, high_limit, deadband;
    # change-of-state: alarm_values (state numbers / texts, or active / inactive)
    notification_class: Optional[Union[int, str]] = None  # notification-class object name or instance
    event_enable: Optional[List[bool]] = None  # default [true, true, true]
    notify_type: Optional[Literal["alarm", "event"]] = None  # default alarm
    time_delay: Optional[int] = Field(default=None, ge=0)  # sim seconds, default 0
    time_delay_normal: Optional[int] = Field(default=None, ge=0)  # sim seconds, default time_delay
    # life-safety-point / life-safety-zone only (see sme_bacnet_sim/lifesafety.py); value = initial state
    mode: Optional[Union[str, bool]] = None  # BACnetLifeSafetyMode, default on (YAML on / off = true / false)
    accepted_modes: Optional[List[Union[str, bool]]] = None  # default [off, on, test]
    operation_expected: Optional[str] = None  # BACnetLifeSafetyOperation, default none
    silenced: Optional[str] = None  # BACnetSilencedState, default unsilenced
    zone_members: Optional[List[str]] = None  # zone only: names of life safety objects of the same device

    @field_validator("type")
    @classmethod
    def _norm_type(cls, v: str) -> str:
        v = OBJECT_TYPE_ALIASES.get(v.strip().lower(), v.strip().lower())
        if v not in OBJECT_TYPES and v not in SPECIAL_TYPES:
            raise ValueError(f"unsupported object type: {v}")
        return v

    @model_validator(mode="after")
    def _check(self) -> "ObjectConfig":
        if self.type in MULTISTATE_TYPES and not self.states:
            raise ValueError(f"{self.name}: multi-state object needs 'states'")
        if self.behavior is not None and "type" not in self.behavior:
            raise ValueError(f"{self.name}: behavior needs 'type'")
        if self.type == TREND_LOG and not self.log_object:
            raise ValueError(f"{self.name}: trend-log needs 'log_object'")
        if self.client_cov_increment is not None and self.logging_type != "cov":
            raise ValueError(f"{self.name}: client_cov_increment needs logging_type: cov")
        if self.type == SCHEDULE:
            self._check_schedule()
        if self.type == CALENDAR:
            for i, e in enumerate(self.dates or []):
                parse_calendar_entry(e, f"{self.name}: dates[{i}]")
        if self.type == NOTIFICATION_CLASS:
            if self.priority is not None and (len(self.priority) != 3 or any(not 0 <= p <= 255 for p in self.priority)):
                raise ValueError(f"{self.name}: priority needs 3 values 0..255 [to-offnormal, to-fault, to-normal]")
            if self.ack_required is not None and len(self.ack_required) != 3:
                raise ValueError(f"{self.name}: ack_required needs 3 flags [to-offnormal, to-fault, to-normal]")
        elif any(getattr(self, k) is not None for k in ("priority", "ack_required", "recipients")):
            raise ValueError(f"{self.name}: priority / ack_required / recipients are only valid for notification-class")
        if self.type == FILE:
            if self.content is not None and self.path is not None:
                raise ValueError(f"{self.name}: file takes 'content' or 'path', not both")
        elif any(getattr(self, k) is not None for k in ("file_type", "access", "content", "path", "read_only")):
            raise ValueError(f"{self.name}: file_type / access / content / path / read_only are only valid for file")
        if self.type != PROGRAM and any(getattr(self, k) is not None
                                        for k in ("program_state", "instance_of", "program_location")):
            raise ValueError(f"{self.name}: program_state / instance_of / program_location are only valid for program")
        if self.type in CONTROL_TYPES and self.commandable:
            raise ValueError(f"{self.name}: {self.type} objects are not commandable")
        if self.type == LOOP:
            if not self.controlled_object or not self.manipulated_object:
                raise ValueError(f"{self.name}: loop needs 'controlled_object' and 'manipulated_object'")
            if self.setpoint is None and not self.setpoint_object:
                raise ValueError(f"{self.name}: loop needs 'setpoint' or 'setpoint_object'")
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ValueError(f"{self.name}: min (minimum output) must not exceed max (maximum output)")
        if self.type == ACCUMULATOR:
            if self.max is not None and (self.max < 1 or self.max != int(self.max)):
                raise ValueError(f"{self.name}: accumulator max (max-pres-value) must be a positive integer")
            if self.prescale is not None and (len(self.prescale) != 2 or any(x < 0 for x in self.prescale)):
                raise ValueError(f"{self.name}: prescale needs [multiplier, modulo_divide] (unsigned)")
        if self.type in LIFE_SAFETY_TYPES:
            self._check_life_safety()
        elif any(getattr(self, k) is not None for k in LS_FIELDS + ("zone_members",)):
            raise ValueError(f"{self.name}: {' / '.join(LS_FIELDS)} / zone_members are only valid for "
                             f"life-safety-point / life-safety-zone")
        if self.type == EVENT_ENROLLMENT:
            self._check_ee()
        elif any(getattr(self, k) is not None for k in EE_FIELDS):
            raise ValueError(f"{self.name}: {' / '.join(EE_FIELDS)} are only valid for event-enrollment")
        if self.alarm is not None:
            if self.type in SPECIAL_TYPES or self.type in CONTROL_TYPES:
                raise ValueError(f"{self.name}: 'alarm' is only valid on value objects")
            self.alarm.check(self)
        return self

    def _check_life_safety(self) -> None:
        """Enumeration names (bacpypes3 accepts both ``pre-alarm`` and ``preAlarm``); members are resolved later."""
        from bacpypes3.basetypes import LifeSafetyMode, LifeSafetyOperation, LifeSafetyState, SilencedState

        def norm(enum: Any, v: Any, what: str) -> str:
            if isinstance(v, bool):  # unquoted YAML 1.1 on / off
                v = "on" if v else "off"
            try:
                s = str(enum(v))
            except Exception:
                s = ""
            if not s or s.isdigit():
                raise ValueError(f"{self.name}: invalid {what} {v!r}")
            return s

        if self.value is not None:
            self.value = norm(LifeSafetyState, self.value, "life safety state (value)")
        if self.mode is not None:
            self.mode = norm(LifeSafetyMode, self.mode, "mode")
        if self.accepted_modes is not None:
            self.accepted_modes = [norm(LifeSafetyMode, m, "accepted_modes entry") for m in self.accepted_modes]
        if self.mode is not None and self.mode not in (self.accepted_modes or ["off", "on", "test"]):
            raise ValueError(f"{self.name}: mode {self.mode!r} is not one of accepted_modes")
        if self.operation_expected is not None:
            self.operation_expected = norm(LifeSafetyOperation, self.operation_expected, "operation_expected")
        if self.silenced is not None:
            self.silenced = norm(SilencedState, self.silenced, "silenced")
        if self.zone_members is not None and self.type != LIFE_SAFETY_ZONE:
            raise ValueError(f"{self.name}: zone_members is only valid for life-safety-zone")

    def _check_ee(self) -> None:
        """Static checks of an event enrollment; the monitored object is checked by the engine."""
        n = self.name
        if not self.monitored_object or self.notification_class is None:
            raise ValueError(f"{n}: event-enrollment needs 'monitored_object' and 'notification_class'")
        if self.event_type not in EE_PARAMETERS:
            raise ValueError(f"{n}: event_type {self.event_type!r} not supported "
                             f"(supported: {', '.join(EE_PARAMETERS)})")
        ep = self.event_parameters or {}
        bad = set(ep) - EE_PARAMETERS[self.event_type]
        if bad:
            raise ValueError(f"{n}: event_parameters {sorted(bad)} not valid for {self.event_type}")
        if self.event_type == "out-of-range":
            if ep.get("low_limit") is None or ep.get("high_limit") is None:
                raise ValueError(f"{n}: out-of-range needs event_parameters low_limit and high_limit")
            if float(ep["low_limit"]) >= float(ep["high_limit"]):
                raise ValueError(f"{n}: low_limit must be below high_limit")
            if float(ep.get("deadband", 0)) < 0:
                raise ValueError(f"{n}: deadband must not be negative")
        elif not ep.get("alarm_values"):
            raise ValueError(f"{n}: change-of-state needs event_parameters alarm_values")
        if self.event_enable is not None and len(self.event_enable) != 3:
            raise ValueError(f"{n}: event_enable needs 3 flags [to-offnormal, to-fault, to-normal]")

    def _check_schedule(self) -> None:
        """Format checks; references to targets / calendars are resolved by the engine."""
        n = self.name
        if self.weekly is None and not self.exceptions:
            raise ValueError(f"{n}: schedule needs 'weekly' and/or 'exceptions'")
        if self.weekly is not None:
            parse_weekly(self.weekly, f"{n}: weekly")
        for i, ex in enumerate(self.exceptions or []):
            where = f"{n}: exceptions[{i}]"
            extra = set(ex) - {"date", "calendar", "priority", "times"}
            if extra:
                raise ValueError(f"{where}: unknown key(s) {sorted(extra)}")
            if ("date" in ex) == ("calendar" in ex):
                raise ValueError(f"{where}: needs exactly one of 'date' or 'calendar'")
            if "date" in ex:  # a date, {from, to} range or {weeknday: [month, week, dow]}
                parse_calendar_entry(ex["date"], f"{where}.date")
            pr = ex.get("priority", 16)
            if isinstance(pr, bool) or not isinstance(pr, int) or not 1 <= pr <= 16:
                raise ValueError(f"{where}: priority must be 1..16")
            parse_times(ex.get("times") or [], f"{where}.times")
        for i, t in enumerate(self.targets or []):
            if isinstance(t, str):
                continue
            if not (isinstance(t, dict) and set(t) == {"device", "object"} and isinstance(t["object"], str)
                    and isinstance(t["device"], (int, str)) and not isinstance(t["device"], bool)):
                raise ValueError(f"{n}: targets[{i}]: expected an object name or "
                                 f"{{device: <name or id>, object: <name or type:instance>}}, got {t!r}")
        if self.effective_period is not None:
            if set(self.effective_period) - {"from", "to"}:
                raise ValueError(f"{n}: effective_period takes 'from' / 'to'")
            for k in ("from", "to"):
                if k in self.effective_period:
                    parse_date(self.effective_period[k])

    @property
    def is_commandable(self) -> bool:
        return self.type in OUTPUT_TYPES or bool(self.commandable)


class PrivateTransferConfig(_Model):
    """Answer of a ConfirmedPrivateTransfer with this vendor id / service number."""

    vendor_id: int = Field(ge=0, le=65535)
    service_number: int = Field(ge=0, le=4294967295)
    result: Any = "echo"  # "echo" (return the service parameters), null (no result block) or a fixed value


class DeviceConfig(_Model):
    device_id: int = Field(ge=0, le=4194302)
    name: str
    description: str = ""
    template: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    vendor_id: int = 999
    vendor_name: str = "smart-edge"
    model_name: Optional[str] = None
    location: str = ""
    objects: List[ObjectConfig] = Field(default_factory=list)
    # names of template objects deleted at run time (DeleteObject); kept out of template expansion
    removed: Optional[List[str]] = None
    dcc_password: Optional[str] = None  # DeviceCommunicationControl password (none = not checked)
    reinit_password: Optional[str] = None  # ReinitializeDevice password (none = not checked)
    private_transfer: Optional[List[PrivateTransferConfig]] = None  # ConfirmedPrivateTransfer answers


class RouterConfig(_Model):
    device_id: int = 4194000
    name: str = "SME-BACnetSim-Router"


class ForeignDeviceConfig(_Model):
    """Register the router's BACnet/IP port as a foreign device with an external BBMD."""
    bbmd: str  # "<ipv4>[:<port>]", port defaults to 47808
    ttl: int = Field(default=300, ge=1, le=65535)  # Time-to-Live in seconds, renewed by bacpypes3

    @field_validator("bbmd")
    @classmethod
    def _check_bbmd(cls, v: str) -> str:
        return parse_host_port(v)


def parse_host_port(v: str, default_port: int = 47808) -> str:
    """'192.168.1.10' or '192.168.1.10:47808' -> normalized '192.168.1.10:47808' (IPv4 literals only)."""
    import ipaddress
    host, sep, port = str(v).strip().partition(":")
    try:
        ipaddress.IPv4Address(host)
        p = int(port) if sep else default_port
    except ValueError:
        raise ValueError(f"{v!r}: expected '<ipv4>[:<port>]'") from None
    if not 1 <= p <= 65535:
        raise ValueError(f"{v!r}: port out of range")
    return f"{host}:{p}"


class NetworkConfig(_Model):
    ip: str = "auto"  # "auto" or "192.168.1.10/24"
    port: int = 47808
    network_number: int = Field(default=1, ge=1, le=65534)  # network number of the IP side (routing needs one)
    virtual_network: int = Field(default=100, ge=1, le=65534)
    mode: Literal["normal", "bbmd"] = "normal"
    foreign_device: Optional[ForeignDeviceConfig] = None  # register with an external BBMD (normal mode only)
    router: RouterConfig = Field(default_factory=RouterConfig)

    @model_validator(mode="after")
    def _check_foreign(self) -> "NetworkConfig":
        if self.foreign_device is not None and self.mode == "bbmd":
            raise ValueError("network.foreign_device cannot be combined with network.mode: bbmd")
        return self


class SimulationConfig(_Model):
    tick_seconds: float = Field(default=1.0, gt=0.05, le=60)
    time_scale: float = Field(default=1.0, gt=0, le=3600)  # sim seconds per real second
    history_size: int = Field(default=600, ge=10, le=100000)
    running: bool = True


class SimConfig(_Model):
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    devices: List[DeviceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> "SimConfig":
        if self.network.network_number == self.network.virtual_network:
            raise ValueError("network.network_number and network.virtual_network must differ")
        ids = [d.device_id for d in self.devices] + [self.network.router.device_id]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate device_id: {sorted(dup)}")
        return self


def parse_text(text: str, fmt: Optional[str] = None) -> SimConfig:
    """Parse YAML or JSON text (YAML is a superset of JSON)."""
    data = json.loads(text) if fmt == "json" else yaml.safe_load(text)
    return SimConfig.model_validate(data or {})


def load_file(path: Union[str, Path]) -> SimConfig:
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), "json" if p.suffix.lower() == ".json" else None)


def dump_yaml(cfg: Union[SimConfig, BaseModel, dict]) -> str:
    data = cfg.model_dump(exclude_none=True, exclude_defaults=False) if isinstance(cfg, BaseModel) else cfg
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
