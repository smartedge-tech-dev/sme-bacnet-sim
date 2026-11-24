"""Simulation engine: builds the BACnet stack and runs the behaviors.

Topology
--------
One BACnet/IP port (default UDP 47808) is owned by a router device.  Behind it
is a virtual BACnet network (default network number 100) where every simulated
device lives as its own BACnet application.  Clients see the devices as remote
devices reachable through the router, so any number of devices share one port.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import socket
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from bacpypes3.apdu import (
    AddListElementError, ConfirmedPrivateTransferACK, ConfirmedPrivateTransferError, ConfirmedTextMessageRequest,
    ConfirmedTextMessageRequestMessageClass, RemoveListElementError, UnconfirmedTextMessageRequest,
    UnconfirmedTextMessageRequestMessageClass, CreateObjectACK, CreateObjectError, DeviceCommunicationControlRequest, GetAlarmSummaryACK,
    GetEnrollmentSummaryACK, GetEventInformationACK, IAmRequest, ReinitializeDeviceRequest, SimpleAckPDU,
    WritePropertyMultipleError,
)
from bacpypes3.basetypes import DeviceObjectPropertyReference, ErrorType, ObjectPropertyReference
from bacpypes3.constructeddata import Array, List as ListType, ListOf
from bacpypes3.local.cmd import Commandable
from bacpypes3.local.oos import OutOfService
from bacpypes3.app import Application
from bacpypes3.local.analog import AnalogInputObject, AnalogOutputObject, AnalogValueObject, AnalogValueObjectCmd
from bacpypes3.local.binary import BinaryInputObject, BinaryOutputObject, BinaryValueObject, BinaryValueObjectCmd
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.multistate import MultiStateInputObject, MultiStateOutputObject, MultiStateValueObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.basetypes import (
    BinaryPV, ClientCOV, GetAlarmSummaryAlarmSummary, LifeSafetyMode, GetEnrollmentSummaryEnrollmentSummary, HostNPort,
    PropertyIdentifier,
)
from bacpypes3.constructeddata import Any as AnyValue
from bacpypes3.errors import ExecutionError, PropertyError
from bacpypes3.ipv4.service import BIPForeign
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import (
    Boolean, CharacterString, Integer, Null, ObjectIdentifier, ObjectType, Real, Unsigned,
)
from bacpypes3.vlan import VirtualNetwork
from . import __version__

from . import __version__
from .behaviors import Behavior, ident, make_behavior
from .config import (
    ACCUMULATOR, ANALOG_TYPES, BINARY_TYPES, CALENDAR, CONTROL_TYPES, INPUT_TYPES, LOOP, MULTISTATE_TYPES,
    EVENT_ENROLLMENT, FILE, LIFE_SAFETY_TYPES, NOTIFICATION_CLASS, PROGRAM, SPECIAL_TYPES, PULSE_CONVERTER, REAL_TYPES,
    SCHEDULE, TREND_LOG, WEEKDAYS, DeviceConfig, ObjectConfig, RecipientConfig, SimConfig, parse_calendar_entry,
)
from .alarm import Alarm, NCRecipient, NotificationClass, alarm_class, timestamp, transition_index
from .lifesafety import LS_READONLY, LifeSafety, build_life_safety, link_zones, member_names
from .eventenroll import EnrollmentAlarm, EventEnrollment, check_target
from .devmgmt import CreateError, PropertySubscription, cov_class, initial_values, sync_time
from .schedule import (
    _UNSET as UNSET_VALUE, Calendar, Schedule, build_calendar, build_schedule, entry_to_cfg, refs_to_targets,
    schedule_to_cfg,
    resolve_targets, _value_kind,
)
from .control import CONTROL_CLASSES, acc_max, build_controls, control_kwargs
from .fileprog import FILE_READONLY, PROGRAM_READONLY, SimFile, SimProgram, build_file, build_program
from .props import coerce as coerce_property, list_properties, to_json, writable as property_writable
from .templates import expand_device
from .trendlog import LOG_BUFFER, SimTrendLogObject, TrendLog, datum_kind, read_range_ack

log = logging.getLogger("sme_bacnet_sim")

VNET_NAME = "sme-bacnet-sim-vnet"
FD_TIMEOUT = 10.0  # seconds without a BBMD answer before the registration is reported as timed out


def _commandable_msv():
    from bacpypes3.local.cmd import Commandable

    class _MSVCmd(Commandable, MultiStateValueObject):
        pass

    return _MSVCmd


OBJECT_CLASSES = {
    ("analog-input", False): AnalogInputObject,
    ("analog-output", True): AnalogOutputObject,
    ("analog-value", False): AnalogValueObject,
    ("analog-value", True): AnalogValueObjectCmd,
    ("binary-input", False): BinaryInputObject,
    ("binary-output", True): BinaryOutputObject,
    ("binary-value", False): BinaryValueObject,
    ("binary-value", True): BinaryValueObjectCmd,
    ("multi-state-input", False): MultiStateInputObject,
    ("multi-state-output", True): MultiStateOutputObject,
    ("multi-state-value", False): MultiStateValueObject,
    ("multi-state-value", True): _commandable_msv(),
}


def _linux_prefix_len(ip: str) -> Optional[int]:
    """Prefix length of the Linux interface that owns ``ip`` (SIOCGIFADDR / SIOCGIFNETMASK), or None."""
    import fcntl
    import struct

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            req = struct.pack("256s", name.encode()[:15])
            try:
                if socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, req)[20:24]) != ip:  # SIOCGIFADDR
                    continue
                mask = fcntl.ioctl(s.fileno(), 0x891B, req)[20:24]  # SIOCGIFNETMASK
            except OSError:
                continue
            return bin(int.from_bytes(mask, "big")).count("1")
    finally:
        s.close()
    return None


def _ifconfig_prefix_len(text: str, ip: str) -> Optional[int]:
    """Prefix length of ``ip`` in BSD / macOS ``ifconfig`` output ("inet 10.0.0.5 netmask 0xffffff00 ...")."""
    for m in re.finditer(r"\binet (?:addr:)?(\d+\.\d+\.\d+\.\d+)\S*\s+(?:-->\s*\S+\s+)?netmask\s+(\S+)", text):
        if m.group(1) != ip:
            continue
        mask = m.group(2)
        try:
            value = int(mask, 16) if mask.lower().startswith("0x") else int.from_bytes(socket.inet_aton(mask), "big")
        except (ValueError, OSError):
            return None
        bits = f"{value:032b}"
        return bits.count("1") if "01" not in bits else None  # contiguous masks only
    return None


def _bsd_prefix_len(ip: str) -> Optional[int]:
    """Prefix length of the macOS / BSD interface that owns ``ip`` (parsed from ``ifconfig -a``), or None."""
    import subprocess

    for exe in ("/sbin/ifconfig", "ifconfig"):
        try:
            out = subprocess.run([exe, "-a"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        return _ifconfig_prefix_len(out, ip)
    return None


def with_prefix(ip: str) -> str:
    """Append the interface's real prefix length to a bare IPv4 address ("/24" when it cannot be found).

    The mask matters on Linux and macOS / BSD: bacpypes3 binds a second socket to the subnet broadcast address there and
    waits for it before sending anything, so a wrong mask (e.g. /24 on a Docker /16 bridge) makes the
    broadcast address non-local, the bind retries forever and the BACnet port never sends a packet.
    """
    if "/" in ip:
        return ip
    prefix = None
    if sys.platform.startswith("linux"):
        try:
            prefix = _linux_prefix_len(ip)
        except Exception:  # pragma: no cover - exotic platforms / sandboxes without ioctl
            prefix = None
    elif sys.platform == "darwin" or "bsd" in sys.platform:  # same broadcast-socket bind as on Linux
        try:
            prefix = _bsd_prefix_len(ip)
        except Exception:  # pragma: no cover
            prefix = None
    return f"{ip}/{prefix if prefix is not None else 24}"


def detect_ip() -> str:
    """Best-effort primary IPv4 address with its interface prefix length (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return with_prefix(ip)


# --------------------------------------------------------------------------- points


@dataclass
class Point:
    device_id: int
    cfg: ObjectConfig
    obj: Any
    behavior: Optional[Behavior]
    history: Deque[Tuple[float, float]]
    error: Optional[str] = None
    alarm: Optional[Alarm] = None
    control: Any = None  # PulseInput / PidLoop (control.py)

    @property
    def key(self) -> str:
        return f"{self.cfg.type}:{self.cfg.instance}"

    @property
    def ident(self) -> str:
        return ident(self.cfg.name)

    @property
    def commandable(self) -> bool:
        return self.cfg.is_commandable

    def read(self) -> float:
        pv = self.obj.presentValue
        if self.cfg.type in REAL_TYPES:
            return float(pv)
        return int(pv)

    def coerce(self, value: Any) -> Any:
        """Python value -> value acceptable for presentValue."""
        t = self.cfg.type
        if t == ACCUMULATOR:  # unsigned count; wraps to 0 above max-pres-value
            v = float(value)
            if not math.isfinite(v):
                raise ValueError("non-finite value")
            return max(0, int(v)) % (acc_max(self.cfg) + 1)
        if t in REAL_TYPES:
            v = float(value)
            if not math.isfinite(v):
                raise ValueError("non-finite value")
            if self.cfg.min is not None:
                v = max(self.cfg.min, v)
            if self.cfg.max is not None:
                v = min(self.cfg.max, v)
            return v
        if t in BINARY_TYPES:
            if isinstance(value, str):
                s = value.strip().lower()
                on = s in ("1", "true", "on", "active", (self.cfg.active_text or "").lower())
            else:
                on = bool(value)
            return "active" if on else "inactive"
        n = int(round(float(value)))
        return max(1, min(len(self.cfg.states or [1]), n))

    def typed(self, v: Any) -> Any:
        """Coerced value -> BACnet primitive (needed for priority-array writes)."""
        t = self.cfg.type
        if t in REAL_TYPES:
            return Real(v)
        if t in BINARY_TYPES:
            return BinaryPV(v)
        return Unsigned(v)

    def status(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"value": self.read(), "oos": bool(self.obj.outOfService)}
        if self.commandable:
            ccp = self.obj.currentCommandPriority
            d["priority"] = ccp.unsigned if ccp is not None and ccp.unsigned is not None else None
        if self.cfg.type == LOOP:
            d["sp"] = float(self.obj.setpoint)
            d["cv"] = float(self.obj.controlledVariableValue)
        if self.error:
            d["error"] = self.error
        progress = getattr(self.behavior, "progress", None)
        if progress is not None:
            d["replay"] = progress()
        if self.alarm is not None:
            d["event_state"] = self.alarm.state
            d["unacked"] = self.alarm.unacked
        return d


# covIncrement fallback by units for behavior-driven analog points without a min / max span
_UNIT_COV = {
    "degrees-celsius": 0.1, "degrees-fahrenheit": 0.2, "degrees-kelvin": 0.1, "percent": 0.5,
    "percent-relative-humidity": 0.5, "watts": 1.0, "kilowatts": 0.1, "kilowatt-hours": 0.1, "volts": 0.5,
    "amperes": 0.1, "hertz": 0.01, "pascals": 1.0, "parts-per-million": 5.0, "luxes": 5.0,
    "cubic-meters-per-hour": 0.5, "liters-per-second": 0.1, "watts-per-square-meter": 5.0,
}


def default_cov_increment(oc: ObjectConfig) -> float:
    """covIncrement of an analog object without an explicit ``cov_increment``.

    Behavior-driven points change every tick, so they get 1 % of their span (``min`` / ``max`` of the object,
    else of the behavior), else a per-unit default (``_UNIT_COV``); everything else 0 (= any change).
    """
    if not oc.behavior:
        return 0.0
    lo = oc.min if oc.min is not None else oc.behavior.get("min")
    hi = oc.max if oc.max is not None else oc.behavior.get("max")
    try:
        if lo is not None and hi is not None and float(hi) > float(lo):
            return round((float(hi) - float(lo)) / 100, 6)
    except (TypeError, ValueError):
        pass
    return _UNIT_COV.get(oc.units or "", 0.0)


def build_object(oc: ObjectConfig) -> Any:
    if oc.type in CONTROL_TYPES:
        cls = cov_class(CONTROL_CLASSES[oc.type])
        kw = dict(objectIdentifier=(oc.type, oc.instance), objectName=oc.name, statusFlags=[0, 0, 0, 0],
                  eventState="normal", outOfService=False, reliability="no-fault-detected")
        if oc.description:
            kw["description"] = oc.description
        inc = oc.cov_increment if oc.cov_increment is not None else default_cov_increment(oc)
        kw.update(control_kwargs(oc, inc))
        return cls(**kw)
    cls = OBJECT_CLASSES[(oc.type, oc.is_commandable)]
    if oc.alarm is not None:
        cls = alarm_class(cls)
    cls = cov_class(cls)
    kw: Dict[str, Any] = dict(
        objectIdentifier=(oc.type, oc.instance),
        objectName=oc.name,
        statusFlags=[0, 0, 0, 0],
        eventState="normal",
        outOfService=False,
        reliability="no-fault-detected",
    )
    if oc.description:
        kw["description"] = oc.description
    if oc.type in ANALOG_TYPES:
        kw["presentValue"] = float(oc.value if oc.value is not None else 0.0)
        kw["units"] = oc.units or "no-units"
        # COV needs a covIncrement (bacpypes3 compares against it); 0 = notify on any change
        kw["covIncrement"] = oc.cov_increment if oc.cov_increment is not None else default_cov_increment(oc)
        if oc.min is not None and oc.type != "analog-input":
            kw["minPresValue"] = float(oc.min)
        if oc.max is not None and oc.type != "analog-input":
            kw["maxPresValue"] = float(oc.max)
    elif oc.type in BINARY_TYPES:
        kw["presentValue"] = "active" if oc.value in (1, True, "active", "1", "on") else "inactive"
        if oc.type != "binary-value":
            kw["polarity"] = "normal"
        if oc.active_text:
            kw["activeText"] = oc.active_text
        if oc.inactive_text:
            kw["inactiveText"] = oc.inactive_text
    else:
        kw["numberOfStates"] = len(oc.states)
        kw["stateText"] = list(oc.states)
        kw["presentValue"] = max(1, min(len(oc.states), int(oc.value or 1)))
    if oc.is_commandable:
        kw["relinquishDefault"] = kw["presentValue"]
    return cls(**kw)


def build_trendlog(dev: DeviceConfig, oc: ObjectConfig, points: List[Point]) -> TrendLog:
    """Trend Log object polling another object of the same device; raises on a bad reference."""
    target = next((p for p in points if p.cfg.name == oc.log_object), None)
    if target is None:
        raise ValueError(f"device {dev.name} ({dev.device_id}): trend-log {oc.name}: "
                         f"log_object {oc.log_object!r} is not an object of this device")
    prop = PropertyIdentifier(oc.log_property or "present-value")
    kind = datum_kind(target.obj.get_property_type(prop))
    if kind is None:
        raise ValueError(f"device {dev.name} ({dev.device_id}): trend-log {oc.name}: "
                         f"property {prop} of {oc.log_object} cannot be logged")
    interval = float(oc.log_interval or 60)
    cov = oc.logging_type == "cov"
    kw: Dict[str, Any] = dict(
        objectIdentifier=(TREND_LOG, oc.instance),
        objectName=oc.name,
        statusFlags=[0, 0, 0, 0],
        eventState="normal",
        reliability="no-fault-detected",
        enable=oc.enabled is not False,
        stopWhenFull=False,
        loggingType="cov" if cov else "polled",
        # hundredths of a second (clause 12.25.10); not used by COV logging
        logInterval=0 if cov else int(round(interval * 100)),
        logDeviceObjectProperty={
            "objectIdentifier": (target.cfg.type, target.cfg.instance),
            "propertyIdentifier": prop,
            "deviceIdentifier": ("device", dev.device_id),
        },
    )
    if oc.description:
        kw["description"] = oc.description
    if cov:
        kw["clientCovIncrement"] = (ClientCOV(realIncrement=oc.client_cov_increment)
                                    if oc.client_cov_increment is not None else ClientCOV(defaultIncrement=Null(())))
    obj = SimTrendLogObject(buffer_size=oc.buffer_size or 1000, **kw)
    return TrendLog(dev.device_id, oc, obj, target, prop.attr, kind, interval,
                    cov=cov, increment=oc.client_cov_increment)


# --------------------------------------------------------------------------- applications


def _recipient_matches(r: Any, ef: Any) -> bool:
    """GetEnrollmentSummary enrollmentFilter (BACnetRecipientProcess) vs one NC recipient."""
    if int(ef.processIdentifier) != r.cfg.process_id:
        return False
    rc = ef.recipient
    if rc.device is not None:
        return r.cfg.device is not None and int(rc.device[1]) == r.cfg.device
    if rc.address is not None and r.cfg.device is None and r.address is not None:
        return int(rc.address.networkNumber) == r.address.addrNet and bytes(rc.address.macAddress) == r.address.addrAddr
    return False


class SimApplication(Application):
    """Application that reports incoming writes to the engine."""

    engine: "Engine"
    sim_device_id: int

    async def do_WritePropertyRequest(self, apdu) -> None:
        self.engine.check_alarm_write(self.sim_device_id, apdu.objectIdentifier, apdu.propertyIdentifier,
                                      apdu.propertyValue)
        await super().do_WritePropertyRequest(apdu)
        self.engine.alarm_written(self.sim_device_id, [apdu.objectIdentifier])
        self.engine.log_event(
            "bacnet-write",
            f"WriteProperty from {apdu.pduSource} -> device {self.sim_device_id} "
            f"{apdu.objectIdentifier[0]},{apdu.objectIdentifier[1]} {apdu.propertyIdentifier}"
            + (f" @priority {apdu.priority}" if apdu.priority else ""),
        )
        self.engine.request_scan()

    def _validate_wpm(self, apdu) -> None:
        """WritePropertyMultiple pre-validation: check every item before any is written.

        bacpypes3 writes the items one by one and stops at the first failure, leaving the earlier ones applied.
        Checked here for all items first: object exists, property exists, array index, datatype, the alarm
        property rules (``check_alarm_write``) and the static write-access rules of bacpypes3 local objects
        (commandable Priority_Array, Present_Value of an out-of-service-gated object, honouring an
        Out_Of_Service write earlier in the same request).  Value checks that only run inside an object's own
        write hook (e.g. trend log / schedule range checks) can still fail after earlier items were applied.
        """
        oos: Dict[Any, bool] = {}
        for spec in apdu.listOfWriteAccessSpecifications:
            oid = spec.objectIdentifier
            if oid == ("device", 4194303) and self.device_object is not None:
                oid = self.device_object.objectIdentifier
            obj = self.get_object_id(oid)

            def fail(error_class: str, error_code: str, prop: Any, index: Any = None) -> None:
                ref = ObjectPropertyReference(objectIdentifier=oid, propertyIdentifier=prop)
                if index is not None:
                    ref.propertyArrayIndex = index
                raise WritePropertyMultipleError(errorType=ErrorType(errorClass=error_class, errorCode=error_code),
                                                 firstFailedWriteAttempt=ref)

            if obj is None:  # the reference needs a property: report the first one of this object
                first = spec.listOfProperties[0] if spec.listOfProperties else None
                fail("object", "unknownObject", first.propertyIdentifier if first else PropertyIdentifier.all,
                     first.propertyArrayIndex if first else None)
            for pv in spec.listOfProperties:
                prop, index, priority = pv.propertyIdentifier, pv.propertyArrayIndex, pv.priority
                ptype = obj.get_property_type(prop)
                if ptype is None:
                    fail("property", "unknownProperty", prop, index)
                if issubclass(ptype, Array):
                    if index == 0:
                        ptype = Unsigned
                    elif index is not None:
                        ptype = ptype._subtype
                elif index is not None:
                    fail("property", "propertyIsNotAnArray", prop, index)
                try:
                    value = pv.propertyValue.cast_out(ptype, null=(priority is not None))
                except Exception:
                    fail("property", "invalidDataType", prop, index)
                pid = PropertyIdentifier(prop)
                if pid == PropertyIdentifier.priorityArray and isinstance(obj, Commandable):
                    fail("property", "writeAccessDenied", prop, index)
                if pid == PropertyIdentifier.outOfService:
                    oos[id(obj)] = bool(value)
                if (pid == PropertyIdentifier.presentValue and isinstance(obj, OutOfService)
                        and not oos.get(id(obj), bool(obj.outOfService))):
                    fail("property", "writeAccessDenied", prop, index)
                try:
                    self.engine.check_alarm_write(self.sim_device_id, oid, prop, pv.propertyValue)
                except ExecutionError as err:
                    fail(str(err.errorClass), str(err.errorCode), prop, index)

    async def do_WritePropertyMultipleRequest(self, apdu) -> None:
        self._validate_wpm(apdu)  # all or nothing for everything checkable up front (see _validate_wpm)
        await super().do_WritePropertyMultipleRequest(apdu)
        self.engine.alarm_written(self.sim_device_id, [s.objectIdentifier for s in apdu.listOfWriteAccessSpecifications])
        self.engine.log_event("bacnet-write", f"WritePropertyMultiple from {apdu.pduSource} -> device {self.sim_device_id}")
        self.engine.request_scan()

    async def do_AtomicReadFileRequest(self, apdu) -> None:
        f = self.engine.file_for(self.sim_device_id, apdu.fileIdentifier)
        await self.response(f.read(apdu))

    async def do_AtomicWriteFileRequest(self, apdu) -> None:
        await self.response(self.engine.write_file(self.sim_device_id, apdu))

    async def do_ReadRangeRequest(self, apdu) -> None:
        # bacpypes3 0.1.0 leaves the server side unimplemented; only trend-log buffers are served
        obj = self.get_object_id(apdu.objectIdentifier)
        if obj is None:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        if obj.get_property_type(apdu.propertyIdentifier) is None:
            raise ExecutionError(errorClass="property", errorCode="unknownProperty")
        if not isinstance(obj, SimTrendLogObject) or apdu.propertyIdentifier != LOG_BUFFER:
            raise ExecutionError(errorClass="property", errorCode="propertyIsNotAList")
        await self.response(read_range_ack(obj, apdu))

    # event services (bacpypes3 0.1.0 has no server side for these; see sme_bacnet_sim/alarm.py)

    async def do_AcknowledgeAlarmRequest(self, apdu) -> None:
        self.engine.bacnet_ack(self.sim_device_id, apdu)
        await self.response(SimpleAckPDU(context=apdu))

    async def do_GetEventInformationRequest(self, apdu) -> None:
        await self.response(self.engine.event_information(self.sim_device_id, apdu))

    async def do_GetAlarmSummaryRequest(self, apdu) -> None:
        await self.response(self.engine.alarm_summary(self.sim_device_id, apdu))

    async def do_GetEnrollmentSummaryRequest(self, apdu) -> None:
        await self.response(self.engine.enrollment_summary(self.sim_device_id, apdu))

    # ---- COV (status flags / DCC aware) and SubscribeCOVProperty (no server side in bacpypes3 0.1.0)

    def cov_notification(self, cov, apdu) -> None:
        if self.comm_state != "enable":  # DCC disable / disable-initiation: no notifications
            return
        super().cov_notification(cov, apdu)

    @property
    def prop_subs(self) -> Dict[tuple, PropertySubscription]:
        d = self.__dict__.get("_prop_subs")
        if d is None:
            d = self.__dict__["_prop_subs"] = {}
        return d

    def cancel_property_subscription(self, sub: PropertySubscription) -> None:
        sub.cancel()
        self.prop_subs.pop(sub.key, None)

    async def do_SubscribeCOVPropertyRequest(self, apdu) -> None:
        obj = self.get_object_id(apdu.monitoredObjectIdentifier)
        cancel = apdu.issueConfirmedNotifications is None and apdu.lifetime is None
        ref = apdu.monitoredPropertyIdentifier
        prop = PropertyIdentifier(ref.propertyIdentifier)
        index = ref.propertyArrayIndex
        if obj is None:
            if cancel:
                await self.response(SimpleAckPDU(context=apdu))
                return
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        if obj.get_property_type(prop) is None:
            raise ExecutionError(errorClass="property", errorCode="unknownProperty")
        key = (apdu.pduSource, int(apdu.subscriberProcessIdentifier), obj.objectIdentifier, prop, index)
        sub = self.prop_subs.get(key)
        if cancel:
            if sub is not None:
                self.cancel_property_subscription(sub)
            await self.response(SimpleAckPDU(context=apdu))
            return
        if sub is None:
            sub = self.prop_subs[key] = PropertySubscription(
                self, apdu.pduSource, int(apdu.subscriberProcessIdentifier), obj, prop, index)
        sub.confirmed = bool(apdu.issueConfirmedNotifications)
        inc = apdu.covIncrement
        if inc is None and prop.attr == "presentValue":
            inc = getattr(obj, "covIncrement", None)
        sub.increment = float(inc) if inc is not None else None
        sub.renew(apdu.lifetime)
        await self.response(SimpleAckPDU(context=apdu))
        sub.schedule()  # initial notification

    def drop_object(self, obj: Any) -> None:
        """Remove an object with its COV subscriptions."""
        det = self._cov_detections.pop(obj.objectIdentifier, None)
        if det is not None:
            for cov in list(det.cov_subscriptions):
                cov.cancel_subscription()
            det.unbind()
        for sub in [s for s in self.prop_subs.values() if s.obj is obj]:
            self.cancel_property_subscription(sub)
        self.delete_object(obj)

    # ---- CreateObject / DeleteObject

    async def do_CreateObjectRequest(self, apdu) -> None:
        spec = apdu.objectSpecifier
        if spec.objectIdentifier is not None:
            otype, inst = spec.objectIdentifier[0], spec.objectIdentifier[1]
        else:
            otype, inst = spec.objectType, None
        try:
            oid = self.engine.create_object(self.sim_device_id, otype, inst, apdu.listOfInitialValues or [],
                                            f"CreateObject from {apdu.pduSource}")
        except CreateError as e:
            await self.response(CreateObjectError(
                errorType=ErrorType(errorClass=e.error_class, errorCode=e.error_code),
                firstFailedElementNumber=e.element, context=apdu))
            return
        await self.response(CreateObjectACK(objectIdentifier=oid, context=apdu))

    async def do_DeleteObjectRequest(self, apdu) -> None:
        self.engine.delete_object(self.sim_device_id, apdu.objectIdentifier, f"DeleteObject from {apdu.pduSource}")
        await self.response(SimpleAckPDU(context=apdu))

    # ---- life safety, text messages, private transfer, list element services

    async def do_LifeSafetyOperationRequest(self, apdu) -> None:
        self.engine.life_safety_operation(self.sim_device_id, apdu)
        await self.response(SimpleAckPDU(context=apdu))

    async def do_ConfirmedTextMessageRequest(self, apdu) -> None:
        self.engine.text_message_received(self.sim_device_id, apdu, True)
        await self.response(SimpleAckPDU(context=apdu))

    async def do_UnconfirmedTextMessageRequest(self, apdu) -> None:
        self.engine.text_message_received(self.sim_device_id, apdu, False)

    async def do_ConfirmedPrivateTransferRequest(self, apdu) -> None:
        await self.response(self.engine.private_transfer(self.sim_device_id, apdu, True))

    async def do_UnconfirmedPrivateTransferRequest(self, apdu) -> None:
        self.engine.private_transfer(self.sim_device_id, apdu, False)

    async def do_AddListElementRequest(self, apdu) -> None:
        await self._change_list(apdu, True)

    async def do_RemoveListElementRequest(self, apdu) -> None:
        await self._change_list(apdu, False)

    async def _change_list(self, apdu, add: bool) -> None:
        try:
            await self.engine.change_list(self.sim_device_id, apdu, add)
        except CreateError as e:
            cls = AddListElementError if add else RemoveListElementError
            await self.response(cls(errorType=ErrorType(errorClass=e.error_class, errorCode=e.error_code),
                                    firstFailedElementNumber=e.element, context=apdu))
            return
        await self.response(SimpleAckPDU(context=apdu))

    # ---- time synchronization

    async def do_TimeSynchronizationRequest(self, apdu) -> None:
        self.engine.set_clock(sync_time(apdu.time, False), f"TimeSynchronization from {apdu.pduSource}")

    async def do_UTCTimeSynchronizationRequest(self, apdu) -> None:
        self.engine.set_clock(sync_time(apdu.time, True), f"UTCTimeSynchronization from {apdu.pduSource}")

    # ---- DeviceCommunicationControl
    # bacpypes3 0.1.0's DCC mixin targets a non-existent ``smap`` and the filter in its service access point
    # crashes on every incoming PDU while disabled, so the state is kept and enforced here instead.

    @property
    def comm_state(self) -> str:
        return self.__dict__.get("_dcc", "enable")

    async def indication(self, apdu) -> None:
        if self.comm_state == "disable" and not isinstance(
                apdu, (DeviceCommunicationControlRequest, ReinitializeDeviceRequest)):
            return  # ignored (a confirmed request simply gets no answer)
        await super().indication(apdu)

    def request(self, apdu):
        state = self.comm_state
        if state == "disable" or (state == "disable-initiation" and not isinstance(apdu, IAmRequest)):
            return None  # initiation disabled (I-Am in answer to Who-Is is still allowed)
        return super().request(apdu)

    def set_comm(self, state: str, minutes: Optional[int] = None, source: str = "") -> None:
        h = self.__dict__.pop("_dcc_handle", None)
        if h is not None:
            h.cancel()
        was = self.comm_state
        self.__dict__["_dcc"] = state
        if state != "enable" and minutes:
            # time duration is wall-clock minutes (clause 16.1.1.1.2), independent of the simulated clock
            self.__dict__["_dcc_handle"] = asyncio.get_running_loop().call_later(
                minutes * 60, self.set_comm, "enable", None, "time duration expired")
        if was != state or source:
            self.engine.log_event("dcc", f"device {self.sim_device_id}: communication {state}"
                                  + (f" for {minutes} min" if state != "enable" and minutes else "")
                                  + (f" ({source})" if source else ""))
            self.engine.publish({"type": "reload"})

    async def do_DeviceCommunicationControlRequest(self, apdu) -> None:
        pw = self.engine.devices[self.sim_device_id].cfg.dcc_password
        if pw and str(apdu.password or "") != pw:
            self.engine.log_event("dcc", f"device {self.sim_device_id}: DeviceCommunicationControl from "
                                         f"{apdu.pduSource} rejected (password failure)")
            raise ExecutionError(errorClass="security", errorCode="passwordFailure")
        await self.response(SimpleAckPDU(context=apdu))
        self.set_comm(str(apdu.enableDisable), int(apdu.timeDuration) if apdu.timeDuration else None,
                      f"DeviceCommunicationControl from {apdu.pduSource}")

    # ---- ReinitializeDevice

    async def do_ReinitializeDeviceRequest(self, apdu) -> None:
        pw = self.engine.devices[self.sim_device_id].cfg.reinit_password
        src = f"ReinitializeDevice from {apdu.pduSource}"
        if pw and str(apdu.password or "") != pw:
            self.engine.log_event("reinit", f"device {self.sim_device_id}: {src} rejected (password failure)")
            raise ExecutionError(errorClass="security", errorCode="passwordFailure")
        state = str(apdu.reinitializedStateOfDevice)
        if state not in ("coldstart", "warmstart"):
            raise ExecutionError(errorClass="services", errorCode="optionalFunctionalityNotSupported")
        await self.response(SimpleAckPDU(context=apdu))  # the device answers before it restarts
        await self.engine.reinitialize(self.sim_device_id, state == "coldstart", src)


class RouterApplication(Application):
    """Router device: answers (broadcast) time synchronization for the whole simulator."""

    engine: "Engine"

    async def do_TimeSynchronizationRequest(self, apdu) -> None:
        self.engine.set_clock(sync_time(apdu.time, False), f"TimeSynchronization from {apdu.pduSource}")

    async def do_UTCTimeSynchronizationRequest(self, apdu) -> None:
        self.engine.set_clock(sync_time(apdu.time, True), f"UTCTimeSynchronization from {apdu.pduSource}")


def _device_object(device_id: int, name: str, vendor_id: int = 999, vendor_name: str = "smart-edge",
                   model: str = "SME BACnetSim", description: str = "", location: str = "") -> DeviceObject:
    kw = dict(
        objectIdentifier=("device", device_id),
        objectName=name,
        vendorIdentifier=vendor_id,
        vendorName=vendor_name,
        modelName=model,
        firmwareRevision=__version__,
        applicationSoftwareVersion=__version__,
        maxApduLengthAccepted=1476,
        segmentationSupported="segmented-both",
    )
    if description:
        kw["description"] = description
    if location:
        kw["location"] = location
    return DeviceObject(**kw)


def _virtual_port(mac: bytes, net: int, instance: int = 2) -> NetworkPortObject:
    return NetworkPortObject(
        objectIdentifier=("network-port", instance),
        objectName="VirtualPort",
        networkType="virtual",
        protocolLevel="bacnet-application",
        networkNumber=net,
        networkNumberQuality="configured",
        macAddress=mac,
        networkInterfaceName=VNET_NAME,
        statusFlags=[0, 0, 0, 0],
        reliability="no-fault-detected",
        outOfService=False,
        changesPending=False,
    )


@dataclass
class DeviceRuntime:
    cfg: DeviceConfig
    mac: bytes
    points: List[Point]
    app: Optional[Application] = None
    by_key: Dict[str, Point] = field(default_factory=dict)
    trendlogs: List[TrendLog] = field(default_factory=list)
    calendars: List[Calendar] = field(default_factory=list)
    schedules: List[Schedule] = field(default_factory=list)
    ncs: List[NotificationClass] = field(default_factory=list)
    alarms: List[Alarm] = field(default_factory=list)
    files: List[SimFile] = field(default_factory=list)
    programs: List[SimProgram] = field(default_factory=list)
    controls: List[Any] = field(default_factory=list)  # pulse converter inputs, then loops (control.py)
    ees: List[EventEnrollment] = field(default_factory=list)  # event enrollments (eventenroll.py)
    lifesafety: List[LifeSafety] = field(default_factory=list)  # points first, then zones (lifesafety.py)
    later: List[Any] = field(default_factory=list)  # object configs built after all value objects (_prepare)


# --------------------------------------------------------------------------- engine


class Engine:
    def __init__(self, config: SimConfig, config_path: Optional[str] = None):
        self.config = config
        self.config_path = config_path
        self.devices: Dict[int, DeviceRuntime] = {}
        self.router_app: Optional[Application] = None
        self.bind_address: str = ""
        self.sim_time = 0.0
        self.sim_epoch = time.time()
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._listeners: Set[asyncio.Queue] = set()
        self._last: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self._scan = asyncio.Event()
        self._lock = asyncio.Lock()
        self.events: Deque[Dict[str, Any]] = deque(maxlen=200)
        self._tasks: Set[asyncio.Task] = set()
        self._dev_addr: Dict[int, Address] = {}  # recipient device id -> address learned with Who-Is
        # foreign-device registration state reported by the status API (None = not a foreign device)
        self.foreign: Optional[Dict[str, Any]] = None
        self._fd_code: Optional[int] = None  # last seen BIPForeign.bbmdRegistrationStatus
        self._fd_since = 0.0  # loop time the current registration attempt started

    # ---- events / listeners

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._listeners.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._listeners.discard(q)

    def publish(self, msg: Dict[str, Any]) -> None:
        for q in list(self._listeners):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def log_event(self, kind: str, text: str) -> None:
        self._event_seq = getattr(self, "_event_seq", 0) + 1  # lets /ws skip events already in a snapshot
        ev = {"t": time.time(), "kind": kind, "text": text, "seq": self._event_seq}
        self.events.append(ev)
        log.info("%s: %s", kind, text)
        self.publish({"type": "log", "event": ev})

    def request_scan(self) -> None:
        self._scan.set()

    # ---- build / teardown

    @property
    def base_dir(self) -> Path:
        """Directory that relative config paths (File objects, replay CSVs) resolve against."""
        return Path(self.config_path).resolve().parent if self.config_path else Path.cwd()

    def _prepare(self, config: SimConfig) -> Dict[int, DeviceRuntime]:
        """Expand templates and build all objects; raises on any config error."""
        hist = config.simulation.history_size
        width = 1 if len(config.devices) < 250 else 2
        base_dir = self.base_dir
        runtimes: Dict[int, DeviceRuntime] = {}
        for idx, dev in enumerate(config.devices, start=1):
            points = []
            names, keys = set(), set()
            later = []  # trend logs, calendars, schedules
            for oc in expand_device(dev):
                key = f"{oc.type}:{oc.instance}"
                if oc.name in names or key in keys:
                    raise ValueError(f"{dev.name}: duplicate object name/instance {oc.name} / {key}")
                names.add(oc.name)
                keys.add(key)
                if oc.type in SPECIAL_TYPES:
                    later.append(oc)  # built once all value objects exist
                    continue
                try:
                    behavior = make_behavior(oc.behavior, base_dir, oc.type)
                    obj = build_object(oc)
                except Exception as e:
                    raise ValueError(f"{dev.name}/{oc.name}: {e}") from e
                points.append(Point(dev.device_id, oc, obj, behavior, deque(maxlen=hist)))
            rt = DeviceRuntime(dev, idx.to_bytes(width, "big"), points)
            rt.by_key = {p.key: p for p in points}
            rt.controls = build_controls(dev, points)
            rt.trendlogs = [build_trendlog(dev, oc, points) for oc in later if oc.type == TREND_LOG]
            rt.calendars = [build_calendar(dev, oc) for oc in later if oc.type == CALENDAR]
            rt.later = later
            try:
                rt.files = [build_file(dev.device_id, oc, base_dir, self.sim_epoch + self.sim_time)
                            for oc in later if oc.type == FILE]
            except OSError as e:
                raise ValueError(f"device {dev.name} ({dev.device_id}): file: {e}") from e
            rt.programs = [build_program(dev.device_id, oc) for oc in later if oc.type == PROGRAM]
            rt.lifesafety = sorted((build_life_safety(dev.device_id, oc) for oc in later
                                    if oc.type in LIFE_SAFETY_TYPES), key=lambda x: x.zone)
            link_zones(f"device {dev.name} ({dev.device_id})", rt.lifesafety)
            rt.ncs = [NotificationClass(dev.device_id, oc, config.network.network_number)
                      for oc in later if oc.type == NOTIFICATION_CLASS]
            for p in points:
                if p.cfg.alarm is None:
                    continue
                ref = p.cfg.alarm.notification_class
                nc = next((n for n in rt.ncs if n.cfg.name == ref or str(n.number) == str(ref)), None)
                if nc is None:
                    raise ValueError(f"device {dev.name} ({dev.device_id}): {p.cfg.name}: alarm.notification_class "
                                     f"{ref!r} is not a notification-class object of this device")
                p.alarm = Alarm(p, nc)
                rt.alarms.append(p.alarm)
            for oc in later:
                if oc.type != EVENT_ENROLLMENT:
                    continue
                where = f"device {dev.name} ({dev.device_id}): {oc.name}"
                target = next((p for p in points if p.cfg.name == oc.monitored_object), None)
                if target is None:
                    raise ValueError(f"{where}: monitored_object {oc.monitored_object!r} is not a value object "
                                     f"of this device")
                ref = oc.notification_class
                nc = next((n for n in rt.ncs if n.cfg.name == ref or str(n.number) == str(ref)), None)
                if nc is None:
                    raise ValueError(f"{where}: notification_class {ref!r} is not a notification-class object "
                                     f"of this device")
                try:
                    check_target(oc, target)
                    ee = EventEnrollment(dev.device_id, oc, target)
                    ee.alarm = EnrollmentAlarm(ee, nc)
                except Exception as e:
                    raise ValueError(f"{where}: {e}") from e
                rt.ees.append(ee)
                rt.alarms.append(ee.alarm)
            runtimes[dev.device_id] = rt
        for rt in runtimes.values():  # once all devices exist: schedule targets may be in other devices
            rt.schedules = [build_schedule(rt.cfg, oc, rt.points, rt.calendars, runtimes.values())
                            for oc in rt.later if oc.type == SCHEDULE]
        return runtimes

    async def start(self) -> None:
        async with self._lock:
            self._build(self.config, self._prepare(self.config))
        self._stopping = False
        self._task = asyncio.create_task(self._run())

    def _build(self, config: SimConfig, runtimes: Dict[int, DeviceRuntime]) -> None:
        net = config.network
        VirtualNetwork._networks.pop(VNET_NAME, None)
        VirtualNetwork(VNET_NAME)

        ip = detect_ip() if net.ip == "auto" else with_prefix(net.ip)
        self.bind_address = f"{ip}:{net.port}"
        router_mac = (254 if len(runtimes) < 250 else 65534).to_bytes(1 if len(runtimes) < 250 else 2, "big")
        ip_port_kw: Dict[str, Any] = {"objectIdentifier": ("network-port", 1), "objectName": "IPPort",
                                      "networkNumber": net.network_number, "networkNumberQuality": "configured"}
        if net.mode == "bbmd":
            ip_port_kw.update(bacnetIPMode="bbmd", bbmdBroadcastDistributionTable=[], bbmdAcceptFDRegistrations=True)
        elif net.foreign_device is not None:
            # bacpypes3 builds a ForeignLinkLayer and starts Register-Foreign-Device (renewed every TTL)
            ip_port_kw.update(bacnetIPMode="foreign", fdBBMDAddress=HostNPort(net.foreign_device.bbmd),
                              fdSubscriptionLifetime=net.foreign_device.ttl)
        router_objs = [
            _device_object(net.router.device_id, net.router.name, description="SME BACnetSim BACnet/IP to virtual network router"),
            NetworkPortObject(self.bind_address, **ip_port_kw),
            _virtual_port(router_mac, net.virtual_network),
        ]
        self.router_app = RouterApplication.from_object_list(router_objs)
        self.router_app.engine = self
        self.foreign = None
        self._fd_code = None
        if net.foreign_device is not None:
            self.foreign = {"bbmd": net.foreign_device.bbmd, "ttl": net.foreign_device.ttl,
                            "status": "registering", "result_code": None}
            self._fd_since = asyncio.get_event_loop().time()

        for rt in runtimes.values():
            d = rt.cfg
            objs = [
                _device_object(d.device_id, d.name, d.vendor_id, d.vendor_name,
                               d.model_name or (d.template or "custom"), d.description, d.location),
                _virtual_port(rt.mac, net.virtual_network),
            ] + [p.obj for p in rt.points] + [tl.obj for tl in rt.trendlogs] \
                + [c.obj for c in rt.calendars] + [sc.obj for sc in rt.schedules] + [n.obj for n in rt.ncs] \
                + [f.obj for f in rt.files] + [pg.obj for pg in rt.programs] + [e.obj for e in rt.ees] \
                + [ls.obj for ls in rt.lifesafety]
            app = SimApplication.from_object_list(objs)
            app.engine = self
            app.sim_device_id = d.device_id
            rt.app = app

        self.devices = runtimes
        self.config = config
        self._last.clear()
        self._dev_addr.clear()
        for rt in runtimes.values():
            self._run_schedules(rt)  # initial scheduled values at the current simulated time
            for sc in rt.schedules:
                for ext in sc.external:
                    self.log_event("schedule", f"{rt.cfg.name}/{sc.cfg.name}: target {ext} is not part of this "
                                               f"simulator; not written")
        self.log_event(
            "start",
            f"BACnet/IP {self.bind_address} (router device {net.router.device_id}), "
            f"{len(runtimes)} device(s) on virtual network {net.virtual_network}",
        )

    # ---- foreign device registration (bacpypes3 BIPForeign)

    def _foreign_link(self) -> Optional[BIPForeign]:
        if self.router_app is None:
            return None
        return next((ll for ll in self.router_app.link_layers.values() if isinstance(ll, BIPForeign)), None)

    def _check_foreign(self) -> None:
        """Track the registration status of the foreign link layer; log every change."""
        link = self._foreign_link()
        if self.foreign is None or link is None:
            return
        fd = self.foreign
        before = fd["status"]
        loop_time = asyncio.get_event_loop().time()
        code = link.bbmdRegistrationStatus  # -2 unregistered, -1 in process, 0 OK, >0 BVLC result code
        if code == -2 and link.bbmdAddress is not None:
            # registration expired (no renewal answer within TTL + 30 s): start over
            self.log_event("foreign", f"FD registration with {fd['bbmd']} expired; re-registering")
            self._restart_foreign(link)
            code = -1
            self._fd_since = loop_time
        elif code > 0 and loop_time - self._fd_since > FD_TIMEOUT:
            # bacpypes3 ignores answers to its own retries after a NAK: register again explicitly
            self._restart_foreign(link)
            self._fd_since = loop_time
        if code != self._fd_code:
            self._fd_code = code
            if code == 0:
                fd.update(status="ok", result_code=0)
                self.log_event("foreign", f"registered as foreign device with BBMD {fd['bbmd']} (TTL {fd['ttl']} s)")
            elif code > 0:
                fd.update(status="nak", result_code=code)
                self._fd_since = loop_time
                self.log_event("foreign", f"BBMD {fd['bbmd']} rejected the registration (NAK 0x{code:04X}); retrying")
            elif code == -1:
                fd.update(status="registering")
                self._fd_since = loop_time
        if code == -1 and fd["status"] == "registering" and loop_time - self._fd_since > FD_TIMEOUT:
            fd.update(status="timeout")
            self.log_event("foreign", f"no answer from BBMD {fd['bbmd']} within {FD_TIMEOUT:.0f} s; retrying")
        if fd["status"] != before:
            self.publish({"type": "network", "foreign_device": dict(fd)})

    @staticmethod
    def _restart_foreign(link: BIPForeign) -> None:
        addr, ttl = link.bbmdAddress, link.bbmdTimeToLive
        link._stop_tracking_registration()  # cancel every pending renewal / retry before starting over
        if link.bbmdRegistrationStatus == -2:
            link.bbmdRegistrationStatus = -1
        link.register(addr, ttl)

    async def _unregister_foreign(self) -> None:
        link = self._foreign_link()
        if link is not None and link.bbmdRegistrationStatus != -2:
            link.unregister()  # sends Register-Foreign-Device with TTL 0 and cancels renewals
            await asyncio.sleep(0.1)  # let the request go out before the socket closes
            if self.foreign is not None:
                self.log_event("foreign", f"unregistered from BBMD {self.foreign['bbmd']}")
        elif link is not None:
            link._stop_tracking_registration()

    def _teardown(self) -> None:
        for rt in self.devices.values():
            if rt.app:
                rt.app.close()
        if self.router_app:
            self.router_app.close()
        self.router_app = None
        self.devices = {}

    async def reload(self, config: SimConfig) -> None:
        runtimes = self._prepare(config)  # validate before touching the running stack
        async with self._lock:
            old = self.config
            await self._unregister_foreign()
            self._teardown()
            await asyncio.sleep(0.3)  # let the UDP socket close before re-binding
            try:
                self._build(config, runtimes)
            except Exception as e:
                self.log_event("error", f"reload failed, restoring previous config: {e}")
                self._teardown()
                await asyncio.sleep(0.3)
                self._build(old, self._prepare(old))
                raise
        self.publish({"type": "reload"})

    async def stop(self) -> None:
        if self._task:
            # The flag is what actually ends _run: on Python < 3.12 asyncio.wait_for() swallows a
            # cancellation that arrives together with the completion of the awaited Event (the scan
            # request), so cancel() alone could leave _run ticking forever and stop() hanging.
            self._stopping = True
            self._scan.set()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._unregister_foreign()
        self._teardown()

    # ---- simulation loop

    @property
    def sim_hour(self) -> float:
        lt = time.localtime(self.sim_epoch + self.sim_time)
        return lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600

    def _pv(self, device: Any, obj: str) -> float:
        for rt in self.devices.values():
            if rt.cfg.name == device or rt.cfg.device_id == device:
                for p in rt.points:
                    if p.cfg.name == obj:
                        return p.read()
        raise KeyError(f"pv({device!r}, {obj!r}) not found")

    def _run_schedules(self, rt: DeviceRuntime, only_dirty: bool = False) -> None:
        """Evaluate calendars and schedules on the simulated clock (see sme_bacnet_sim/schedule.py)."""
        ts = self.sim_epoch + self.sim_time
        for c in rt.calendars:
            c.obj.evaluate(ts)
        for sc in rt.schedules:
            if only_dirty and not sc.obj._dirty:
                continue
            if sc.evaluate(ts) and sc.targets:
                self.log_event("schedule", f"{rt.cfg.name}/{sc.cfg.name} = {sc.text(sc.current)} -> "
                               f"{', '.join(sc.labels)} @priority {sc.priority}")

    def step(self, dt: float) -> None:
        self.sim_time += dt
        base = {"t": self.sim_time, "dt": dt, "hour": self.sim_hour, "pv": self._pv}
        for rt in self.devices.values():
            self._run_schedules(rt)
            names = dict(base)
            names.update({p.ident: p.read() for p in rt.points})
            for p in rt.points:
                if p.behavior is None or p.obj.outOfService:
                    continue
                try:
                    v = p.behavior.step(names, names[p.ident], dt)
                    if v is None:
                        continue
                    p.obj.presentValue = p.coerce(v)
                    names[p.ident] = p.read()
                    p.error = None
                except Exception as e:  # keep running, surface the error in the UI
                    msg = f"{type(e).__name__}: {e}"
                    if p.error != msg:
                        p.error = msg
                        self.log_event("error", f"{rt.cfg.name}/{p.cfg.name}: {msg}")
            for c in rt.controls:
                p = c.point
                try:
                    c.step(dt)
                    p.error = None
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    if p.error != msg:
                        p.error = msg
                        self.log_event("error", f"{rt.cfg.name}/{p.cfg.name}: {msg}")
            for ls in rt.lifesafety:
                try:
                    ls.step(dt)
                    ls.error = None
                except Exception as e:
                    ls.error = f"{type(e).__name__}: {e}"
            self._eval_life_safety(rt)
            self._run_alarms(rt)
            for tl in rt.trendlogs:
                tl.sample(self.sim_time, self.sim_epoch)

    def _scan_changes(self) -> None:
        now = time.time()
        changes = []
        for rt in self.devices.values():
            self._run_schedules(rt, only_dirty=True)  # picks up client writes while paused
            self._run_alarms(rt)  # also evaluates writes while paused (time delays need the clock to run)
            self._eval_life_safety(rt)
            for p in rt.points:
                st = p.status()
                k = (rt.cfg.device_id, p.key)
                if self._last.get(k) != st:
                    self._last[k] = st
                    changes.append({"d": rt.cfg.device_id, "k": p.key, **st})
                    p.history.append((now, float(st["value"])))
            for x in [*rt.trendlogs, *rt.calendars, *rt.schedules, *rt.files, *rt.programs, *rt.ees,
                      *rt.lifesafety]:
                st = x.status()
                k = (rt.cfg.device_id, x.key)
                if self._last.get(k) != st:
                    self._last[k] = st
                    changes.append({"d": rt.cfg.device_id, "k": x.key, **st})
        if changes:
            self.publish({"type": "values", "t": now, "sim_hour": self.sim_hour, "changes": changes})

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        nxt = loop.time()
        while not self._stopping:
            sim = self.config.simulation
            now = loop.time()
            if now >= nxt:
                async with self._lock:
                    if sim.running:
                        self.step(sim.tick_seconds * sim.time_scale)
                    self._scan_changes()
                    self._check_foreign()
                nxt = max(nxt + sim.tick_seconds, loop.time())
            try:
                await asyncio.wait_for(self._scan.wait(), timeout=max(0.0, nxt - loop.time()))
                self._scan.clear()
                async with self._lock:
                    self._scan_changes()
            except asyncio.TimeoutError:
                pass

    # ---- alarms (intrinsic reporting, see sme_bacnet_sim/alarm.py)

    def _run_alarms(self, rt: DeviceRuntime) -> None:
        if not rt.alarms:
            return
        ts = self.sim_epoch + self.sim_time
        for a in rt.alarms:
            tr = a.evaluate(self.sim_time, ts)
            if tr is None:
                continue
            frm, to = tr
            self.log_event("alarm", f"{rt.cfg.name}/{a.point.cfg.name}: {frm} -> {to} (priority {a.priority(to)}"
                           + (", ack required)" if a.unacked else ")"))
            idx = transition_index(to)
            if not a.event_enable[idx]:
                continue
            for r in a.nc.recipients:
                if r.accepts(idx, ts):
                    self._spawn(self._send_notification(rt, a, r, frm, to, ts))

    def _spawn(self, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:  # no event loop (synchronous use of step()): nothing can be sent
            coro.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resolve_device(self, rt: DeviceRuntime, device_id: int) -> Address:
        other = self.devices.get(device_id)
        if other is not None:  # another simulated device on the virtual network
            return Address(f"{self.config.network.virtual_network}:{int.from_bytes(other.mac, 'big')}")
        addr = self._dev_addr.get(device_id)
        if addr is None:
            iams = await rt.app.who_is(device_id, device_id, timeout=3)
            if not iams:
                raise LookupError(f"device {device_id} did not answer Who-Is")
            addr = self._dev_addr[device_id] = iams[0].pduSource
        return addr

    async def _send_notification(self, rt: DeviceRuntime, a: Alarm, r, frm: str, to: str, ts: float) -> None:
        if rt.app is None or rt.app.comm_state != "enable":  # DCC: initiation disabled
            return
        try:
            addr = r.address or await self._resolve_device(rt, r.cfg.device)
            if rt.app is None:
                return
            fut = rt.app.request(a.notification(rt.cfg.device_id, r, frm, to, ts, addr))
            if r.cfg.confirmed:
                await fut
        except Exception as e:  # recipient unreachable etc.: keep running, surface it in the event log
            if r.cfg.device is not None:
                self._dev_addr.pop(r.cfg.device, None)  # re-resolve next time
            self.log_event("error", f"{rt.cfg.name}/{a.point.cfg.name}: event notification to {r.label()} "
                                    f"failed: {type(e).__name__}: {e}")

    @staticmethod
    def _owner(rt: Optional[DeviceRuntime], key: str) -> Any:
        """Point or EventEnrollment with this key (both carry .cfg / .obj / .alarm), else None."""
        if rt is None:
            return None
        return rt.by_key.get(key) or next((e for e in rt.ees if e.key == key), None)

    def _alarm(self, device_id: int, oid: Any) -> Alarm:
        p = self._owner(self.devices.get(device_id), f"{ObjectType(oid[0])}:{oid[1]}")
        if p is None or p.alarm is None:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        return p.alarm

    def _sorted_alarms(self, device_id: int) -> List[Alarm]:
        return sorted(self.devices[device_id].alarms,
                      key=lambda a: (int(ObjectType(a.point.cfg.type)), a.point.cfg.instance))

    def bacnet_ack(self, device_id: int, apdu: Any) -> None:
        """AcknowledgeAlarm from a BACnet client."""
        a = self._alarm(device_id, apdu.eventObjectIdentifier)
        state = str(apdu.eventStateAcknowledged)
        idx = transition_index(state)
        if a.timestamps[idx] is None:
            raise ExecutionError(errorClass="services", errorCode="invalidEventState")
        ts = apdu.timestamp
        if ts is not None and ts._choice == "datetime" and str(ts) != str(timestamp(a.timestamps[idx])):
            raise ExecutionError(errorClass="services", errorCode="invalidTimeStamp")
        changed = a.acknowledge(idx)
        self.log_event("alarm-ack", f"device {device_id} {a.point.cfg.name}: {state} acknowledged by "
                                    f"{apdu.acknowledgmentSource!s} ({apdu.pduSource})"
                                    + ("" if changed else " (already acknowledged)"))
        self.request_scan()

    def acknowledge(self, device_id: int, key: str) -> None:
        """Operator acknowledgement from the web UI: all unacknowledged transitions of the object."""
        p = self._owner(self.devices.get(device_id), key)
        if p is None:
            raise KeyError(f"no object {key} on device {device_id}")
        if p.alarm is None:
            raise ValueError(f"{p.cfg.name} has no alarm")
        names = ["to-offnormal", "to-fault", "to-normal"]
        done = [names[i] for i in range(3) if p.alarm.acknowledge(i)]
        self.log_event("alarm-ack", f"device {device_id} {p.cfg.name}: {', '.join(done) or 'nothing'} "
                                    f"acknowledged (web UI)")
        self.request_scan()

    def event_information(self, device_id: int, apdu: Any) -> GetEventInformationACK:
        items = [a for a in self._sorted_alarms(device_id) if a.state != "normal" or a.unacked]
        last = apdu.lastReceivedObjectIdentifier
        if last is not None:
            lk = (int(last[0]), int(last[1]))
            items = [a for a in items if (int(ObjectType(a.point.cfg.type)), a.point.cfg.instance) > lk]
        return GetEventInformationACK(listOfEventSummaries=[a.event_summary() for a in items], moreEvents=False,
                                      context=apdu)

    def alarm_summary(self, device_id: int, apdu: Any) -> GetAlarmSummaryACK:
        return GetAlarmSummaryACK(listOfAlarmSummaries=[
            GetAlarmSummaryAlarmSummary(objectIdentifier=(a.point.cfg.type, a.point.cfg.instance), alarmState=a.state,
                                        acknowledgedTransitions=[int(x) for x in a.acked])
            for a in self._sorted_alarms(device_id) if a.notify_type == "alarm" and a.state != "normal"
        ], context=apdu)

    def enrollment_summary(self, device_id: int, apdu: Any) -> GetEnrollmentSummaryACK:
        """GetEnrollmentSummary with all filters (enrollmentFilter: a recipient + process of the object's NC)."""
        out = []
        ef = apdu.enrollmentFilter
        ack = str(apdu.acknowledgmentFilter)
        esf = str(apdu.eventStateFilter) if apdu.eventStateFilter is not None else None
        for a in self._sorted_alarms(device_id):
            if (ack == "acked" and a.unacked) or (ack == "not-acked" and not a.unacked):
                continue
            group = "normal" if a.state == "normal" else "fault" if a.state == "fault" else "offnormal"
            if (esf == "active" and a.state == "normal") or (esf in ("offnormal", "fault", "normal") and group != esf):
                continue
            if apdu.eventTypeFilter is not None and str(apdu.eventTypeFilter) != a.kind:
                continue
            pr = a.priority()
            pf = apdu.priorityFilter
            if pf is not None and not int(pf.minPriority) <= pr <= int(pf.maxPriority):
                continue
            if apdu.notificationClassFilter is not None and int(apdu.notificationClassFilter) != a.nc.number:
                continue
            if ef is not None and not any(_recipient_matches(r, ef) for r in a.nc.recipients):
                continue
            out.append(GetEnrollmentSummaryEnrollmentSummary(
                objectIdentifier=(a.point.cfg.type, a.point.cfg.instance), eventType=a.kind, eventState=a.state,
                priority=pr, notificationClass=a.nc.number))
        return GetEnrollmentSummaryACK(listOfEnrollmentSummaries=out, context=apdu)

    # ---- BACnet writes to alarm properties

    def check_alarm_write(self, device_id: int, oid: Any, prop: Any, value: Any) -> None:
        """Reject WriteProperty to Acked_Transitions (R) and to an unknown Notification_Class."""
        pid = str(PropertyIdentifier(prop))
        otype = str(ObjectType(oid[0]))
        if otype == SCHEDULE and pid == "list-of-object-property-references":
            try:
                refs = value.cast_out(ListOf(DeviceObjectPropertyReference)) if hasattr(value, "cast_out") else value
            except Exception:
                return  # wrong datatype: rejected by the write itself
            self.check_schedule_refs(device_id, oid, refs)
            return
        if (otype == FILE and pid in FILE_READONLY) or (otype == PROGRAM and pid in PROGRAM_READONLY) \
                or (otype in LIFE_SAFETY_TYPES and pid in LS_READONLY):
            raise ExecutionError(errorClass="property", errorCode="writeAccessDenied")
        if otype in LIFE_SAFETY_TYPES:
            ls = self._life_safety(device_id, oid)
            if ls is not None and pid == "present-value" and not ls.obj.outOfService:
                raise ExecutionError(errorClass="property", errorCode="writeAccessDenied")
            if ls is not None and pid == "mode":
                try:
                    mode = str(value.cast_out(LifeSafetyMode))
                except Exception:
                    raise ExecutionError(errorClass="property", errorCode="invalidDataType")
                if mode not in [str(m) for m in ls.obj.acceptedModes or []]:
                    raise ExecutionError(errorClass="property", errorCode="valueOutOfRange")
            return
        if pid not in ("acked-transitions", "notification-class") or str(ObjectType(oid[0])) == "notification-class":
            return
        p = self._owner(self.devices[device_id], f"{ObjectType(oid[0])}:{oid[1]}")
        if p is None or p.alarm is None:
            return
        if pid == "acked-transitions":
            raise ExecutionError(errorClass="property", errorCode="writeAccessDenied")
        try:
            n = int(value.cast_out(Unsigned))
        except Exception:
            raise ExecutionError(errorClass="property", errorCode="invalidDataType")
        if not any(nc.number == n for nc in self.devices[device_id].ncs):
            raise ExecutionError(errorClass="property", errorCode="valueOutOfRange")

    def alarm_written(self, device_id: int, oids: List[Any]) -> None:
        """After WriteProperty(Multiple): take over alarm property writes and keep them in the config."""
        rt = self.devices[device_id]
        for pg in rt.programs:  # Program_Change written by a client
            if any(str(ObjectType(o[0])) == PROGRAM and o[1] == pg.cfg.instance for o in oids):
                self._program_moved(pg, pg.poll(), "BACnet")
        written = {(str(ObjectType(o[0])), o[1]) for o in oids}
        for n in rt.ncs:  # Recipient_List written by a client: used for sending and kept in the config
            if (NOTIFICATION_CLASS, n.number) in written:
                self._sync_recipients(rt, n)
        for c in rt.calendars:  # Date_List written by a client: kept in the config
            if (CALENDAR, c.cfg.instance) in written:
                self._sync_calendar(rt, c)
        for sc in rt.schedules:  # List_Of_Object_Property_References / schedule content written by a client
            if (SCHEDULE, sc.cfg.instance) in written:
                self._sync_schedule_targets(rt, sc)
                self._sync_schedule_content(rt, sc)
        for z in rt.lifesafety:  # Zone_Members written by a client: kept in the config (member names)
            if z.zone and (z.cfg.type, z.cfg.instance) in written:
                names = member_names(z, rt.lifesafety)
                if names != (z.cfg.zone_members or []):
                    z.cfg.zone_members = names
                    o = next((o for o in rt.cfg.objects if o.name == z.cfg.name), None)
                    if o is not None and o is not z.cfg:
                        o.zone_members = names
                    self.log_event("life-safety", f"{rt.cfg.name}/{z.cfg.name}: zone members = {names}")
                self._eval_life_safety(rt)
        for oid in oids:
            p = self._owner(rt, f"{ObjectType(oid[0])}:{oid[1]}")
            if p is None or p.alarm is None:
                continue
            a = p.alarm
            nc_ref = None
            n = int(p.obj.notificationClass)
            if n != a.nc.number:
                nc = next((x for x in rt.ncs if x.number == n), None)
                if nc is None:  # WritePropertyMultiple bypasses check_alarm_write
                    p.obj.notificationClass = a.nc.number
                    self.log_event("error", f"{rt.cfg.name}/{p.cfg.name}: notification-class {n} does not exist")
                else:
                    a.nc, nc_ref = nc, nc.cfg.name
            changed, err = a.sync_from_object(nc_ref)
            if err:
                self.log_event("error", f"{rt.cfg.name}/{p.cfg.name}: alarm property write rejected: {err}")
            if not changed:
                continue
            if isinstance(p, EventEnrollment):  # the alarm config is the object config itself
                i = next((i for i, o in enumerate(rt.cfg.objects) if o.name == p.cfg.name), None)
                if i is None:
                    rt.cfg.objects.append(p.cfg)
                else:
                    rt.cfg.objects[i] = p.cfg  # persisted by Save / Export
                self.log_event("alarm", f"{rt.cfg.name}/{p.cfg.name}: event enrollment updated by BACnet write")
                continue
            p.cfg = p.cfg.model_copy(update={"alarm": a.cfg})
            o = next((o for o in rt.cfg.objects if o.name == p.cfg.name), None)
            if o is None:  # template object: add an override entry (merged by name, see expand_device)
                rt.cfg.objects.append(ObjectConfig(type=p.cfg.type, name=p.cfg.name, alarm=a.cfg))
            else:
                o.alarm = a.cfg  # persisted by Save / Export
            self.log_event("alarm", f"{rt.cfg.name}/{p.cfg.name}: alarm properties updated by BACnet write")

    def _sync_recipients(self, rt: DeviceRuntime, n: NotificationClass) -> None:
        """Notification class Recipient_List (BACnetDestination list) -> runtime recipients and config."""
        net = self.config.network.network_number

        def hms(t: Any) -> Optional[str]:
            h, m, sec = tuple(t)[:3]
            return None if 255 in (h, m, sec) else f"{h:02d}:{m:02d}:{sec:02d}"

        try:
            cfgs = []
            for d in n.obj.recipientList or []:
                days = [WEEKDAYS[i] for i, x in enumerate(d.validDays) if i < 7 and x]
                kw: Dict[str, Any] = dict(process_id=int(d.processIdentifier),
                                          confirmed=bool(d.issueConfirmedNotifications),
                                          transitions=[bool(x) for x in d.transitions],
                                          from_time=hms(d.fromTime), to_time=hms(d.toTime),
                                          days=None if len(days) == 7 else days)
                r = d.recipient
                if r.device is not None:
                    kw["device"] = int(r.device[1])
                else:
                    nn, mac = int(r.address.networkNumber), bytes(r.address.macAddress)
                    if len(mac) == 6 and nn == net:
                        kw["address"] = f"{'.'.join(str(b) for b in mac[:4])}:{int.from_bytes(mac[4:], 'big')}"
                    else:
                        kw["address"] = f"{nn}:{mac[0]}" if len(mac) == 1 else f"{nn}:0x{mac.hex()}"
                cfgs.append(RecipientConfig(**kw))
            n.recipients = [NCRecipient(c, net) for c in cfgs]
        except Exception as e:
            self.log_event("error", f"{rt.cfg.name}/{n.cfg.name}: recipient list not taken over: {e}")
            return
        self._persist(rt, n.cfg, recipients=cfgs)
        self.log_event("alarm", f"{rt.cfg.name}/{n.cfg.name}: recipient list updated ({len(cfgs)} recipient(s))")

    @staticmethod
    def _persist(rt: DeviceRuntime, cfg: ObjectConfig, **fields: Any) -> None:
        """Keep runtime changes of an object in the device config (persisted by Save / Export)."""
        for k, v in fields.items():
            setattr(cfg, k, v)
        o = next((o for o in rt.cfg.objects if o.name == cfg.name), None)
        if o is None:  # template object: add an override entry (merged by name, see expand_device)
            if cfg.type == SCHEDULE:  # an override entry must be a valid schedule on its own
                fields = {**{k: getattr(cfg, k) for k in ("weekly", "exceptions") if getattr(cfg, k) is not None},
                          **fields}
            rt.cfg.objects.append(ObjectConfig(type=cfg.type, name=cfg.name, **fields))
        elif o is not cfg:
            for k, v in fields.items():
                setattr(o, k, v)

    def _sync_calendar(self, rt: DeviceRuntime, c: Calendar) -> None:
        """Calendar Date_List (written / AddListElement / RemoveListElement) -> config ``dates``."""
        try:
            dates = [entry_to_cfg(e) for e in c.obj.dateList or []]
            for i, d in enumerate(dates):
                parse_calendar_entry(d, f"dates[{i}]")
        except Exception as e:
            self.log_event("error", f"{rt.cfg.name}/{c.cfg.name}: date list not kept in the config: {e}")
            return
        if dates == list(c.cfg.dates or []):
            return
        self._persist(rt, c.cfg, dates=dates)
        self.log_event("schedule", f"{rt.cfg.name}/{c.cfg.name}: date list updated ({len(dates)} entries)")

    def _schedule_targets(self, rt: DeviceRuntime, sc: Schedule, refs: Any) -> Tuple[List[Any], List[Any],
                                                                                    List[str], List[str]]:
        """Client references -> (config targets, points, labels, external); ValueError if not schedulable."""
        where = f"{rt.cfg.name}/{sc.cfg.name}"
        try:
            entries = refs_to_targets(rt.cfg, refs, rt.points, self.devices.values())
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from None
        targets, labels, external, _ = resolve_targets(rt.cfg, entries, rt.points, self.devices.values(), where)
        kinds = {_value_kind(p.cfg.type) for p in targets}
        if kinds and kinds != {sc.kind}:
            raise ValueError(f"{where}: targets must be {sc.kind} objects (the schedule datatype is fixed)")
        return entries, targets, labels, external

    def check_schedule_refs(self, device_id: int, oid: Any, refs: Any) -> None:
        """Reject a List_Of_Object_Property_References the schedule cannot write to (value-out-of-range)."""
        rt = self.devices[device_id]
        sc = next((x for x in rt.schedules if x.cfg.instance == oid[1]), None)
        if sc is None:
            return
        try:
            self._schedule_targets(rt, sc, refs)
        except ValueError as e:
            self.log_event("error", f"list-of-object-property-references rejected: {e}")
            raise ExecutionError(errorClass="property", errorCode="valueOutOfRange")

    def _sync_schedule_targets(self, rt: DeviceRuntime, sc: Schedule) -> None:
        """Schedule List_Of_Object_Property_References -> the points written by the schedule and config ``targets``."""
        try:
            entries, targets, labels, external = self._schedule_targets(rt, sc, sc.obj.listOfObjectPropertyReferences)
        except ValueError as e:  # WritePropertyMultiple skips check_schedule_refs: restore the configured targets
            sc.obj.listOfObjectPropertyReferences = resolve_targets(rt.cfg, sc.cfg.targets, rt.points,
                                                                    self.devices.values(), sc.cfg.name)[3]
            self.log_event("error", f"{e}; targets unchanged")
            return
        if [id(p) for p in targets] == [id(p) for p in sc.targets] and external == sc.external:
            return
        sc.targets, sc.labels, sc.external = targets, labels, external
        self._persist(rt, sc.cfg, targets=entries)
        self.log_event("schedule", f"{rt.cfg.name}/{sc.cfg.name}: targets = {', '.join(labels) or 'none'}")

    def _sync_schedule_content(self, rt: DeviceRuntime, sc: Schedule) -> None:
        """Weekly_Schedule / Exception_Schedule / Schedule_Default written by a client -> config ``weekly`` /
        ``exceptions`` / ``default`` (only the changed ones).  The schedule already runs on the new content; content
        the config cannot reproduce (configuration-error, calendar of another device, value the targets do not
        accept) is not kept and the config holds the last valid content."""
        where = f"{rt.cfg.name}/{sc.cfg.name}"
        try:
            new = schedule_to_cfg(sc.obj, rt.calendars)
            changed = {k: v for k, v in new.items() if v != sc.saved.get(k)}
            if not changed:
                return
            if str(sc.obj.reliability) != "no-fault-detected":
                raise ValueError(f"reliability {sc.obj.reliability}")
            oc = ObjectConfig.model_validate({**sc.cfg.model_dump(exclude_none=True), **new})
            build_schedule(rt.cfg, oc, rt.points, rt.calendars, self.devices.values())
        except Exception as e:
            self.log_event("error", f"{where}: schedule content not kept in the config: {e}")
            return
        sc.saved = new
        self._persist(rt, sc.cfg, **changed)
        self.log_event("schedule", f"{where}: {', '.join(changed)} updated by BACnet write")

    # ---- life safety (see sme_bacnet_sim/lifesafety.py)

    def _eval_life_safety(self, rt: DeviceRuntime) -> None:
        for ls in rt.lifesafety:  # points first, so zones see their members' new state
            ls.update(rt.lifesafety)

    def _life_safety(self, device_id: int, oid: Any) -> Optional[LifeSafety]:
        rt = self.devices.get(device_id)
        key = f"{ObjectType(oid[0])}:{oid[1]}"
        return next((x for x in rt.lifesafety if x.key == key), None) if rt else None

    def life_safety_operation(self, device_id: int, apdu: Any) -> None:
        rt = self.devices[device_id]
        op = str(apdu.request)
        if op.isdigit():  # vendor-specific operation
            raise ExecutionError(errorClass="services", errorCode="optionalFunctionalityNotSupported")
        if apdu.objectIdentifier is None:
            targets = list(rt.lifesafety)
        else:
            ls = self._life_safety(device_id, apdu.objectIdentifier)
            if ls is None:
                if rt.app.get_object_id(apdu.objectIdentifier) is None:
                    raise ExecutionError(errorClass="object", errorCode="unknownObject")
                raise ExecutionError(errorClass="object", errorCode="unsupportedObjectType")
            targets, i = [ls], 0
            while i < len(targets):  # a zone passes the operation on to its members (and their members)
                if targets[i].zone:
                    targets += [m for m in targets[i].members(rt.lifesafety) if m not in targets]
                i += 1
        for ls in reversed(targets):  # members first, so a zone reset sees the members' reset state
            if ls.zone:
                ls.update(rt.lifesafety)
            ls.operate(op)
        self._eval_life_safety(rt)
        self.log_event("life-safety", f"LifeSafetyOperation {op} from {apdu.pduSource} "
                                      f"({apdu.requestingSource}, process {int(apdu.requestingProcessIdentifier)}) "
                                      f"-> device {device_id} {', '.join(x.cfg.name for x in targets) or '(none)'}")
        self.request_scan()

    def set_life_safety(self, device_id: int, key: str, state: str) -> None:
        """Web UI: set the detector state (Tracking_Value) of a life safety point."""
        rt = self.devices.get(device_id)
        ls = next((x for x in rt.lifesafety if x.key == key), None) if rt else None
        if ls is None:
            raise KeyError(f"no life safety object {key} on device {device_id}")
        if ls.zone:
            raise ValueError("the tracking value of a zone follows its members")
        ls.set_tracking(state)
        self._eval_life_safety(rt)
        self.log_event("ui-write", f"device {device_id} {ls.cfg.name} tracking-value = {ls.tracking}")
        self.request_scan()

    # ---- text messages / private transfer

    def text_message_received(self, device_id: int, apdu: Any, confirmed: bool) -> None:
        src = apdu.textMessageSourceDevice
        mc = to_json(apdu.messageClass) if apdu.messageClass is not None else None
        cls = f", class {next(iter(mc.values()))}" if isinstance(mc, dict) and mc else ""
        self.log_event("text-message", f"{'Confirmed' if confirmed else 'Unconfirmed'}TextMessage from "
                                       f"{apdu.pduSource} (device {src[1]}) -> device {device_id} "
                                       f"[{apdu.messagePriority}{cls}]: {apdu.message}")

    async def send_text_message(self, device_id: int, message: str, address: Optional[str] = None,
                                priority: str = "normal", message_class: Any = None,
                                confirmed: bool = False) -> str:
        """Send a TextMessage from a simulated device (default: unconfirmed global broadcast)."""
        rt = self.devices.get(device_id)
        if rt is None or rt.app is None:
            raise KeyError(f"no device {device_id}")
        if rt.app.comm_state != "enable":
            raise ValueError(f"device {device_id}: communication is disabled (DeviceCommunicationControl)")
        dest = Address(address.strip()) if address else Address("*:*")
        shown = str(dest)
        if dest.addrType == Address.remoteStationAddr and dest.addrNet == self.config.network.virtual_network:
            # another simulated device: address it as a local station, or the answer would not match the request
            dest = Address(dest.addrAddr)
        if confirmed and dest.addrType not in (Address.remoteStationAddr, Address.localStationAddr):
            raise ValueError("a confirmed text message needs a station address")
        cls, mcls = ((ConfirmedTextMessageRequest, ConfirmedTextMessageRequestMessageClass) if confirmed
                     else (UnconfirmedTextMessageRequest, UnconfirmedTextMessageRequestMessageClass))
        req = cls(textMessageSourceDevice=("device", device_id), messagePriority=priority, message=message,
                  destination=dest)
        if message_class is not None and message_class != "":
            req.messageClass = mcls(numeric=int(message_class)) if str(message_class).isdigit() \
                else mcls(character=str(message_class))
        fut = rt.app.request(req)
        if confirmed:
            await asyncio.wait_for(fut, 10)
        self.log_event("text-message", f"device {device_id} sent {'Confirmed' if confirmed else 'Unconfirmed'}"
                                       f"TextMessage to {shown} [{priority}]: {message}")
        return shown

    def private_transfer(self, device_id: int, apdu: Any, confirmed: bool) -> Any:
        vid, num = int(apdu.vendorID), int(apdu.serviceNumber)
        rt = self.devices[device_id]
        match = next((x for x in rt.cfg.private_transfer or [] if x.vendor_id == vid and x.service_number == num),
                     None)
        kind = "Confirmed" if confirmed else "Unconfirmed"
        self.log_event("private-transfer", f"{kind}PrivateTransfer from {apdu.pduSource} -> device {device_id} "
                                           f"vendor {vid} service {num}"
                                           + (" with parameters" if apdu.serviceParameters is not None else "")
                                           + ("" if not confirmed else " (answered)" if match else " (not supported)"))
        if not confirmed:
            return None
        if match is None:
            return ConfirmedPrivateTransferError(
                errorType=ErrorType(errorClass="services", errorCode="optionalFunctionalityNotSupported"),
                vendorID=vid, serviceNumber=num, context=apdu)
        ack = ConfirmedPrivateTransferACK(vendorID=vid, serviceNumber=num, context=apdu)
        res = match.result
        if res == "echo":
            if apdu.serviceParameters is not None:
                ack.resultBlock = apdu.serviceParameters
        elif res is not None:
            if isinstance(res, bool):
                prim = Boolean(res)
            elif isinstance(res, int):
                prim = Unsigned(res) if res >= 0 else Integer(res)
            elif isinstance(res, float):
                prim = Real(res)
            else:
                prim = CharacterString(str(res))
            ack.resultBlock = AnyValue(prim)
        return ack

    async def change_list(self, device_id: int, apdu: Any, add: bool) -> None:
        """AddListElement / RemoveListElement: computed on the current list, then written like a WriteProperty
        of the whole list (same checks and follow-ups); raises CreateError (class, code, element number)."""
        rt = self.devices[device_id]
        oid = apdu.objectIdentifier
        if oid == ("device", 4194303):
            oid = rt.app.device_object.objectIdentifier
        obj = rt.app.get_object_id(oid)
        if obj is None:
            raise CreateError("object", "unknownObject")
        prop = PropertyIdentifier(apdu.propertyIdentifier)
        ptype = obj.get_property_type(prop)
        if ptype is None:
            raise CreateError("property", "unknownProperty")
        if apdu.propertyArrayIndex is not None:
            raise CreateError("property", "propertyIsNotAnArray")
        if not (isinstance(ptype, type) and issubclass(ptype, ListType)):
            raise CreateError("services", "propertyIsNotAList")
        if not property_writable(obj, prop.attr, self._readonly_props(rt, obj)):
            raise CreateError("property", "writeAccessDenied")
        try:
            elements = list(apdu.listOfElements.cast_out(ptype))
        except Exception:
            raise CreateError("property", "invalidDataType", 1)
        current = list(getattr(obj, prop.attr) or [])
        if add:
            new = list(current)
            for e in elements:
                if e not in new:  # elements already in the list are ignored
                    new.append(e)
        else:
            for i, e in enumerate(elements, start=1):
                if e not in current:
                    raise CreateError("services", "listElementNotFound", i)
            new = [c for c in current if c not in elements]
        if len(new) != len(current):
            if str(ObjectType(obj.objectIdentifier[0])) == SCHEDULE and prop.attr == "listOfObjectPropertyReferences":
                try:
                    self.check_schedule_refs(device_id, obj.objectIdentifier, new)
                except ExecutionError:
                    raise CreateError("property", "valueOutOfRange")
            try:
                await obj.write_property(prop.attr, ptype(new))
            except (ExecutionError, PropertyError) as e:
                raise CreateError(str(e.errorClass), str(e.errorCode))
            self.alarm_written(device_id, [obj.objectIdentifier])
        self.log_event("bacnet-write", f"{'AddListElement' if add else 'RemoveListElement'} from {apdu.pduSource} "
                                       f"-> device {device_id} {oid[0]},{oid[1]} {prop}: {len(elements)} element(s), "
                                       f"list now {len(new)}")
        self.request_scan()

    # ---- operator actions (from the web UI)

    def point(self, device_id: int, key: str) -> Point:
        rt = self.devices.get(device_id)
        if rt is None or key not in rt.by_key:
            raise KeyError(f"no object {key} on device {device_id}")
        return rt.by_key[key]

    async def write(self, device_id: int, key: str, value: Any, priority: Optional[int] = None) -> None:
        p = self.point(device_id, key)
        v = p.coerce(value)
        if p.commandable:
            await p.obj.write_property("presentValue", p.typed(v), priority=priority or 16)
            note = f" @priority {priority or 16}"
        else:
            if (p.behavior is not None or p.control is not None) and not p.obj.outOfService:
                p.obj.outOfService = True  # manual override of a simulated input
                note = " (set out-of-service to override behavior)"
            else:
                note = ""
            p.obj.presentValue = v
        self.log_event("ui-write", f"device {device_id} {p.cfg.name} = {value}{note}")
        self.request_scan()

    async def relinquish(self, device_id: int, key: str, priority: Optional[int] = None) -> None:
        p = self.point(device_id, key)
        if not p.commandable:
            raise ValueError("object is not commandable")
        if priority is None:
            priority = p.obj.currentCommandPriority.unsigned or 16
        await p.obj.write_property("presentValue", Null(()), priority=priority)
        self.log_event("ui-write", f"device {device_id} {p.cfg.name} relinquish @priority {priority}")
        self.request_scan()

    def set_oos(self, device_id: int, key: str, oos: bool) -> None:
        p = self.point(device_id, key)
        p.obj.outOfService = bool(oos)
        self.log_event("ui-write", f"device {device_id} {p.cfg.name} out-of-service = {bool(oos)}")
        self.request_scan()

    def trendlog(self, device_id: int, instance: int) -> TrendLog:
        rt = self.devices.get(device_id)
        tl = next((x for x in rt.trendlogs if x.cfg.instance == instance), None) if rt else None
        if tl is None:
            raise KeyError(f"no trend-log {instance} on device {device_id}")
        return tl

    # ---- file / program objects (see sme_bacnet_sim/fileprog.py)

    def file_for(self, device_id: int, oid: Any) -> SimFile:
        rt = self.devices[device_id]
        f = next((x for x in rt.files if x.cfg.instance == oid[1]), None)             if str(ObjectType(oid[0])) == FILE else None
        if f is None:
            obj = rt.app.get_object_id(oid) if rt.app is not None else None
            if obj is None:
                raise ExecutionError(errorClass="object", errorCode="unknownObject")
            raise ExecutionError(errorClass="services", errorCode="inconsistentObjectType")
        return f

    def write_file(self, device_id: int, apdu: Any) -> Any:
        f = self.file_for(device_id, apdu.fileIdentifier)
        ack = f.write(apdu, self.sim_epoch + self.sim_time)
        if f.cfg.path is None:  # mirror the content into the device config (auto-numbered objects are copies)
            o = next((o for o in self.devices[device_id].cfg.objects if o.name == f.cfg.name), None)
            if o is not None and o is not f.cfg:
                o.content = f.cfg.content
        self.log_event("bacnet-write", f"AtomicWriteFile from {apdu.pduSource} -> device {device_id} "
                                       f"{f.cfg.name} ({int(f.obj.fileSize)} bytes)")
        self.request_scan()
        return ack

    def _program_moved(self, pg: SimProgram, moved: Any, source: str) -> None:
        if moved is not None:
            self.log_event("program", f"{source}: device {pg.device_id} {pg.cfg.name} {moved[0]} -> {moved[1]}")
            self.request_scan()

    def program_change(self, device_id: int, instance: int, request: str, source: str = "UI") -> None:
        rt = self.devices.get(device_id)
        pg = next((x for x in rt.programs if x.cfg.instance == instance), None) if rt else None
        if pg is None:
            raise KeyError(f"program {instance} not found in device {device_id}")
        self._program_moved(pg, pg.apply(request), source)

    def set_trendlog_enable(self, device_id: int, instance: int, enabled: bool) -> None:
        tl = self.trendlog(device_id, instance)
        tl.obj.enable = bool(enabled)
        self.log_event("ui-write", f"device {device_id} {tl.cfg.name} enable = {bool(enabled)}")
        self.request_scan()

    def set_simulation(self, running: Optional[bool] = None, time_scale: Optional[float] = None) -> None:
        sim = self.config.simulation
        if running is not None:
            sim.running = running
        if time_scale is not None and time_scale > 0:
            sim.time_scale = time_scale
        self.publish({"type": "sim", "running": sim.running, "time_scale": sim.time_scale})

    def set_clock(self, ts: float, source: str) -> None:
        """Move the simulated clock so that sim_epoch + sim_time == ts (sim_time stays monotonic)."""
        now = time.monotonic()
        last = getattr(self, "_last_sync", None)
        self._last_sync = (round(ts, 1), now)
        self.sim_epoch = ts - self.sim_time
        for rt in self.devices.values():
            self._run_schedules(rt)
        if last is None or last[0] != round(ts, 1) or now - last[1] > 1.0:  # a broadcast reaches every device
            self.log_event("time-sync", f"{source}: simulated clock set to "
                                        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}")
        sim = self.config.simulation
        self.publish({"type": "sim", "running": sim.running, "time_scale": sim.time_scale, "sim_hour": self.sim_hour})
        self.request_scan()

    def set_dcc(self, device_id: int, state: str) -> None:
        rt = self.devices.get(device_id)
        if rt is None or rt.app is None:
            raise KeyError(f"no device {device_id}")
        if state not in ("enable", "disable", "disable-initiation"):
            raise ValueError("state must be enable / disable / disable-initiation")
        rt.app.set_comm(state, None, "web UI")

    # ---- device management services (CreateObject / DeleteObject / ReinitializeDevice)

    # ---- generic property access (web UI property grid)

    def _local_object(self, device_id: int, key: str) -> Tuple[DeviceRuntime, Any]:
        """Local BACnet object by ``type:instance`` key (any object, including the device object)."""
        rt = self.devices.get(device_id)
        t, _, inst = key.partition(":")
        obj = None
        if rt is not None and rt.app is not None and inst.isdigit():
            try:
                obj = rt.app.get_object_id(ObjectIdentifier(f"{t},{inst}"))
            except Exception:
                obj = None
        if obj is None:
            raise KeyError(f"no object {key} on device {device_id}")
        return rt, obj

    def _readonly_props(self, rt: DeviceRuntime, obj: Any) -> Set[str]:
        """Properties the simulator rejects on WriteProperty (see check_alarm_write)."""
        otype = str(ObjectType(obj.objectIdentifier[0]))
        ro = set(FILE_READONLY) if otype == FILE else set(PROGRAM_READONLY) if otype == PROGRAM \
            else set(LS_READONLY) if otype in LIFE_SAFETY_TYPES else set()
        p = self._owner(rt, f"{otype}:{obj.objectIdentifier[1]}")
        if p is not None and p.alarm is not None and otype != NOTIFICATION_CLASS:
            ro.add("acked-transitions")
        return ro

    def properties(self, device_id: int, key: str) -> List[Dict[str, Any]]:
        rt, obj = self._local_object(device_id, key)
        return list_properties(obj, self._readonly_props(rt, obj))

    async def write_property(self, device_id: int, key: str, prop: str, value: Any,
                             priority: Optional[int] = None) -> None:
        """Write one property the way an incoming WriteProperty request does (same checks and follow-ups)."""
        rt, obj = self._local_object(device_id, key)
        try:
            pid = PropertyIdentifier(prop)
        except Exception:
            raise KeyError(f"unknown property {prop!r}")
        datatype = obj.get_property_type(pid.attr) if pid.attr in obj._elements else None
        if datatype is None:
            raise KeyError(f"{key} has no property {prop!r}")
        if not property_writable(obj, pid.attr, self._readonly_props(rt, obj)):
            raise ValueError(f"{prop} is read-only")
        v = coerce_property(datatype, value, priority)
        try:
            self.check_alarm_write(device_id, obj.objectIdentifier, pid, AnyValue(v))
            await obj.write_property(pid.attr, v, priority=priority)
        except (ExecutionError, PropertyError) as e:
            raise ValueError(f"{prop}: {getattr(e, 'errorCode', e)}") from e
        self.alarm_written(device_id, [obj.objectIdentifier])
        self.log_event("ui-write", f"device {device_id} {key} {prop} = {value}"
                       + (f" @priority {priority}" if priority else ""))
        self.request_scan()

    def create_object(self, device_id: int, otype: Any, instance: Optional[int], values: List[Any],
                      source: str) -> Tuple[str, int]:
        """CreateObject: build a value object, add it to the device and to the config; raises CreateError."""
        rt = self.devices[device_id]
        t = str(ObjectType(otype))
        if t not in {k for k, _ in OBJECT_CLASSES} | {ACCUMULATOR, PULSE_CONVERTER}:
            raise CreateError("object", "dynamicCreationNotSupported")
        fields = initial_values(t, values)
        name_el = fields.pop("_name_element", 0)
        oos = fields.pop("_oos", False)
        used = {p.cfg.instance for p in rt.points if p.cfg.type == t}
        if instance is None:
            instance = next(n for n in range(1, len(used) + 2) if n not in used)
        elif instance in used or rt.app.get_object_id((t, instance)) is not None:
            raise CreateError("object", "objectIdentifierAlreadyExists")
        name = fields.pop("name", None) or f"{t}-{instance}"
        if rt.app.get_object_name(name) is not None:
            raise CreateError("object", "duplicateName", name_el)
        if t in MULTISTATE_TYPES and not fields.get("states"):
            fields["states"] = ["State 1", "State 2"]
        try:
            oc = ObjectConfig(type=t, instance=instance, name=name, **fields)
            obj = build_object(oc)
        except Exception:
            raise CreateError("property", "valueOutOfRange")
        if oos:
            obj.outOfService = True
        p = Point(device_id, oc, obj, None, deque(maxlen=self.config.simulation.history_size))
        rt.app.add_object(obj)
        rt.points.append(p)
        rt.by_key[p.key] = p
        dev = rt.cfg
        dev.objects.append(oc)  # persisted by Save / Export
        if dev.removed and name in dev.removed:
            dev.removed.remove(name)
        self.log_event("bacnet-create", f"{source}: device {device_id} created {t},{instance} {name!r}")
        self.publish({"type": "reload"})
        return (t, instance)

    def delete_object(self, device_id: int, oid: Any, source: str) -> None:
        """DeleteObject: only value objects that nothing else references can be deleted."""
        rt = self.devices[device_id]
        obj = rt.app.get_object_id(oid)
        if obj is None:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        p = rt.by_key.get(f"{ObjectType(oid[0])}:{oid[1]}")
        refs = [] if p is None else [tl.cfg.name for tl in rt.trendlogs if tl.target is p] + \
            [sc.cfg.name for r in self.devices.values() for sc in r.schedules if p in sc.targets] + \
            [c.point.cfg.name for c in rt.controls if p in c.refs] + \
            [e.cfg.name for e in rt.ees if e.target is p]
        if p is None or refs:  # device, network port, trend log, schedule, calendar, notification class, referenced
            self.log_event("bacnet-delete", f"{source}: device {device_id} {oid[0]},{oid[1]} not deleted"
                                            + (f" (referenced by {', '.join(refs)})" if refs else ""))
            raise ExecutionError(errorClass="object", errorCode="objectDeletionNotPermitted")
        rt.app.drop_object(obj)
        rt.points.remove(p)
        del rt.by_key[p.key]
        if p.control is not None:
            rt.controls.remove(p.control)
        if p.alarm is not None:
            rt.alarms.remove(p.alarm)
        self._last.pop((device_id, p.key), None)
        dev = rt.cfg
        dev.objects[:] = [o for o in dev.objects if o.name != p.cfg.name]
        if any(o.name == p.cfg.name for o in expand_device(dev)):  # still provided by the template
            dev.removed = [*(dev.removed or []), p.cfg.name]
        self.log_event("bacnet-delete", f"{source}: device {device_id} deleted {p.key} {p.cfg.name!r}")
        self.publish({"type": "reload"})

    async def reinitialize(self, device_id: int, cold: bool, source: str) -> None:
        """Warmstart: runtime state back to the config (values, priority arrays, alarms, behaviors, DCC).
        Coldstart: the same and the trend log buffers are cleared."""
        rt = self.devices[device_id]
        for p in rt.points:
            init = build_object(p.cfg)
            p.obj.outOfService = False
            if p.commandable:
                p.obj.relinquishDefault = init.relinquishDefault
                for prio in range(1, 17):
                    await p.obj.write_property("presentValue", Null(()), priority=prio)
            else:
                p.obj.presentValue = init.presentValue
            p.behavior = make_behavior(p.cfg.behavior, self.base_dir, p.cfg.type)
            if p.control is not None:
                p.control.reset()
            p.error = None
            if p.alarm is not None:
                p.obj.eventState = "normal"
                new = Alarm(p, p.alarm.nc)
                rt.alarms[rt.alarms.index(p.alarm)] = new
                p.alarm = new
        for e in rt.ees:
            new = EnrollmentAlarm(e, e.alarm.nc)
            rt.alarms[rt.alarms.index(e.alarm)] = new
            e.alarm = new
        if cold:
            for tl in rt.trendlogs:
                tl.obj.clear()
                tl.obj.totalRecordCount = 0
        for r in self.devices.values():  # rewrite scheduled values into the relinquished priority arrays
            for sc in r.schedules:
                if any(p.device_id == device_id for p in sc.targets):
                    sc.scheduled = UNSET_VALUE
                    sc.obj._dirty = True
            self._run_schedules(r, only_dirty=True)
        for ls in rt.lifesafety:
            ls.reset_to_config()
        self._eval_life_safety(rt)
        rt.app.set_comm("enable")  # a restart ends DeviceCommunicationControl
        self.log_event("reinit", f"{source}: device {device_id} {'coldstart' if cold else 'warmstart'}")
        self.request_scan()
        self.publish({"type": "reload"})

    # ---- views

    def snapshot(self) -> Dict[str, Any]:
        devices = []
        for rt in self.devices.values():
            objs = []
            for p in rt.points:
                c = p.cfg
                o = {
                    "k": p.key, "type": c.type, "instance": c.instance, "name": c.name,
                    "description": c.description, "units": c.units, "commandable": p.commandable,
                    "states": c.states, "active_text": c.active_text, "inactive_text": c.inactive_text,
                    "min": c.min, "max": c.max,
                    "behavior": (c.behavior or {}).get("type"), "behavior_spec": c.behavior,
                    "input": c.type in INPUT_TYPES,
                }
                if c.type == LOOP:
                    o["loop"] = {"controlled": c.controlled_object, "manipulated": c.manipulated_object,
                                 "setpoint_object": c.setpoint_object}
                if p.alarm is not None:
                    o["alarm"] = {"kind": p.alarm.kind, "nc": p.alarm.nc.number, "notify_type": p.alarm.notify_type}
                o.update(p.status())
                objs.append(o)
            for tl in rt.trendlogs:
                c = tl.cfg
                o = {
                    "k": tl.key, "type": c.type, "instance": c.instance, "name": c.name,
                    "description": c.description, "trendlog": True, "target": c.log_object,
                    "target_key": tl.target.key, "units": tl.target.cfg.units,
                    "log_property": c.log_property or "present-value", "log_interval": tl.interval,
                    "buffer_size": int(tl.obj.bufferSize),
                }
                o.update(tl.status())
                objs.append(o)
            for c in rt.calendars:
                o = {"k": c.key, "type": CALENDAR, "instance": c.cfg.instance, "name": c.cfg.name,
                     "description": c.cfg.description, "calendar": True}
                o.update(c.status())
                objs.append(o)
            for sc in rt.schedules:
                o = {"k": sc.key, "type": SCHEDULE, "instance": sc.cfg.instance, "name": sc.cfg.name,
                     "description": sc.cfg.description, "schedule": True, "kind": sc.kind,
                     "targets": sc.labels, "write_priority": sc.priority}
                o.update(sc.status())
                objs.append(o)
            for f in rt.files:
                o = {"k": f.key, "type": FILE, "instance": f.cfg.instance, "name": f.cfg.name,
                     "description": f.cfg.description, "file": True, "file_type": str(f.obj.fileType),
                     "access": "record" if not f.stream else "stream", "path": f.cfg.path}
                o.update(f.status())
                objs.append(o)
            for pg in rt.programs:
                o = {"k": pg.key, "type": PROGRAM, "instance": pg.cfg.instance, "name": pg.cfg.name,
                     "description": pg.cfg.description, "program": True, "instance_of": str(pg.obj.instanceOf)}
                o.update(pg.status())
                objs.append(o)
            for e in rt.ees:
                c, tc = e.cfg, e.target.cfg
                o = {"k": e.key, "type": EVENT_ENROLLMENT, "instance": c.instance, "name": c.name,
                     "description": c.description, "event_enrollment": True, "event_type": c.event_type,
                     "monitored": tc.name, "monitored_key": e.target.key, "units": tc.units,
                     "alarm": {"kind": e.alarm.kind, "nc": e.alarm.nc.number, "notify_type": e.alarm.notify_type}}
                o.update(e.status())
                objs.append(o)
            for ls in rt.lifesafety:
                c = ls.cfg
                o = {"k": ls.key, "type": c.type, "instance": c.instance, "name": c.name,
                     "description": c.description, "life_safety": True, "zone": ls.zone,
                     "members": member_names(ls, rt.lifesafety) if ls.zone else None,
                     "accepted_modes": [str(m) for m in ls.obj.acceptedModes or []],
                     "behavior": (c.behavior or {}).get("type")}
                o.update(ls.status())
                objs.append(o)
            for n in rt.ncs:  # read back from the object: BACnet clients may write Priority / Ack_Required
                objs.append({
                    "k": f"{NOTIFICATION_CLASS}:{n.number}", "type": NOTIFICATION_CLASS, "instance": n.number,
                    "name": n.cfg.name, "description": n.cfg.description, "notification_class": True,
                    "nc_priority": [int(x) for x in n.obj.priority],
                    "ack_required": [bool(x) for x in n.obj.ackRequired],
                    "recipients": [{"recipient": r.label(), "process_id": r.cfg.process_id,
                                    "confirmed": r.cfg.confirmed} for r in n.recipients],
                })
            devices.append({
                "device_id": rt.cfg.device_id, "name": rt.cfg.name, "description": rt.cfg.description,
                "template": rt.cfg.template, "mac": rt.mac.hex(),
                "comm": rt.app.comm_state if rt.app is not None else "enable",
                "address": f"{self.config.network.virtual_network}:{int.from_bytes(rt.mac, 'big')}",
                "objects": objs,
            })
        net = self.config.network
        return {
            "version": __version__,
            "network": {"bind": self.bind_address, "virtual_network": net.virtual_network,
                        "router_device_id": net.router.device_id, "mode": net.mode,
                        "foreign_device": dict(self.foreign) if self.foreign else None},
            "simulation": self.config.simulation.model_dump(),
            "sim_hour": self.sim_hour,
            "config_path": self.config_path,
            "devices": devices,
            "events": list(self.events)[-50:],
        }

    def history(self, device_id: int, key: str) -> List[Tuple[float, float]]:
        return list(self.point(device_id, key).history)
