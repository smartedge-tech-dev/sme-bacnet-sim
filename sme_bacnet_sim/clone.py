"""Clone real BACnet devices into a simulator config: ``sme-bacnet-sim clone ...``.

Read-only by construction: the client application (:class:`ReadOnlyApplication`) refuses to send any APDU other
than Who-Is, ReadProperty and ReadPropertyMultiple, and it never answers incoming requests (no I-Am, no
ReadProperty answers). The object list is read element by element (array index 0 = length, then 1..N) so devices
without segmentation work; ReadPropertyMultiple is used per object and falls back to ReadProperty for the rest of
the device on the first failure.

Cross-subnet (``--foreign-bbmd``): the client registers as a foreign device with a BBMD so the broadcast I-Am
answers are forwarded to it. Register-Foreign-Device / Distribute-Broadcast-To-Network are BVLL messages below the
APDU layer; the read-only guard is unchanged (no write / subscribe / DCC APDU can be sent).

Output: a SimConfig YAML (devices only; the network section is left at the simulator defaults, i.e. the devices
are served on the virtual network behind the built-in router) and ``<out>.log.jsonl`` with one line per request /
answer / error / warning. The YAML is rewritten after every device, so an interrupted run keeps what it has read.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import yaml
from bacpypes3.apdu import (ErrorRejectAbortNack, IAmRequest, ReadPropertyMultipleRequest, ReadPropertyRequest,
                            WhoIsRequest)
from bacpypes3.app import Application
from bacpypes3.basetypes import ErrorType, HostNPort
from bacpypes3.ipv4.service import BIPForeign
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address, LocalBroadcast
from bacpypes3.primitivedata import ObjectIdentifier

from .config import (ACCUMULATOR, ANALOG_TYPES, BINARY_TYPES, CALENDAR, EVENT_ENROLLMENT, FILE, LIFE_SAFETY_TYPES,
                     LIFE_SAFETY_ZONE, LOOP, MULTISTATE_TYPES, NOTIFICATION_CLASS, OBJECT_TYPES, OUTPUT_TYPES,
                     PROGRAM, PULSE_CONVERTER, SCHEDULE, SPECIAL_TYPES, TREND_LOG, WEEKDAYS, SimConfig,
                     parse_host_port)
from .schedule import entry_to_cfg, fmt_date, schedule_to_cfg

ALLOWED_REQUESTS = (WhoIsRequest, ReadPropertyRequest, ReadPropertyMultipleRequest)
SUPPORTED_TYPES = OBJECT_TYPES | SPECIAL_TYPES
SILENT_TYPES = {"device", "network-port"}  # created by the simulator itself, not warned about
RPM_BIT = 14  # BACnetServicesSupported: readPropertyMultiple
VALUE_TYPES = ANALOG_TYPES | BINARY_TYPES | MULTISTATE_TYPES

DEVICE_PROPS = ["object-name", "vendor-name", "vendor-identifier", "model-name", "description", "location",
                "max-apdu-length-accepted", "segmentation-supported", "protocol-services-supported"]
ALARM_COMMON = ["notification-class", "event-enable", "notify-type", "time-delay", "time-delay-normal"]


class ReadOnlyViolation(RuntimeError):
    """Raised when anything but Who-Is / ReadProperty / ReadPropertyMultiple would be sent."""


class ObjectListError(RuntimeError):
    """The object list could neither be read nor taken from --object-list-file."""


class ReadOnlyApplication(Application):
    """bacpypes3 application that can only send Who-Is / ReadProperty / ReadPropertyMultiple.

    The guard is on the APDU layer. With ``--foreign-bbmd`` the BVLL link layer additionally sends
    Register-Foreign-Device (and TTL 0 on exit) and wraps broadcasts in Distribute-Broadcast-To-Network; that is
    link-layer plumbing, not a BACnet service, and it never carries anything but the allowed APDUs.
    """

    def request(self, apdu):  # every client service of bacpypes3 goes through here
        if not isinstance(apdu, ALLOWED_REQUESTS):
            raise ReadOnlyViolation(f"clone is read-only: refusing to send {type(apdu).__name__}")
        return super().request(apdu)

    async def indication(self, apdu) -> None:
        # passive: only I-Am (answers to our Who-Is) is processed; other requests are ignored, never answered
        if isinstance(apdu, IAmRequest):
            await super().indication(apdu)


def props_for(t: str) -> List[str]:
    p = ["object-name", "description"]
    if t in VALUE_TYPES:
        p += ["present-value", "priority-array", "relinquish-default"]
        if t in ANALOG_TYPES:
            p += ["units", "cov-increment", "high-limit", "low-limit", "deadband", "limit-enable"]
            if t != "analog-input":
                p += ["min-pres-value", "max-pres-value"]
        elif t in BINARY_TYPES:
            p += ["active-text", "inactive-text", "alarm-value"]
        else:
            p += ["state-text", "number-of-states", "alarm-values", "fault-values"]
        p += ALARM_COMMON
    elif t == ACCUMULATOR:
        p += ["present-value", "units", "max-pres-value", "scale", "prescale"]
    elif t == PULSE_CONVERTER:
        p += ["present-value", "units", "scale-factor", "cov-increment", "input-reference"]
    elif t == LOOP:
        p += ["present-value", "output-units", "update-interval", "setpoint", "setpoint-reference",
              "controlled-variable-reference", "manipulated-variable-reference", "proportional-constant",
              "integral-constant", "derivative-constant", "bias", "action", "minimum-output", "maximum-output",
              "cov-increment"]
    elif t == TREND_LOG:
        p += ["log-device-object-property", "log-interval", "buffer-size", "enable", "logging-type",
              "client-cov-increment"]
    elif t == SCHEDULE:
        p += ["weekly-schedule", "exception-schedule", "schedule-default", "list-of-object-property-references",
              "priority-for-writing", "effective-period"]
    elif t == CALENDAR:
        p += ["date-list"]
    elif t == NOTIFICATION_CLASS:
        p += ["priority", "ack-required", "recipient-list"]
    elif t == FILE:
        p += ["file-type", "file-access-method", "read-only"]
    elif t == PROGRAM:
        p += ["program-state", "instance-of", "program-location"]
    elif t == EVENT_ENROLLMENT:
        p += ["object-property-reference", "event-type", "event-parameters", "notification-class",
              "event-enable", "notify-type"]
    elif t in LIFE_SAFETY_TYPES:
        p += ["present-value", "mode", "accepted-modes", "operation-expected", "silenced"]
        if t == LIFE_SAFETY_ZONE:
            p += ["zone-members"]
    return p


def jsonable(v: Any) -> Any:
    if v is None or isinstance(v, bool):
        return v
    for t in (int, float, str):  # bacpypes3 primitives subclass these
        if isinstance(v, t):
            return t(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    try:
        return jsonable(v.dict_contents())
    except Exception:
        pass
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return str(v)


class ReadOnlyClient:
    """Paced, logged, retried Who-Is / ReadProperty / ReadPropertyMultiple on a :class:`ReadOnlyApplication`."""

    def __init__(self, app: ReadOnlyApplication, rate: float, timeout: float, retries: int, log) -> None:
        self.app, self.interval, self.timeout, self.retries, self.log = app, 1.0 / rate, timeout, retries, log
        self._next = 0.0
        self.services: List[str] = []  # names of every service sent (tests assert on it)

    async def _pace(self) -> None:
        now = time.monotonic()
        wait = self._next - now
        self._next = max(now, self._next) + self.interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def who_is(self, low: Optional[int], high: Optional[int], address: Address) -> List[Any]:
        await self._pace()
        self.services.append("who-is")
        self.log(kind="who-is", address=str(address), low=low, high=high)
        iams = await self.app.who_is(low, high, address=address, timeout=self.timeout)
        for i in iams:
            self.log(kind="i-am", device=i.iAmDeviceIdentifier[1], address=str(i.pduSource),
                     max_apdu=int(i.maxAPDULengthAccepted), segmentation=str(i.segmentationSupported),
                     vendor_id=int(i.vendorID))
        return iams

    async def _call(self, service: str, factory, **logkw) -> Any:
        err: Any = None
        for attempt in range(self.retries + 1):
            await self._pace()
            self.services.append(service)
            try:
                # bacpypes3 retries the APDU itself (apduTimeout / numberOfApduRetries); this is the outer cap
                return await asyncio.wait_for(factory(), self.timeout * (self.retries + 1) + 1)
            except ErrorRejectAbortNack as e:  # an answer: no point in retrying
                self.log(kind=service, error=str(e), **logkw)
                raise
            except asyncio.TimeoutError as e:
                err = e
                self.log(kind=service, error="timeout", attempt=attempt + 1, **logkw)
        raise asyncio.TimeoutError(f"no answer after {self.retries + 1} attempt(s)") from err

    async def read(self, addr: Address, oid: ObjectIdentifier, prop: str, index: Optional[int] = None) -> Any:
        kw = dict(device_address=str(addr), object=str(oid), property=prop, index=index)
        v = await self._call("read-property", lambda: self.app.read_property(addr, oid, prop, index), **kw)
        self.log(kind="read-property", value=jsonable(v), **kw)
        return v

    async def read_multiple(self, addr: Address, oid: ObjectIdentifier, props: List[str]) -> Dict[str, Any]:
        kw = dict(device_address=str(addr), object=str(oid), properties=props)
        res = await self._call("read-property-multiple",
                               lambda: self.app.read_property_multiple(addr, [(oid, props)]), **kw)
        out: Dict[str, Any] = {}
        for _oid, pid, _idx, v in res:
            if isinstance(v, ErrorType):
                self.log(kind="read-property-multiple", object=str(oid), property=str(pid),
                         error=f"{v.errorClass}: {v.errorCode}")
            else:
                out[str(pid)] = v
                self.log(kind="read-property-multiple", object=str(oid), property=str(pid), value=jsonable(v))
        return out


# --------------------------------------------------------------------------- BACnet values -> config


def _f(v: Any) -> Optional[float]:
    return None if v is None else round(float(v), 6)


def _s(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def _bits(v: Any) -> Optional[List[bool]]:
    return None if v is None else [bool(x) for x in v]


class Mapper:
    """Turns the raw properties of one device into ObjectConfig dicts, collecting warnings."""

    def __init__(self, device_id: int, raw: Dict[Tuple[str, int], Dict[str, Any]], warn) -> None:
        self.dev, self.raw, self.warn = device_id, raw, warn
        self.names: Dict[Tuple[str, int], str] = {}
        seen: Dict[str, int] = {}
        for key, p in raw.items():
            name = str(p.get("object-name") or f"{key[0]}-{key[1]}")
            if name in seen:
                seen[name] += 1
                new = f"{name} ({seen[name]})"
                warn(f"{key[0]},{key[1]}: duplicate object name {name!r}, renamed to {new!r}")
                name = new
            else:
                seen[name] = 1
            self.names[key] = name

    def name_of(self, oid: Any, where: str, device: Any = None) -> Optional[str]:
        if oid is None:
            return None
        if device is not None and int(device[1]) != self.dev:
            self.warn(f"{where}: references device {int(device[1])} (only the same device is supported)")
            return None
        key = (str(oid[0]), int(oid[1]))
        if key not in self.names:
            self.warn(f"{where}: references {key[0]},{key[1]}, which was not cloned")
            return None
        return self.names[key]

    def nc_ref(self, inst: Any) -> Any:
        key = (NOTIFICATION_CLASS, int(inst))
        return self.names.get(key)

    def map(self, key: Tuple[str, int]) -> Optional[Dict[str, Any]]:
        t, inst = key
        p = self.raw[key]
        o: Dict[str, Any] = {"type": t, "instance": inst, "name": self.names[key]}
        if p.get("description"):
            o["description"] = str(p["description"])
        w = f"{t},{inst} ({o['name']})"
        if t in VALUE_TYPES:
            self._value(t, p, o, w)
        elif t == ACCUMULATOR:
            o.update(value=int(p.get("present-value") or 0), units=_s(p.get("units")))
            if p.get("max-pres-value") is not None:
                o["max"] = int(p["max-pres-value"])
            sc = p.get("scale")
            if sc is not None:
                o["scale"] = _f(sc.floatScale if sc.floatScale is not None else sc.integerScale)
            ps = p.get("prescale")
            if ps is not None:
                o["prescale"] = [int(ps.multiplier), int(ps.moduloDivide)]
        elif t == PULSE_CONVERTER:
            o.update(value=_f(p.get("present-value")), units=_s(p.get("units")),
                     scale_factor=_f(p.get("scale-factor")), cov_increment=_f(p.get("cov-increment")))
            ref = p.get("input-reference")
            if ref is not None:
                o["input_object"] = self.name_of(ref.objectIdentifier, f"{w}: input-reference")
        elif t == LOOP:
            if not self._loop(p, o, w):
                return None
        elif t == TREND_LOG:
            if not self._trendlog(p, o, w):
                return None
        elif t == SCHEDULE:
            if not self._schedule(p, o, w):
                return None
        elif t == CALENDAR:
            o["dates"] = [entry_to_cfg(ce) for ce in p.get("date-list") or []]
        elif t == NOTIFICATION_CLASS:
            self._nc(p, o, w)
        elif t == FILE:
            if p.get("file-type"):
                o["file_type"] = str(p["file-type"])
            fam = _s(p.get("file-access-method"))
            o["access"] = "record" if fam == "record-access" else "stream"
            if p.get("read-only") is not None:
                o["read_only"] = bool(p["read-only"])
            self.warn(f"{w}: file content is not cloned (AtomicReadFile is not used); the file starts empty")
        elif t == PROGRAM:
            ps = _s(p.get("program-state"))
            if ps in ("idle", "running", "halted"):
                o["program_state"] = ps
            elif ps is not None:
                self.warn(f"{w}: program-state {ps!r} not supported, using idle")
            if p.get("instance-of"):
                o["instance_of"] = str(p["instance-of"])
            if p.get("program-location"):
                o["program_location"] = str(p["program-location"])
        elif t == EVENT_ENROLLMENT:
            if not self._ee(p, o, w):
                return None
        elif t in LIFE_SAFETY_TYPES:
            o["value"] = _s(p.get("present-value"))
            o["mode"] = _s(p.get("mode"))
            if p.get("accepted-modes") is not None:
                o["accepted_modes"] = [str(m) for m in p["accepted-modes"]]
            o["operation_expected"] = _s(p.get("operation-expected"))
            o["silenced"] = _s(p.get("silenced"))
            if t == LIFE_SAFETY_ZONE and p.get("zone-members") is not None:
                members = [self.name_of(m.objectIdentifier, f"{w}: zone-members", m.deviceIdentifier)
                           for m in p["zone-members"]]
                o["zone_members"] = [m for m in members if m]
        return {k: v for k, v in o.items() if v is not None}

    def _value(self, t: str, p: Dict[str, Any], o: Dict[str, Any], w: str) -> None:
        commandable = "priority-array" in p
        if commandable and t not in OUTPUT_TYPES:
            o["commandable"] = True
        pv = p.get("relinquish-default") if commandable and "relinquish-default" in p else p.get("present-value")
        if t in ANALOG_TYPES:
            o["value"] = _f(pv)
            o["units"] = _s(p.get("units"))
            o["cov_increment"] = _f(p.get("cov-increment"))
            o["min"], o["max"] = _f(p.get("min-pres-value")), _f(p.get("max-pres-value"))
        elif t in BINARY_TYPES:
            o["value"] = _s(pv)
            o["active_text"], o["inactive_text"] = _s(p.get("active-text")), _s(p.get("inactive-text"))
        else:
            states = [str(s) for s in p.get("state-text") or []]
            n = int(p.get("number-of-states") or len(states) or 2)
            if len(states) != n:
                if states:
                    self.warn(f"{w}: state-text has {len(states)} entries for {n} states, padded")
                else:
                    self.warn(f"{w}: no state-text, using 'State 1'..'State {n}'")
                states = (states + [f"State {i + 1}" for i in range(len(states), n)])[:n]
            o["states"] = states
            o["value"] = int(pv) if pv is not None else 1
        if "notification-class" not in p:
            return
        a: Dict[str, Any] = {}
        nc = self.nc_ref(p["notification-class"])
        if nc is None:
            self.warn(f"{w}: alarm skipped, notification class {int(p['notification-class'])} was not cloned")
            return
        a["notification_class"] = nc
        if t in ANALOG_TYPES:
            a["high_limit"], a["low_limit"] = _f(p.get("high-limit")), _f(p.get("low-limit"))
            a["deadband"] = _f(p.get("deadband"))
            le = _bits(p.get("limit-enable"))
            if le is not None:
                a["limit_enable"] = le[:2]
            if a["high_limit"] is None and a["low_limit"] is None:
                return
        elif t in BINARY_TYPES:
            a["alarm_value"] = _s(p.get("alarm-value"))
            if a["alarm_value"] is None:
                return
        else:
            av = [int(x) for x in p.get("alarm-values") or []]
            fv = [int(x) for x in p.get("fault-values") or []]
            if not av and not fv:
                return
            a["alarm_values"], a["fault_values"] = av or None, fv or None
        if p.get("time-delay") is not None:
            a["time_delay"] = int(p["time-delay"])
        if p.get("time-delay-normal") is not None:
            a["time_delay_normal"] = int(p["time-delay-normal"])
        if p.get("event-enable") is not None:
            a["event_enable"] = _bits(p["event-enable"])[:3]
        nt = _s(p.get("notify-type"))
        if nt in ("alarm", "event"):
            a["notify_type"] = nt
        o["alarm"] = {k: v for k, v in a.items() if v is not None}

    def _loop(self, p: Dict[str, Any], o: Dict[str, Any], w: str) -> bool:
        cv, mv = p.get("controlled-variable-reference"), p.get("manipulated-variable-reference")
        o["controlled_object"] = cv and self.name_of(cv.objectIdentifier, f"{w}: controlled-variable-reference")
        o["manipulated_object"] = mv and self.name_of(mv.objectIdentifier, f"{w}: manipulated-variable-reference")
        if not o["controlled_object"] or not o["manipulated_object"]:
            self.warn(f"{w}: loop skipped (controlled / manipulated object not in this clone)")
            return False
        sr = p.get("setpoint-reference")
        ref = getattr(sr, "setpointReference", None) if sr is not None else None
        if ref is not None:
            o["setpoint_object"] = self.name_of(ref.objectIdentifier, f"{w}: setpoint-reference")
        o.update(value=_f(p.get("present-value")), units=_s(p.get("output-units")), setpoint=_f(p.get("setpoint")),
                 proportional_constant=_f(p.get("proportional-constant")),
                 integral_constant=_f(p.get("integral-constant")),
                 derivative_constant=_f(p.get("derivative-constant")), bias=_f(p.get("bias")),
                 action=_s(p.get("action")), min=_f(p.get("minimum-output")), max=_f(p.get("maximum-output")),
                 cov_increment=_f(p.get("cov-increment")))
        if p.get("update-interval"):
            o["update_interval"] = int(p["update-interval"]) / 1000
        if o["setpoint"] is None and not o.get("setpoint_object"):
            o["setpoint"] = 0.0
        return True

    def _trendlog(self, p: Dict[str, Any], o: Dict[str, Any], w: str) -> bool:
        ref = p.get("log-device-object-property")
        name = ref and self.name_of(ref.objectIdentifier, f"{w}: log-device-object-property", ref.deviceIdentifier)
        if not name:
            self.warn(f"{w}: trend log skipped (no logged object in this device)")
            return False
        o["log_object"] = name
        prop = str(ref.propertyIdentifier)
        if prop != "present-value":
            o["log_property"] = prop
        lt = _s(p.get("logging-type"))
        if lt in ("polled", "cov"):
            o["logging_type"] = lt
        elif lt is not None:
            self.warn(f"{w}: logging-type {lt!r} not supported, using polled")
        if p.get("log-interval"):
            o["log_interval"] = int(p["log-interval"]) / 100  # centiseconds
        if p.get("buffer-size"):
            o["buffer_size"] = min(int(p["buffer-size"]), 100000)
        if p.get("enable") is not None:
            o["enabled"] = bool(p["enable"])
        ci = p.get("client-cov-increment")
        if lt == "cov" and ci is not None and getattr(ci, "realIncrement", None):
            o["client_cov_increment"] = _f(ci.realIncrement)
        return True

    def _schedule(self, p: Dict[str, Any], o: Dict[str, Any], w: str) -> bool:
        cals = [SimpleNamespace(cfg=SimpleNamespace(instance=k[1], name=n))
                for k, n in self.names.items() if k[0] == CALENDAR]
        obj = SimpleNamespace(weeklySchedule=p.get("weekly-schedule"), exceptionSchedule=p.get("exception-schedule"),
                              scheduleDefault=p.get("schedule-default"))
        try:
            o.update(schedule_to_cfg(obj, cals))
        except ValueError as e:
            self.warn(f"{w}: exception schedule dropped ({e})")
            obj.exceptionSchedule = None
            o.update(schedule_to_cfg(obj, cals))
        if not o["exceptions"]:
            o.pop("exceptions")
        targets = []
        for r in p.get("list-of-object-property-references") or []:
            n = self.name_of(r.objectIdentifier, f"{w}: target", r.deviceIdentifier)
            if n:
                targets.append(n)
        if targets:
            o["targets"] = targets
        if p.get("priority-for-writing") is not None:
            o["priority_for_writing"] = int(p["priority-for-writing"])
        ep = p.get("effective-period")
        if ep is not None:
            per = {"from": fmt_date(ep.startDate), "to": fmt_date(ep.endDate)}
            if per != {"from": "*-*-*", "to": "*-*-*"}:
                o["effective_period"] = per
        return True

    def _nc(self, p: Dict[str, Any], o: Dict[str, Any], w: str) -> None:
        if p.get("priority") is not None:
            o["priority"] = [int(x) for x in p["priority"]][:3]
        if p.get("ack-required") is not None:
            o["ack_required"] = _bits(p["ack-required"])[:3]
        recips = []
        for d in p.get("recipient-list") or []:
            if d.recipient.device is None:
                self.warn(f"{w}: recipient by address skipped (addresses of the original network)")
                continue

            def hms(t: Any) -> Optional[str]:
                h, m, sec = tuple(t)[:3]
                return None if 255 in (h, m, sec) else f"{h:02d}:{m:02d}:{sec:02d}"

            days = [WEEKDAYS[i] for i, x in enumerate(d.validDays) if i < 7 and x]
            r = dict(device=int(d.recipient.device[1]), process_id=int(d.processIdentifier),
                     confirmed=bool(d.issueConfirmedNotifications), transitions=_bits(d.transitions)[:3],
                     from_time=hms(d.fromTime), to_time=hms(d.toTime), days=None if len(days) == 7 else days)
            if r["from_time"] == "00:00:00":
                r.pop("from_time")
            if r["to_time"] == "23:59:59":
                r.pop("to_time")
            recips.append({k: v for k, v in r.items() if v is not None})
        o["recipients"] = recips

    def _ee(self, p: Dict[str, Any], o: Dict[str, Any], w: str) -> bool:
        ref = p.get("object-property-reference")
        et = _s(p.get("event-type"))
        ep = p.get("event-parameters")
        mon = ref and self.name_of(ref.objectIdentifier, f"{w}: object-property-reference", ref.deviceIdentifier)
        nc = self.nc_ref(p["notification-class"]) if p.get("notification-class") is not None else None
        if not mon or nc is None or ep is None or et not in ("out-of-range", "change-of-state"):
            self.warn(f"{w}: event enrollment skipped (event type {et!r} not supported, or monitored object / "
                      f"notification class not in this clone)")
            return False
        o.update(monitored_object=mon, event_type=et, notification_class=nc)
        if et == "out-of-range":
            par = ep.outOfRange
            o["event_parameters"] = {"low_limit": _f(par.lowLimit), "high_limit": _f(par.highLimit),
                                     "deadband": _f(par.deadband)}
        else:
            par = ep.changeOfState
            vals: List[Any] = []
            for s in par.listOfValues or []:
                if s.binaryValue is not None:
                    vals.append(str(s.binaryValue))
                elif getattr(s, "unsignedValue", None) is not None:
                    vals.append(int(s.unsignedValue))
                else:
                    self.warn(f"{w}: change-of-state value {s} not supported, skipped")
            o["event_parameters"] = {"alarm_values": vals}
        if par.timeDelay is not None:
            o["time_delay"] = int(par.timeDelay)
        if p.get("event-enable") is not None:
            o["event_enable"] = _bits(p["event-enable"])[:3]
        nt = _s(p.get("notify-type"))
        if nt in ("alarm", "event"):
            o["notify_type"] = nt
        return True


# --------------------------------------------------------------------------- cloning


class Cloner:
    def __init__(self, client: ReadOnlyClient, warn, progress, use_rpm: bool = True,
                 object_lists: Optional[Dict[int, List[ObjectIdentifier]]] = None) -> None:
        self.c, self.warn_, self.progress, self.use_rpm = client, warn, progress, use_rpm
        self.object_lists = object_lists or {}

    async def _props(self, addr: Address, oid: ObjectIdentifier, props: List[str], state: Dict[str, bool]
                     ) -> Dict[str, Any]:
        if state["rpm"]:
            try:
                out: Dict[str, Any] = {}
                step = state.get("chunk", 50)
                for i in range(0, len(props), step):
                    out.update(await self.c.read_multiple(addr, oid, props[i:i + step]))
                return out
            except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
                state["rpm"] = False
                self.progress(f"  ReadPropertyMultiple failed ({e}); using ReadProperty for this device")
        out: Dict[str, Any] = {}
        for prop in props:
            try:
                out[prop] = await self.c.read(addr, oid, prop)
            except ErrorRejectAbortNack:
                pass  # property not present: logged
        return out

    async def _object_list(self, addr: Address, dev_oid: ObjectIdentifier, device_id: int, warn) -> List[Any]:
        """Object-list by index (no segmentation needed), else whole, else from --object-list-file."""
        try:
            n = int(await self.c.read(addr, dev_oid, "object-list", 0))
            return [await self.c.read(addr, dev_oid, "object-list", i) for i in range(1, n + 1)]
        except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
            first = e
        try:
            return list(await self.c.read(addr, dev_oid, "object-list"))
        except (ErrorRejectAbortNack, asyncio.TimeoutError):
            pass
        if device_id in self.object_lists:
            warn(f"object-list not readable ({first}); using --object-list-file")
            return self.object_lists[device_id]
        raise ObjectListError(f"object-list not readable ({first}); give the objects with --object-list-file")

    async def clone_device(self, device_id: int, addr: Address) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []

        def warn(msg: str) -> None:
            warnings.append(f"device {device_id}: {msg}")
            self.warn_(f"device {device_id}: {msg}")

        dev_oid = ObjectIdentifier(("device", device_id))
        state = {"rpm": self.use_rpm}
        dp = await self._props(addr, dev_oid, DEVICE_PROPS, state)
        pss = dp.get("protocol-services-supported")
        if state["rpm"] and pss is not None and len(pss) > RPM_BIT and not pss[RPM_BIT]:
            state["rpm"] = False
        max_apdu = int(dp.get("max-apdu-length-accepted") or 480)
        seg = str(dp.get("segmentation-supported") or "no-segmentation")
        try:  # use the device's own limits (also when it was reached without an I-Am)
            iam = IAmRequest(iAmDeviceIdentifier=dev_oid, maxAPDULengthAccepted=max_apdu,
                             segmentationSupported=seg, vendorID=int(dp.get("vendor-identifier") or 0))
            iam.pduSource = addr
            await self.c.app.device_info_cache.set_device_info(iam)
        except Exception:
            pass
        # devices without segmentation: small RPM requests so the answer fits in one APDU
        state["chunk"] = 50 if seg != "no-segmentation" else max(2, min(12, max_apdu // 60))
        oids = await self._object_list(addr, dev_oid, device_id, warn)
        n = len(oids)
        self.progress(f"device {device_id} ({dp.get('object-name')}) at {addr}: {n} object(s), "
                      f"max-apdu {max_apdu}, segmentation {seg}, {'RPM' if state['rpm'] else 'RP only'}")
        raw: Dict[Tuple[str, int], Dict[str, Any]] = {}
        skipped: Dict[str, int] = {}
        for i, oid in enumerate(oids, 1):
            t = str(oid[0])
            if t not in SUPPORTED_TYPES:
                if t not in SILENT_TYPES:
                    skipped[t] = skipped.get(t, 0) + 1
                continue
            self.progress(f"  [{i}/{n}] {t},{oid[1]}")
            raw[(t, int(oid[1]))] = await self._props(addr, oid, props_for(t), state)
        for t, k in skipped.items():
            warn(f"{k} {t} object(s) skipped (type not supported by the simulator)")
        m = Mapper(device_id, raw, warn)
        objects = []
        for key in raw:
            o = m.map(key)
            if o is not None:
                objects.append(o)
        dev = {"device_id": device_id, "name": str(dp.get("object-name") or f"Device-{device_id}")}
        for k, prop in (("description", "description"), ("vendor_name", "vendor-name"),
                        ("model_name", "model-name"), ("location", "location")):
            if dp.get(prop):
                dev[k] = str(dp[prop])
        if dp.get("vendor-identifier") is not None:
            dev["vendor_id"] = int(dp["vendor-identifier"])
        dev["objects"] = objects
        return validate_device(dev, warn), warnings


def validate_device(dev: Dict[str, Any], warn) -> Dict[str, Any]:
    """Drop what the config model rejects: first an object's alarm, then the object."""
    from .engine import Engine
    from pydantic import ValidationError
    from .config import ObjectConfig

    ok = []
    for o in dev["objects"]:
        try:
            ObjectConfig.model_validate(o)
        except ValidationError as e:
            if "alarm" in o:
                o2 = {k: v for k, v in o.items() if k != "alarm"}
                try:
                    ObjectConfig.model_validate(o2)
                    warn(f"{o['name']}: alarm dropped ({e.errors()[0]['msg']})")
                    ok.append(o2)
                    continue
                except ValidationError:
                    pass
            warn(f"{o['name']}: object skipped ({e.errors()[0]['msg']})")
            continue
        ok.append(o)
    dev["objects"] = ok
    try:
        cfg = SimConfig.model_validate({"devices": [dev]})
        Engine(cfg)._prepare(cfg)
    except Exception as e:  # reported, the file is still written (edit it by hand)
        warn(f"the simulator rejects the generated device config: {e}")
    return dev


def parse_range(s: str) -> Tuple[int, int]:
    lo, _, hi = s.partition("-")
    lo_i, hi_i = int(lo), int(hi or lo)
    if not 0 <= lo_i <= hi_i <= 4194303:
        raise ValueError(f"invalid device range {s!r}")
    return lo_i, hi_i


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sme-bacnet-sim clone",
        description="Read real BACnet devices (Who-Is / ReadProperty / ReadPropertyMultiple only) "
                    "and write a simulator config.")
    ap.add_argument("--who-is", metavar="LOW-HIGH", help="device instance range for Who-Is (e.g. 1000-1099)")
    ap.add_argument("--address", metavar="IP[:PORT]",
                    help="unicast Who-Is to this device; with --network: the BACnet router to that network")
    ap.add_argument("--network", type=int, metavar="N", help="remote network number (Who-Is to N:*)")
    ap.add_argument("--devices", metavar="ID,...", help="only clone these device instances")
    ap.add_argument("--ip", help='local address with prefix, e.g. "192.168.1.10/24" (default: auto)')
    ap.add_argument("--port", type=int, default=47808, help="local BACnet/IP UDP port (default 47808)")
    ap.add_argument("--foreign-bbmd", metavar="HOST[:PORT]",
                    help="register as a foreign device with this BBMD first (cross-subnet: the BBMD forwards the "
                         "broadcast I-Am answers to this client; IPv4, default port 47808)")
    ap.add_argument("--foreign-ttl", type=int, default=300, metavar="SECONDS",
                    help="foreign device Time-to-Live in seconds (default 300)")
    ap.add_argument("--rate", type=float, default=5.0, help="max requests per second (default 5)")
    ap.add_argument("--timeout", type=float, default=3.0, help="seconds per request / Who-Is wait (default 3)")
    ap.add_argument("--retries", type=int, default=2, help="retries per request (default 2)")
    ap.add_argument("--client-device-id", type=int, default=4194300,
                    help="device instance of the clone client itself (default 4194300)")
    ap.add_argument("--object-list-file", metavar="JSON",
                    help='object table for devices whose object-list cannot be read: [{"deviceID": 1011, '
                         '"objectList": [{"objectType": "analogInput", "objectInstance": 1}, ...]}, ...]')
    ap.add_argument("--no-rpm", action="store_true", help="never use ReadPropertyMultiple")
    ap.add_argument("--keep-ids", action=argparse.BooleanOptionalAction, default=True,
                    help="keep the device instances (default); --no-keep-ids renumbers from 1001")
    ap.add_argument("--resume", action="store_true", help="keep the devices already in the output file, skip them")
    ap.add_argument("-o", "--output", required=True, help="output YAML file")
    return ap


def route_ip(host: str) -> Optional[str]:
    """Local IPv4 address the OS uses to reach ``host`` (no packet is sent). Matters for VPN / overlay routes
    (e.g. a Tailscale subnet route): bound to the LAN address, the requests would leave without a usable source."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 47808))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def check_port(ip: str, port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((ip.split("/")[0], port))
    except OSError as e:
        raise OSError(f"UDP port {port} on {ip.split('/')[0]} is in use ({e.strerror or e}); another BACnet "
                      f"stack (a BMS tool, a gateway such as BAC0, a simulator) is probably running. Use --port 47809 "
                      f"(or another free port), or stop the program that holds port {port} first") from None
    finally:
        s.close()


def load_object_lists(path: str) -> Dict[int, List[ObjectIdentifier]]:
    """Object tables of a JSON file: [{"deviceID": N, "objectList": [{"objectType", "objectInstance"}, ...]}]
    (objectType in bacpypes camelCase, e.g. analogInput, or hyphenated; other keys are ignored)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    out: Dict[int, List[ObjectIdentifier]] = {}
    for d in data:
        try:
            out[int(d["deviceID"])] = [ObjectIdentifier((o["objectType"], int(o["objectInstance"])))
                                       for o in d.get("objectList") or []]
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"{path}: expected [{{deviceID, objectList: [{{objectType, objectInstance}}]}}] "
                             f"({e})") from None
    return out


def write_output(path: Path, devices: List[Dict[str, Any]], source: str, n_warn: int) -> None:
    head = (f"# Cloned by sme-bacnet-sim clone ({source}) at {_dt.datetime.now().isoformat(timespec='seconds')}\n"
            f"# {n_warn} warning(s): see {path.name}.log.jsonl\n")
    text = head + yaml.safe_dump({"devices": devices}, allow_unicode=True, sort_keys=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


async def run_clone(args: argparse.Namespace, progress=None) -> Dict[str, Any]:
    """Run a clone; returns {"devices", "warnings", "services"}. The YAML is written after every device."""
    from .engine import detect_ip

    def say(msg: str) -> None:
        (progress or (lambda m: print(m, file=sys.stderr, flush=True)))(msg)

    if not (args.who_is or args.address or args.devices):
        raise ValueError("give a target: --who-is LOW-HIGH, --address IP[:PORT] and/or --devices ID,...")
    wanted = {int(x) for x in args.devices.split(",") if x.strip()} if args.devices else None
    low = high = None
    if args.who_is:
        low, high = parse_range(args.who_is)
    elif wanted:
        low, high = min(wanted), max(wanted)
    if args.rate <= 0:
        raise ValueError("--rate must be positive")

    out = Path(args.output)
    log_path = out.with_name(out.name + ".log.jsonl")
    devices: List[Dict[str, Any]] = []
    if args.resume and out.exists():
        devices = (yaml.safe_load(out.read_text(encoding="utf-8")) or {}).get("devices") or []
    done = {d["device_id"] for d in devices}
    warnings: List[str] = []
    logf = log_path.open("a" if args.resume else "w", encoding="utf-8")

    def log(**kw: Any) -> None:
        kw = {"ts": _dt.datetime.now().isoformat(timespec="milliseconds"), **kw}
        logf.write(json.dumps(kw, ensure_ascii=False, default=str) + "\n")
        logf.flush()

    def warn(msg: str) -> None:
        warnings.append(msg)
        log(kind="warning", message=msg)
        say(f"warning: {msg}")

    target = getattr(args, "foreign_bbmd", None) or args.address
    ip = args.ip or (route_ip(parse_host_port(target).split(":")[0]) if target else None) or detect_ip()
    if not args.ip and target and ip.split("/")[0] != detect_ip().split("/")[0]:
        say(f"using local address {ip.split('/')[0]} (the route to {target} leaves through that interface; "
            f"override with --ip)")
    if "/" not in ip:
        from .engine import with_prefix
        ip = with_prefix(ip)
    check_port(ip, args.port)
    dev_obj = DeviceObject(objectIdentifier=("device", args.client_device_id), objectName="sme-bacnet-sim-clone",
                           vendorIdentifier=999, maxApduLengthAccepted=1476, segmentationSupported="segmented-both",
                           apduTimeout=int(args.timeout * 1000), numberOfApduRetries=args.retries)
    port_kw: Dict[str, Any] = {}
    bbmd = getattr(args, "foreign_bbmd", None)
    if bbmd:
        bbmd = parse_host_port(bbmd)
        if not 30 <= args.foreign_ttl <= 65535:
            raise ValueError("--foreign-ttl must be 30..65535 seconds")
        port_kw = dict(bacnetIPMode="foreign", fdBBMDAddress=HostNPort(bbmd), fdSubscriptionLifetime=args.foreign_ttl)
    app = ReadOnlyApplication.from_object_list([
        dev_obj, NetworkPortObject(f"{ip}:{args.port}", objectIdentifier=("network-port", 1), objectName="ip",
                                   **port_kw)])
    client = ReadOnlyClient(app, args.rate, args.timeout, args.retries, log)
    result = {"devices": devices, "warnings": warnings, "services": client.services}
    fd_link = next((ll for ll in app.link_layers.values() if isinstance(ll, BIPForeign)), None) if bbmd else None
    try:
        if fd_link is not None:
            await register_foreign(fd_link, bbmd, args.foreign_ttl, max(args.timeout, 5.0), log, say)
        if args.network is not None and args.address:
            router = Address(parse_host_port(args.address))
            await app.nsap.update_router_references(None, router, [args.network])  # local table only
            dest = Address(f"{args.network}:*")
        elif args.network is not None:
            dest = Address(f"{args.network}:*")
        elif args.address:
            dest = Address(parse_host_port(args.address))
        else:
            dest = LocalBroadcast()
        found: Dict[int, Address] = {}
        direct = bool(args.address) and args.network is None
        if direct and wanted:  # known instances at a known address: no Who-Is at all
            found = {d: dest for d in wanted}
        else:
            say(f"Who-Is {low if low is not None else ''}-{high if high is not None else ''} to {dest}")
            for i in await client.who_is(low, high, dest):
                found.setdefault(int(i.iAmDeviceIdentifier[1]), i.pduSource)
        if not found and direct:  # no I-Am (e.g. broadcast to 47808 while we use another port)
            try:
                oid = await client.read(dest, ObjectIdentifier(("device", 4194303)), "object-identifier")
                found = {int(oid[1]): dest}
                say(f"device {int(oid[1])} found at {dest} by reading device,4194303")
            except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
                warn(f"{dest}: no I-Am and device,4194303 not readable ({e or type(e).__name__}); "
                     f"give the instance with --devices")
        if not found and not direct:
            hint = (f" The I-Am answers may go to port 47808 while this client listens on {args.port}:"
                    if args.port != 47808 else "")
            warn(f"no device answered Who-Is.{hint} try --address <device IP> (unicast, with --devices ID), "
                 f"or temporarily stop the program that holds port 47808")
        if wanted is not None:
            for d in sorted(wanted - set(found)):
                warn(f"device {d} did not answer Who-Is")
            found = {k: v for k, v in found.items() if k in wanted}
        say(f"{len(found)} device(s): {', '.join(map(str, sorted(found))) or '-'}")
        source = ", ".join(f"{k}={getattr(args, k, None)}"
                           for k in ("who_is", "address", "network", "devices", "foreign_bbmd")
                           if getattr(args, k, None) is not None)
        cloner = Cloner(client, warn, say, use_rpm=not args.no_rpm,
                        object_lists=load_object_lists(args.object_list_file) if args.object_list_file else None)
        next_id = max([1000] + [d["device_id"] for d in devices]) + 1
        for dev_id in sorted(found):
            if dev_id in done:
                say(f"device {dev_id}: already in {out.name}, skipped (--resume)")
                continue
            try:
                dev, _ = await cloner.clone_device(dev_id, found[dev_id])
            except (ErrorRejectAbortNack, asyncio.TimeoutError, ObjectListError) as e:
                warn(f"device {dev_id}: not cloned ({e or type(e).__name__})")
                continue
            if not args.keep_ids:
                dev["device_id"], next_id = next_id, next_id + 1
            if dev["device_id"] == SimConfig().network.router.device_id:
                warn(f"device {dev_id}: device id equals the simulator's router id; change network.router.device_id")
            devices.append(dev)
            write_output(out, devices, source, len(warnings))
            say(f"device {dev_id}: {len(dev['objects'])} object(s) written to {out}")
        if not found:
            write_output(out, devices, source, len(warnings))
    finally:
        if fd_link is not None and fd_link.bbmdRegistrationStatus == 0:
            fd_link.unregister()  # Register-Foreign-Device with TTL 0
            log(kind="foreign", bbmd=bbmd, status="unregistered")
            await asyncio.sleep(0.2)  # let the datagram leave before the socket closes
        app.close()
        logf.close()
    return result


async def register_foreign(link: BIPForeign, bbmd: str, ttl: int, wait: float, log, say) -> None:
    """Wait for the BBMD's BVLC-Result to the Register-Foreign-Device that bacpypes3 sends on start-up."""
    say(f"registering as foreign device with BBMD {bbmd} (TTL {ttl} s)")
    log(kind="foreign", bbmd=bbmd, ttl=ttl, status="registering")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        code = link.bbmdRegistrationStatus  # -1 in process, 0 OK, >0 BVLC result code (NAK)
        if code == 0:
            log(kind="foreign", bbmd=bbmd, status="ok")
            say(f"registered with BBMD {bbmd}")
            return
        if code > 0:
            log(kind="foreign", bbmd=bbmd, status="nak", result_code=code)
            raise ValueError(f"BBMD {bbmd} rejected the foreign device registration (BVLC-Result 0x{code:04X}); "
                             f"is it a BBMD that accepts foreign devices?")
        await asyncio.sleep(0.05)
    log(kind="foreign", bbmd=bbmd, status="timeout")
    raise ValueError(f"no answer from BBMD {bbmd} to Register-Foreign-Device within {wait:.0f} s "
                     f"(wrong address/port, firewall, or not a BBMD)")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        res = asyncio.run(run_clone(args))
    except KeyboardInterrupt:
        print(f"interrupted; the devices read so far are in {args.output}", file=sys.stderr)
        return 130
    except (ValueError, OSError) as e:
        print(f"clone error: {e}", file=sys.stderr)
        return 2
    print(f"{len(res['devices'])} device(s) in {args.output}, {len(res['warnings'])} warning(s)", file=sys.stderr)
    return 0
