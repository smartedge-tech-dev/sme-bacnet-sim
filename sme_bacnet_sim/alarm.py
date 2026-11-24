"""Alarms: Notification Class objects and intrinsic reporting on the simulated clock.

What bacpypes3 0.1.0 provides and what is replaced
--------------------------------------------------
* bacpypes3 ships intrinsic-reporting classes (``AnalogInputObjectIR`` ...) whose event algorithms
  (``bacpypes3/local/event.py``) start time delays with ``loop.call_later`` (wall clock, so they ignore
  the simulation speed and pause) and stamp events with ``Time.now()``.  The application layer has no
  server side for AcknowledgeAlarm, GetEventInformation, GetAlarmSummary or GetEnrollmentSummary.
* The simulator therefore builds alarmed objects from the plain object classes (they already declare every
  event property: highLimit, eventState, ackedTransitions, ...), evaluates OUT_OF_RANGE (analog),
  CHANGE_OF_STATE (binary / multi-state) and the multi-state fault check itself on the sim clock, and
  builds / serves the event APDUs with the bacpypes3 data types.
* Limits / deadband / time delays are read back from the object on every evaluation, so BACnet writes to
  them take effect.  Event_Enable, Limit_Enable, Alarm_Value(s) and Notification_Class are kept in Python and
  mirrored to the object; the engine calls ``sync_from_object`` after a BACnet write so client writes to them
  are honoured (and persisted in the config).  Acked_Transitions is read-only.
* CHANGE_OF_STATE re-alarm: an object already OFFNORMAL whose value changes to a *different* alarm value
  (and stays there for Time_Delay) makes a new OFFNORMAL -> OFFNORMAL transition (ASHRAE 135 13.3.2 c).
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple

from bacpypes3.apdu import (
    ConfirmedEventNotificationRequest, GetAlarmSummaryACK, GetEnrollmentSummaryACK, UnconfirmedEventNotificationRequest,
)
from bacpypes3.basetypes import (
    DateTime, DaysOfWeek, Destination, DeviceAddress, GetEventInformationEventSummary,
    NotificationParameters, NotificationParametersChangeOfReliabilityType, NotificationParametersChangeOfState,
    NotificationParametersOutOfRange, PropertyStates, Recipient, TimeStamp,
)
from bacpypes3.local.object import Object as LocalObject
from bacpypes3.object import NotificationClassObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier, Time

from .config import ANALOG_TYPES, BINARY_TYPES, WEEKDAYS, ObjectConfig, RecipientConfig, ms_index, parse_time

def _allow_empty_list_acks() -> None:
    """bacpypes3 0.1.0 cannot decode a GetAlarmSummary / GetEnrollmentSummary ACK with an empty list.

    An empty SEQUENCE OF encodes as zero octets, so the ACK has no tags at all; bacpypes3 declares the list as
    a required element and its decoder raises "required element" (reported by the requesting application as
    Error communication / invalid-tag).  A filtered GetEnrollmentSummary (enrollmentFilter, priority, ...) that
    matches nothing hits this.  The server side always encoded correctly; this makes bacpypes3 *clients* in
    this process (tests, router tools) accept the empty ACK.  The decoded attribute is then None (= empty).
    """
    for ack, attr in ((GetAlarmSummaryACK, "listOfAlarmSummaries"),
                      (GetEnrollmentSummaryACK, "listOfEnrollmentSummaries")):
        element = ack._elements[attr]
        if not element._optional:
            ack._elements[attr] = type(element.__name__, (element,), {"_optional": True})


_allow_empty_list_acks()

TO_OFFNORMAL, TO_FAULT, TO_NORMAL = 0, 1, 2
UNSPECIFIED_TIME = (255, 255, 255, 255)


def transition_index(state: str) -> int:
    """Event state reached by a transition -> index into the 3-element event arrays."""
    return TO_NORMAL if state == "normal" else TO_FAULT if state == "fault" else TO_OFFNORMAL


def timestamp(ts: Optional[float]) -> TimeStamp:
    """Epoch seconds (sim clock) -> BACnetTimeStamp; None -> unspecified time (no transition yet)."""
    if ts is None:
        return TimeStamp(time=Time(UNSPECIFIED_TIME))
    return TimeStamp(datetime=DateTime.now(ts))


class SimNotificationClassObject(LocalObject, NotificationClassObject):
    async def _post_init(self):
        # the engine links objects to notification classes itself
        pass


_ALARM_CLASSES: dict = {}


def alarm_class(cls: type) -> type:
    """Subclass of a value object class that skips bacpypes3's notification-class lookup in _post_init.

    That lookup runs as a task and fails when an object is built for validation only (no application).
    """
    if cls not in _ALARM_CLASSES:
        async def _post_init(self):
            pass

        _ALARM_CLASSES[cls] = type(cls.__name__ + "Alarm", (cls,), {"_post_init": _post_init})
    return _ALARM_CLASSES[cls]


# --------------------------------------------------------------------------- notification class


class NCRecipient:
    def __init__(self, cfg: RecipientConfig, network_number: int):
        self.cfg = cfg
        self.address: Optional[Address] = None
        if cfg.address is not None:
            s = cfg.address.strip()
            # "<ip>:<port>" is a station on the BACnet/IP side of the router
            self.address = Address(f"{network_number}:{s}" if "." in s and s.count(":") == 1 else s)
            if self.address.addrNet is None:
                raise ValueError(f"recipient address {s!r}: expected '<net>:<mac>' or '<ip>:<port>'")
        self.from_t = parse_time(cfg.from_time) if cfg.from_time is not None else (0, 0, 0)
        self.to_t = parse_time(cfg.to_time) if cfg.to_time is not None else (23, 59, 59)
        days = WEEKDAYS if not cfg.days else [str(d).strip().lower()[:3] for d in cfg.days]
        self.days = [d in days for d in WEEKDAYS]

    def destination(self) -> Destination:
        if self.cfg.device is None:
            rcp = Recipient(address=DeviceAddress(networkNumber=self.address.addrNet,
                                                  macAddress=self.address.addrAddr))
        else:
            rcp = Recipient(device=ObjectIdentifier(("device", self.cfg.device)))
        return Destination(
            validDays=DaysOfWeek([int(x) for x in self.days]),
            fromTime=Time(self.from_t + (0,)),
            toTime=Time(self.to_t + (99 if self.to_t == (23, 59, 59) else 0,)),
            recipient=rcp,
            processIdentifier=self.cfg.process_id,
            issueConfirmedNotifications=self.cfg.confirmed,
            transitions=[int(x) for x in self.cfg.transitions],
        )

    def accepts(self, idx: int, ts: float) -> bool:
        """Transition enabled and sim-clock time inside the valid days / time window."""
        lt = time.localtime(ts)
        return bool(self.cfg.transitions[idx]) and self.days[lt.tm_wday] \
            and self.from_t <= (lt.tm_hour, lt.tm_min, lt.tm_sec) <= self.to_t

    def label(self) -> str:
        return f"device {self.cfg.device}" if self.cfg.device is not None else str(self.address)


class NotificationClass:
    def __init__(self, device_id: int, oc: ObjectConfig, network_number: int):
        self.device_id = device_id
        self.cfg = oc
        self.number = oc.instance
        self.priority = list(oc.priority or [100, 100, 200])
        self.ack_required = list(oc.ack_required if oc.ack_required is not None else [True, True, False])
        self.recipients = [NCRecipient(r, network_number) for r in (oc.recipients or [])]
        kw: dict = dict(
            objectIdentifier=("notification-class", oc.instance),
            objectName=oc.name,
            notificationClass=oc.instance,
            priority=self.priority,
            ackRequired=[int(x) for x in self.ack_required],
            recipientList=[r.destination() for r in self.recipients],
        )
        if oc.description:
            kw["description"] = oc.description
        self.obj = SimNotificationClassObject(**kw)


# --------------------------------------------------------------------------- intrinsic reporting


class Alarm:
    """Event state machine of one value object (sim-clock time delays)."""

    def __init__(self, point: Any, nc: NotificationClass):
        self.point = point
        self.nc = nc
        oc = point.cfg
        a = oc.alarm
        self.cfg = a
        t = oc.type
        self.kind = "out-of-range" if t in ANALOG_TYPES else "change-of-state"
        if t in BINARY_TYPES:
            self.alarm_values = [1 if ms_index(a.alarm_value, ["inactive", "active"], oc) == 2 else 0]
        elif t in ANALOG_TYPES:
            self.alarm_values = []
        else:
            self.alarm_values = [ms_index(v, oc.states, oc) for v in (a.alarm_values or [])]
        self.fault_values = [ms_index(v, oc.states, oc) for v in (a.fault_values or [])]
        if t in ANALOG_TYPES:
            le = a.limit_enable or [a.low_limit is not None, a.high_limit is not None]
            self.limit_enable = [bool(x) for x in le]
        else:
            self.limit_enable = [False, False]
        self.event_enable = [bool(x) for x in a.event_enable]
        self.state = "normal"
        # ((target state, re-alarm value or None), sim time the condition started)
        self.pending: Optional[Tuple[Tuple[str, Any], float]] = None
        self.alarm_pv: Any = None  # value that caused the last transition to OFFNORMAL (change-of-state)
        self.timestamps: List[Optional[float]] = [None, None, None]
        self.acked = [True, True, True]
        self._init_properties()

    @property
    def obj(self) -> Any:
        return self.point.obj

    @property
    def notify_type(self) -> str:
        return self.cfg.notify_type

    def _init_properties(self) -> None:
        o, a = self.obj, self.cfg
        o.notificationClass = self.nc.number
        o.timeDelay = int(a.time_delay)
        if a.time_delay_normal is not None:
            o.timeDelayNormal = int(a.time_delay_normal)
        o.eventEnable = [int(x) for x in self.event_enable]
        o.notifyType = a.notify_type
        o.eventDetectionEnable = True
        if self.kind == "out-of-range":
            o.highLimit = float(a.high_limit if a.high_limit is not None else 0.0)
            o.lowLimit = float(a.low_limit if a.low_limit is not None else 0.0)
            o.deadband = float(a.deadband)
            o.limitEnable = [int(x) for x in self.limit_enable]
        elif self.point.cfg.type in BINARY_TYPES:
            o.alarmValue = "active" if self.alarm_values[0] else "inactive"
        else:
            o.alarmValues = list(self.alarm_values)
            if self.fault_values:
                o.faultValues = list(self.fault_values)
        self._publish()

    def _publish(self) -> None:
        o = self.obj
        o.eventState = self.state
        o.ackedTransitions = [int(x) for x in self.acked]
        o.eventTimeStamps = [timestamp(t) for t in self.timestamps]
        in_alarm = self.state != "normal"
        o.statusFlags = [int(in_alarm), int(self.state == "fault"), 0, int(bool(self._out_of_service()))]

    def _out_of_service(self) -> bool:
        return bool(self.obj.outOfService)

    def _limits(self) -> Tuple[float, float, float]:
        """(high limit, low limit, deadband) of the out-of-range algorithm."""
        o = self.obj
        return float(o.highLimit), float(o.lowLimit), float(o.deadband)

    def _delays(self) -> Tuple[int, int]:
        """(time delay, time delay normal) in sim seconds."""
        td = int(self.obj.timeDelay or 0)
        tdn = self.obj.timeDelayNormal
        return td, int(tdn) if tdn is not None else td

    # ---- evaluation

    def _target(self, pv: Any) -> str:
        if self.fault_values and pv in self.fault_values:
            return "fault"
        if self.state == "fault":
            return "normal"  # leave fault through normal, then re-evaluate
        if self.kind == "change-of-state":
            return "offnormal" if pv in self.alarm_values else "normal"
        hi, lo, db = self._limits()
        lo_en, hi_en = self.limit_enable
        if self.state == "high-limit":
            if lo_en and pv < lo:
                return "low-limit"
            return "normal" if (not hi_en or pv < hi - db) else "high-limit"
        if self.state == "low-limit":
            if hi_en and pv > hi:
                return "high-limit"
            return "normal" if (not lo_en or pv > lo + db) else "low-limit"
        if hi_en and pv > hi:
            return "high-limit"
        if lo_en and pv < lo:
            return "low-limit"
        return "normal"

    def evaluate(self, sim_time: float, ts: float) -> Optional[Tuple[str, str]]:
        """Run one evaluation at sim time ``sim_time`` (epoch ``ts``); returns (from, to) on a transition."""
        pv = self.point.read()
        target = self._target(pv)
        realarm = (self.kind == "change-of-state" and target == self.state == "offnormal"
                   and pv != self.alarm_pv)
        if target == self.state and not realarm:
            self.pending = None
            return None
        key = (target, pv if realarm else None)
        if self.pending is None or self.pending[0] != key:
            self.pending = (key, sim_time)
        if "fault" in (target, self.state):
            delay = 0
        elif target == "normal":
            delay = self._delays()[1]
        else:
            delay = self._delays()[0]
        if sim_time - self.pending[1] + 1e-6 < delay:
            return None
        self.pending = None
        old = self.state
        idx = transition_index(target)
        self.state = target
        if target == "offnormal":
            self.alarm_pv = pv
        self.timestamps[idx] = ts
        self.acked[idx] = not self.nc.ack_required[idx]
        if target == "fault":
            self.obj.reliability = "multi-state-fault"
        elif old == "fault":
            self.obj.reliability = "no-fault-detected"
        self._publish()
        return old, target

    def sync_from_object(self, nc_ref: Any = None) -> Tuple[bool, Optional[str]]:
        """Pick up BACnet writes to the alarm properties of the object.

        Updates the Python state and ``self.cfg`` (``nc_ref``: new notification_class reference, already
        validated by the engine).  Returns (config changed, error); on an invalid value every alarm property
        is restored from the last valid config.
        """
        o, a = self.obj, self.cfg
        upd: dict = {}
        if nc_ref is not None:
            upd["notification_class"] = nc_ref
        ee = [bool(x) for x in o.eventEnable]
        if ee != self.event_enable:
            upd["event_enable"] = ee
        td = int(o.timeDelay or 0)
        if td != a.time_delay:
            upd["time_delay"] = td
        tdn = o.timeDelayNormal
        if tdn is not None and (a.time_delay_normal is None or int(tdn) != a.time_delay_normal):
            upd["time_delay_normal"] = int(tdn)
        err = None
        t = self.point.cfg.type
        if self.kind == "out-of-range":
            le = [bool(x) for x in o.limitEnable]
            if le != self.limit_enable:
                upd["limit_enable"] = le
            for key, attr in (("high_limit", "highLimit"), ("low_limit", "lowLimit")):
                cur = getattr(a, key)
                v = float(getattr(o, attr))
                if v != float(cur if cur is not None else 0.0):
                    upd[key] = v
            db = float(o.deadband)
            if db != a.deadband:
                upd["deadband"] = db
                if db < 0:
                    err = f"deadband {db} < 0"
        elif t in BINARY_TYPES:
            av = "active" if str(o.alarmValue) == "active" else "inactive"
            if [int(av == "active")] != self.alarm_values:
                upd["alarm_value"] = av
        else:
            avs = [int(x) for x in (o.alarmValues or [])]
            if avs != self.alarm_values:
                n = len(self.point.cfg.states or [])
                bad = [v for v in avs if not 1 <= v <= n]
                if bad:
                    err = f"alarm-values {bad} outside 1..{n}"
                upd["alarm_values"] = avs
        if err is not None:
            self._init_properties()
            return False, err
        if not upd:
            self._publish()  # undo writes to read-only mirrors (Acked_Transitions via WPM)
            return False, None
        self.cfg = a.model_copy(update=upd)
        self.event_enable = [bool(x) for x in self.cfg.event_enable]
        if self.kind == "out-of-range":
            self.limit_enable = [bool(x) for x in (self.cfg.limit_enable or self.limit_enable)]
        elif t in BINARY_TYPES:
            self.alarm_values = [1 if self.cfg.alarm_value == "active" else 0]
        else:
            self.alarm_values = list(self.cfg.alarm_values or [])
        self._publish()
        return True, None

    def acknowledge(self, idx: int) -> bool:
        """Set the acked bit of one transition; returns False when it was already acknowledged."""
        if self.acked[idx]:
            return False
        self.acked[idx] = True
        self._publish()
        return True

    @property
    def unacked(self) -> bool:
        return not all(self.acked)

    def priority(self, state: Optional[str] = None) -> int:
        return int(self.nc.priority[transition_index(state or self.state)])

    # ---- APDUs

    def event_type(self, frm: str, to: str) -> str:
        return "change-of-reliability" if "fault" in (frm, to) else self.kind

    def event_values(self, frm: str, to: str) -> NotificationParameters:
        o = self.obj
        flags = o.statusFlags
        if "fault" in (frm, to):
            return NotificationParameters(changeOfReliability=NotificationParametersChangeOfReliabilityType(
                reliability=o.reliability, statusFlags=flags, propertyValues=[]))
        if self.kind == "out-of-range":
            low = to == "low-limit" or (to == "normal" and frm == "low-limit")
            return NotificationParameters(outOfRange=NotificationParametersOutOfRange(
                exceedingValue=float(o.presentValue), statusFlags=flags, deadband=float(o.deadband),
                exceededLimit=float(o.lowLimit if low else o.highLimit)))
        if self.point.cfg.type in BINARY_TYPES:
            ns = PropertyStates(binaryValue=o.presentValue)
        else:
            ns = PropertyStates(unsignedValue=int(o.presentValue))
        return NotificationParameters(changeOfState=NotificationParametersChangeOfState(newState=ns, statusFlags=flags))

    def notification(self, device_id: int, rcp: NCRecipient, frm: str, to: str, ts: float, destination: Address):
        idx = transition_index(to)
        cls = ConfirmedEventNotificationRequest if rcp.cfg.confirmed else UnconfirmedEventNotificationRequest
        return cls(
            processIdentifier=rcp.cfg.process_id,
            initiatingDeviceIdentifier=ObjectIdentifier(("device", device_id)),
            eventObjectIdentifier=ObjectIdentifier((self.point.cfg.type, self.point.cfg.instance)),
            timestamp=timestamp(ts),
            notificationClass=self.nc.number,
            priority=self.priority(to),
            eventType=self.event_type(frm, to),
            messageText=f"{self.point.cfg.name} {to}",
            notifyType=self.notify_type,
            ackRequired=bool(self.nc.ack_required[idx]),
            fromState=frm,
            toState=to,
            eventValues=self.event_values(frm, to),
            destination=destination,
        )

    def event_summary(self) -> GetEventInformationEventSummary:
        return GetEventInformationEventSummary(
            objectIdentifier=ObjectIdentifier((self.point.cfg.type, self.point.cfg.instance)),
            eventState=self.state,
            acknowledgedTransitions=[int(x) for x in self.acked],
            eventTimestamps=[timestamp(t) for t in self.timestamps],
            notifyType=self.notify_type,
            eventEnable=[int(x) for x in self.event_enable],
            eventPriorities=[int(p) for p in self.nc.priority],
        )
