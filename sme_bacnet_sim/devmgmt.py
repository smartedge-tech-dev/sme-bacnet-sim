"""Device management helpers for services bacpypes3 0.1.0 does not serve (or serves incompletely).

* ``cov_class``: bacpypes3 computes ``statusFlags`` from eventState / reliability / outOfService, so the
  property monitors of statusFlags (and with them COV detection) never fire.  The wrapper fires them.
* ``PropertySubscription``: server side of SubscribeCOVProperty (bacpypes3 has none).
* ``initial_values``: CreateObject listOfInitialValues -> ObjectConfig fields.
* ``sync_time``: TimeSynchronization / UTCTimeSynchronization date-time -> epoch seconds.
"""

from __future__ import annotations

import asyncio
import calendar
import functools
import time
from typing import Any, Dict, List, Optional

from bacpypes3.apdu import ConfirmedCOVNotificationRequest, UnconfirmedCOVNotificationRequest
from bacpypes3.basetypes import BinaryPV, EngineeringUnits, PropertyIdentifier, PropertyValue
from bacpypes3.constructeddata import Any as BAny, ArrayOf
from bacpypes3.primitivedata import Boolean, CharacterString, Real, Unsigned

from .config import ACCUMULATOR, BINARY_TYPES, REAL_TYPES
from .trendlog import from_datetime

_STATUS_INPUTS = ("eventState", "reliability", "outOfService")


@functools.lru_cache(maxsize=None)
def cov_class(cls: type) -> type:
    """Subclass of ``cls`` that tells statusFlags monitors when one of its inputs changes."""

    class _StatusFlagsCOV(cls):  # type: ignore[valid-type, misc]
        def __setattr__(self, attr: str, value: Any) -> None:
            mons = self.__dict__.get("_property_monitors")
            if attr not in _STATUS_INPUTS or not mons or not mons.get("statusFlags"):
                super().__setattr__(attr, value)
                return
            old = self.statusFlags
            super().__setattr__(attr, value)
            new = self.statusFlags
            if list(old) != list(new):
                for fn in list(mons["statusFlags"]):
                    fn(old, new)

    return _StatusFlagsCOV


# --------------------------------------------------------------------------- SubscribeCOVProperty


class PropertySubscription:
    """One SubscribeCOVProperty subscription; notifies on property change (with increment) and status flags."""

    def __init__(self, app: Any, addr: Any, proc_id: int, obj: Any, prop: PropertyIdentifier,
                 index: Optional[int]) -> None:
        self.app, self.addr, self.proc_id, self.obj = app, addr, proc_id, obj
        self.prop, self.index, self.attr = prop, index, prop.attr
        self.confirmed = False
        self.increment: Optional[float] = None
        self.reported: Any = None
        self.handle: Optional[asyncio.TimerHandle] = None
        self.expires = 0.0
        self._pending = False
        mons = obj._property_monitors
        mons[self.attr].append(self._changed)
        if self.attr != "statusFlags":
            mons["statusFlags"].append(self._flags_changed)

    @property
    def key(self) -> tuple:
        return (self.addr, self.proc_id, self.obj.objectIdentifier, self.prop, self.index)

    def renew(self, lifetime: Optional[int]) -> None:
        if self.handle:
            self.handle.cancel()
            self.handle = None
        if lifetime:
            loop = asyncio.get_running_loop()
            self.expires = loop.time() + lifetime
            self.handle = loop.call_later(lifetime, self.app.cancel_property_subscription, self)

    def cancel(self) -> None:
        if self.handle:
            self.handle.cancel()
            self.handle = None
        for attr, fn in ((self.attr, self._changed), ("statusFlags", self._flags_changed)):
            try:
                self.obj._property_monitors[attr].remove(fn)
            except ValueError:
                pass

    def _value(self) -> Any:
        v = getattr(self.obj, self.attr)
        return v[self.index] if self.index is not None else v

    def _changed(self, old: Any, new: Any) -> None:
        inc = self.increment
        if inc is not None and self.reported is not None and isinstance(self.reported, float):
            try:
                if abs(float(self._value()) - float(self.reported)) < inc:
                    return
            except (TypeError, ValueError):
                pass
        self.schedule()

    def _flags_changed(self, old: Any, new: Any) -> None:
        self.schedule()

    def schedule(self) -> None:
        if not self._pending:
            self._pending = True
            asyncio.get_running_loop().call_soon(self.send)

    def send(self) -> None:
        self._pending = False
        if self.obj._app is None:
            return
        value = self._value()
        self.reported = value
        values = [PropertyValue(propertyIdentifier=self.prop, propertyValue=BAny(value))]
        if self.index is not None:
            values[0].propertyArrayIndex = self.index
        if self.attr != "statusFlags":
            values.append(PropertyValue(propertyIdentifier="status-flags", propertyValue=BAny(self.obj.statusFlags)))
        remaining = max(1, int(self.expires - asyncio.get_running_loop().time())) if self.handle else 0
        req = ConfirmedCOVNotificationRequest() if self.confirmed else UnconfirmedCOVNotificationRequest()
        req.pduDestination = self.addr
        req.subscriberProcessIdentifier = self.proc_id
        req.initiatingDeviceIdentifier = self.app.device_object.objectIdentifier
        req.monitoredObjectIdentifier = self.obj.objectIdentifier
        req.timeRemaining = remaining
        req.listOfValues = values
        self.app.cov_notification(None, req)


# --------------------------------------------------------------------------- CreateObject


class CreateError(Exception):
    def __init__(self, error_class: str, error_code: str, element: int = 0) -> None:
        super().__init__(f"{error_class}/{error_code} (element {element})")
        self.error_class, self.error_code, self.element = error_class, error_code, element


_TEXT = {"object-name": "name", "description": "description", "active-text": "active_text",
         "inactive-text": "inactive_text"}
_IGNORED = {"object-identifier", "object-type"}  # must match the object specifier; nothing to store


def initial_values(otype: str, values: List[Any]) -> Dict[str, Any]:
    """CreateObject listOfInitialValues -> ObjectConfig fields; raises CreateError (1-based element)."""
    out: Dict[str, Any] = {}
    for i, pv in enumerate(values or [], start=1):
        pid = str(PropertyIdentifier(pv.propertyIdentifier))
        a = pv.propertyValue
        try:
            if pid in _TEXT:
                out[_TEXT[pid]] = str(a.cast_out(CharacterString))
            elif pid == "units" and (otype in REAL_TYPES or otype == ACCUMULATOR):
                out["units"] = str(a.cast_out(EngineeringUnits))
            elif pid == "cov-increment" and otype in REAL_TYPES:
                out["cov_increment"] = float(a.cast_out(Real))
            elif pid == "state-text" and otype not in REAL_TYPES | BINARY_TYPES | {ACCUMULATOR}:
                out["states"] = [str(s) for s in a.cast_out(ArrayOf(CharacterString))]
            elif pid == "out-of-service":
                out["_oos"] = bool(a.cast_out(Boolean))
            elif pid == "present-value":
                if otype in REAL_TYPES:
                    out["value"] = float(a.cast_out(Real))
                elif otype in BINARY_TYPES:
                    out["value"] = 1 if str(a.cast_out(BinaryPV)) == "active" else 0
                else:
                    out["value"] = int(a.cast_out(Unsigned))
            elif pid in _IGNORED:
                pass
            else:
                raise CreateError("property", "writeAccessDenied", i)
        except CreateError:
            raise
        except Exception:
            raise CreateError("property", "invalidDataType", i)
        if pid == "object-name":
            out["_name_element"] = i
    return out


# --------------------------------------------------------------------------- time synchronization


def sync_time(dt: Any, utc: bool) -> float:
    """BACnet DateTime (local or UTC) -> epoch seconds."""
    local = from_datetime(dt)  # fields interpreted as local time
    if not utc:
        return local
    return calendar.timegm(time.localtime(local)[:6] + (0, 0, 0)) + (local % 1)
