"""Event Enrollment objects: algorithmic reporting on a monitored object of the same device.

An Event Enrollment watches the present-value of another object and runs the same event state machine as
intrinsic reporting (``alarm.Alarm``: sim-clock time delays, Notification Class recipients, AcknowledgeAlarm,
GetEventInformation / GetAlarmSummary / GetEnrollmentSummary).  Only the parameters differ: they come from the
Event_Parameters property (bacpypes3 ``EventParameter`` choice) instead of High_Limit / Alarm_Values / ... of
the monitored object.

Supported event types: OUT_OF_RANGE (analog-like monitored objects, both limits always enabled) and
CHANGE_OF_STATE (binary / multi-state monitored objects).  BACnet writes to Event_Parameters, Event_Enable,
Notify_Type, Time_Delay_Normal and Notification_Class are taken over and written back to the config.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bacpypes3.basetypes import (
    DeviceObjectPropertyReference, EventParameter, EventParameterChangeOfState, EventParameterOutOfRange,
    NotificationParameters, NotificationParametersChangeOfState, NotificationParametersOutOfRange, PropertyStates,
)
from bacpypes3.local.object import Object as LocalObject
from bacpypes3.object import EventEnrollmentObject
from bacpypes3.primitivedata import ObjectIdentifier

from .alarm import Alarm, NotificationClass
from .config import BINARY_TYPES, MULTISTATE_TYPES, REAL_TYPES, ObjectConfig, ms_index


class SimEventEnrollmentObject(LocalObject, EventEnrollmentObject):
    async def _post_init(self):
        # the engine links the object to its notification class itself
        pass


class EventEnrollment:
    """Runtime of one Event Enrollment object; plays the role of ``Alarm.point``."""

    def __init__(self, device_id: int, oc: ObjectConfig, target: Any):
        self.device_id = device_id
        self.cfg = oc
        self.target = target  # monitored engine Point
        kw: Dict[str, Any] = dict(
            objectIdentifier=(oc.type, oc.instance), objectName=oc.name, eventType=oc.event_type,
            notifyType=oc.notify_type or "alarm", eventState="normal", statusFlags=[0, 0, 0, 0],
            reliability="no-fault-detected", eventDetectionEnable=True,
        )
        if oc.description:
            kw["description"] = oc.description
        self.obj = SimEventEnrollmentObject(**kw)
        self.alarm: Optional[EnrollmentAlarm] = None

    @property
    def key(self) -> str:
        return f"{self.cfg.type}:{self.cfg.instance}"

    def read(self) -> Any:
        return self.target.read()

    def status(self) -> Dict[str, Any]:
        a = self.alarm
        return {"value": self.read(), "event_state": a.state, "unacked": a.unacked}


def check_target(oc: ObjectConfig, target: Any) -> None:
    """Monitored object must suit the event type; alarm values must be states of it."""
    t = target.cfg.type
    if oc.event_type == "out-of-range" and t not in REAL_TYPES:
        raise ValueError(f"{oc.name}: out-of-range needs an analog monitored object, {target.cfg.name} is {t}")
    if oc.event_type == "change-of-state":
        if t not in BINARY_TYPES and t not in MULTISTATE_TYPES:
            raise ValueError(f"{oc.name}: change-of-state needs a binary / multi-state monitored object, "
                             f"{target.cfg.name} is {t}")
        for v in oc.event_parameters["alarm_values"]:
            _state(v, target)


def _state(v: Any, target: Any) -> int:
    """Alarm value -> value compared with Point.read() (binary 0 / 1, multi-state 1..n)."""
    tc = target.cfg
    if tc.type in BINARY_TYPES:
        return ms_index(v, None, tc) - 1
    return ms_index(v, tc.states)


class EnrollmentAlarm(Alarm):
    """Alarm state machine whose parameters live in the Event Enrollment object."""

    def __init__(self, point: EventEnrollment, nc: NotificationClass):
        self.point = point
        self.nc = nc
        self.cfg = point.cfg
        self.kind = point.cfg.event_type
        self.fault_values: List[int] = []  # fault detection of event enrollments is not supported
        self.limit_enable = [True, True]
        self._load_cfg()
        self.state = "normal"
        self.pending: Optional[Tuple[Tuple[str, Any], float]] = None
        self.alarm_pv: Any = None
        self.timestamps: List[Optional[float]] = [None, None, None]
        self.acked = [True, True, True]
        self._init_properties()

    def _load_cfg(self) -> None:
        c = self.cfg
        self.event_enable = [bool(x) for x in (c.event_enable or [True, True, True])]
        if self.kind == "change-of-state":
            self.alarm_values = [_state(v, self.point.target) for v in c.event_parameters["alarm_values"]]
        else:
            self.alarm_values = []

    @property
    def notify_type(self) -> str:
        return self.cfg.notify_type or "alarm"

    @property
    def _binary(self) -> bool:
        return self.point.target.cfg.type in BINARY_TYPES

    def _parameters(self) -> EventParameter:
        c = self.cfg
        ep, td = c.event_parameters, int(c.time_delay or 0)
        if self.kind == "out-of-range":
            return EventParameter(outOfRange=EventParameterOutOfRange(
                timeDelay=td, lowLimit=float(ep["low_limit"]), highLimit=float(ep["high_limit"]),
                deadband=float(ep.get("deadband", 0.0))))
        if self._binary:
            states = [PropertyStates(binaryValue="active" if v else "inactive") for v in self.alarm_values]
        else:
            states = [PropertyStates(unsignedValue=v) for v in self.alarm_values]
        return EventParameter(changeOfState=EventParameterChangeOfState(timeDelay=td, listOfValues=states))

    def _init_properties(self) -> None:
        o, c, tc = self.obj, self.cfg, self.point.target.cfg
        o.eventType = self.kind
        o.notifyType = self.notify_type
        o.notificationClass = self.nc.number
        o.eventEnable = [int(x) for x in self.event_enable]
        o.eventParameters = self._parameters()
        o.objectPropertyReference = DeviceObjectPropertyReference(
            objectIdentifier=ObjectIdentifier((tc.type, tc.instance)), propertyIdentifier="present-value")
        if c.time_delay_normal is not None:
            o.timeDelayNormal = int(c.time_delay_normal)
        o.eventDetectionEnable = True
        self._publish()

    def _out_of_service(self) -> bool:
        return False  # Event Enrollment has no Out_Of_Service property

    def _ep(self) -> Any:
        ep = self.obj.eventParameters
        return ep.outOfRange if self.kind == "out-of-range" else ep.changeOfState

    def _limits(self) -> Tuple[float, float, float]:
        p = self._ep()
        return float(p.highLimit), float(p.lowLimit), float(p.deadband)

    def _delays(self) -> Tuple[int, int]:
        td = int(self._ep().timeDelay or 0)
        tdn = self.obj.timeDelayNormal
        return td, int(tdn) if tdn is not None else td

    def event_values(self, frm: str, to: str) -> NotificationParameters:
        t = self.point.target.obj
        flags = t.statusFlags  # status flags of the monitored object
        if self.kind == "out-of-range":
            hi, lo, db = self._limits()
            low = to == "low-limit" or (to == "normal" and frm == "low-limit")
            return NotificationParameters(outOfRange=NotificationParametersOutOfRange(
                exceedingValue=float(t.presentValue), statusFlags=flags, deadband=db,
                exceededLimit=lo if low else hi))
        if self._binary:
            ns = PropertyStates(binaryValue=t.presentValue)
        else:
            ns = PropertyStates(unsignedValue=int(t.presentValue))
        return NotificationParameters(changeOfState=NotificationParametersChangeOfState(newState=ns, statusFlags=flags))

    def sync_from_object(self, nc_ref: Any = None) -> Tuple[bool, Optional[str]]:
        """Pick up BACnet writes; returns (config changed, error) like ``Alarm.sync_from_object``."""
        o, c, tc = self.obj, self.cfg, self.point.target.cfg
        upd: Dict[str, Any] = {}
        err = None
        if nc_ref is not None:
            upd["notification_class"] = nc_ref
        ee = [bool(x) for x in o.eventEnable]
        if ee != self.event_enable:
            upd["event_enable"] = ee
        nt = str(o.notifyType)
        if nt != self.notify_type:
            if nt in ("alarm", "event"):
                upd["notify_type"] = nt
            else:
                err = f"notify-type {nt} not supported"
        tdn = o.timeDelayNormal
        if tdn is not None and int(tdn) != c.time_delay_normal:
            upd["time_delay_normal"] = int(tdn)
        if str(o.eventType) != self.kind:
            err = "changing event-type is not supported"
        ref = o.objectPropertyReference
        if ref is None or tuple(ref.objectIdentifier) != tuple(ObjectIdentifier((tc.type, tc.instance))) \
                or str(ref.propertyIdentifier) != "present-value" or ref.deviceIdentifier is not None:
            err = "changing object-property-reference is not supported"
        ep = o.eventParameters
        p = None if ep is None else ep.outOfRange if self.kind == "out-of-range" else ep.changeOfState
        if p is None:
            err = f"event-parameters must be {self.kind}"
        elif err is None:
            td = int(p.timeDelay)
            if td != int(c.time_delay or 0):
                upd["time_delay"] = td
            if self.kind == "out-of-range":
                params = {"low_limit": float(p.lowLimit), "high_limit": float(p.highLimit),
                          "deadband": float(p.deadband)}
                if params["low_limit"] >= params["high_limit"]:
                    err = "event-parameters: low-limit must be below high-limit"
                elif params["deadband"] < 0:
                    err = "event-parameters: deadband < 0"
                cur = {k: float(c.event_parameters.get(k, 0.0)) for k in params}
                if params != cur:
                    upd["event_parameters"] = params
            else:
                vals: List[Any] = []
                for s in p.listOfValues or []:
                    if self._binary and s.binaryValue is not None:
                        vals.append(str(s.binaryValue))
                    elif not self._binary and s.unsignedValue is not None \
                            and 1 <= int(s.unsignedValue) <= len(tc.states or []):
                        vals.append(int(s.unsignedValue))
                    else:
                        err = f"event-parameters: value {s} is not a state of {tc.name}"
                        break
                if err is None and not vals:
                    err = "event-parameters: change-of-state needs at least one value"
                if err is None and [_state(v, self.point.target) for v in vals] != self.alarm_values:
                    upd["event_parameters"] = {"alarm_values": vals}
        if err is not None:
            self._init_properties()
            return False, err
        if not upd:
            self._publish()  # undo writes to read-only mirrors (Acked_Transitions via WPM)
            return False, None
        self.cfg = self.point.cfg = c.model_copy(update=upd)
        self._load_cfg()
        self._init_properties()
        return True, None
