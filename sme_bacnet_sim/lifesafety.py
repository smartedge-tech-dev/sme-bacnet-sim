"""Life Safety Point / Life Safety Zone objects and the LifeSafetyOperation service.

The detailed state machine of these objects (latching rules, mode dependent transitions, the severity order of
the states, change-of-life-safety reporting) is only defined in ASHRAE 135, so the simulator uses a small,
documented model instead:

* Tracking_Value is the live detector state.  On a point it is set by the config (``value``), the web UI or a
  ``behavior`` (see ``LifeSafety.step``); on a zone it is derived from the members: the Present_Value of the
  first member (in Zone_Members order) that is not ``quiet``, else ``quiet`` (a simplification: no severity order).
* Present_Value follows Tracking_Value while that is not ``quiet`` and stays latched when it returns to
  ``quiet``, until a reset operation.  While Out_Of_Service the engine leaves Present_Value alone (clients may
  write it then).
* LifeSafetyOperation: ``silence*`` / ``unsilence*`` set / clear the audible and visible bits of Silenced;
  ``reset`` / ``reset-alarm`` / ``reset-fault`` copy Tracking_Value to Present_Value and unsilence;
  ``none`` does nothing.  An operation on a zone also applies to its members; without an object identifier it
  applies to every life safety object of the device.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bacpypes3.basetypes import DeviceObjectReference
from bacpypes3.errors import ExecutionError
from bacpypes3.local.object import Object as _Object
from bacpypes3.object import LifeSafetyPointObject as _LSP, LifeSafetyZoneObject as _LSZ

from .config import LIFE_SAFETY_POINT, LIFE_SAFETY_ZONE, ObjectConfig

# properties a client may not write (WriteProperty answers write-access-denied)
LS_READONLY = {"tracking-value", "operation-expected"}
DEFAULT_MODES = ["off", "on", "test"]

_SILENCE_BITS = {"unsilenced": 0, "audible-silenced": 1, "visible-silenced": 2, "all-silenced": 3}
_BITS_SILENCE = {v: k for k, v in _SILENCE_BITS.items()}
# operation -> (bits to set, bits to clear)
_SILENCE_OPS = {"silence": (3, 0), "silence-audible": (1, 0), "silence-visual": (2, 0),
                "unsilence": (0, 3), "unsilence-audible": (0, 1), "unsilence-visual": (0, 2)}
_RESET_OPS = {"reset", "reset-alarm", "reset-fault"}


class LifeSafetyPointObject(_Object, _LSP):
    async def _post_init(self) -> None:
        pass  # no notification-class lookup (change-of-life-safety reporting is not supported)


class LifeSafetyZoneObject(_Object, _LSZ):
    async def _post_init(self) -> None:
        pass


@dataclass
class LifeSafety:
    device_id: int
    cfg: ObjectConfig
    obj: Any
    error: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.cfg.type}:{self.cfg.instance}"

    @property
    def zone(self) -> bool:
        return self.cfg.type == LIFE_SAFETY_ZONE

    @property
    def present(self) -> str:
        return str(self.obj.presentValue)

    @property
    def tracking(self) -> str:
        return str(self.obj.trackingValue)

    def members(self, peers: List["LifeSafety"]) -> List["LifeSafety"]:
        """Zone_Members resolved to life safety objects of this device (other devices are ignored)."""
        out = []
        for ref in self.obj.zoneMembers or []:
            if ref.deviceIdentifier is not None and ref.deviceIdentifier[1] != self.device_id:
                continue
            oid = (str(ref.objectIdentifier[0]), ref.objectIdentifier[1])
            m = next((p for p in peers if (p.cfg.type, p.cfg.instance) == oid and p is not self), None)
            if m is not None:
                out.append(m)
        return out

    def set_tracking(self, state: str) -> None:
        self._random_hit = False
        self.obj.trackingValue = state

    def step(self, dt: float) -> None:
        """Optional ``behavior: {type: random_alarm, probability: <per sim second>, state: alarm}``:
        the detector goes to ``state`` at random and back to ``quiet`` on the next tick. A state set from the
        UI or by a BACnet write stays until it is changed again."""
        b = self.cfg.behavior
        if self.zone or not b or self.obj.outOfService:
            return
        if getattr(self, "_random_hit", False):  # only undo a state the behavior set itself
            self._random_hit = False
            if self.tracking != "quiet":
                self.set_tracking("quiet")
        elif self.tracking == "quiet" and random.random() < float(b.get("probability", 0.001)) * dt:
            self.set_tracking(str(b.get("state", "alarm")))
            self._random_hit = True

    def update(self, peers: List["LifeSafety"]) -> None:
        """Derive a zone's Tracking_Value; latch Present_Value (see the module docstring)."""
        if self.zone:
            hot = [m.present for m in self.members(peers) if m.present != "quiet"]
            t = hot[0] if hot else "quiet"
            if self.tracking != t:
                self.obj.trackingValue = t
        if self.obj.outOfService:
            return
        t = self.tracking
        if t != "quiet" and self.present != t:
            self.obj.presentValue = t

    def operate(self, op: str) -> None:
        if op in _SILENCE_OPS:
            on, off = _SILENCE_OPS[op]
            bits = (_SILENCE_BITS.get(str(self.obj.silenced), 0) | on) & ~off
            self.obj.silenced = _BITS_SILENCE[bits]
        elif op in _RESET_OPS:
            self.obj.silenced = "unsilenced"
            if not self.obj.outOfService:
                self.obj.presentValue = self.tracking
        elif op != "none":
            raise ExecutionError(errorClass="services", errorCode="optionalFunctionalityNotSupported")

    def reset_to_config(self) -> None:
        """ReinitializeDevice: back to the configured state."""
        state = self.cfg.value or "quiet"
        self.obj.outOfService = False
        self.obj.trackingValue = state
        self.obj.presentValue = state
        self.obj.silenced = self.cfg.silenced or "unsilenced"
        self.obj.mode = self.cfg.mode or "on"

    def status(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"value": self.present, "tracking": self.tracking, "silenced": str(self.obj.silenced),
                             "mode": str(self.obj.mode), "oos": bool(self.obj.outOfService)}
        if self.error:
            d["error"] = self.error
        return d


def build_life_safety(device_id: int, oc: ObjectConfig) -> LifeSafety:
    state = oc.value or "quiet"
    kw: Dict[str, Any] = dict(
        objectIdentifier=(oc.type, oc.instance), objectName=oc.name, presentValue=state, trackingValue=state,
        statusFlags=[0, 0, 0, 0], eventState="normal", reliability="no-fault-detected", outOfService=False,
        mode=oc.mode or "on", acceptedModes=list(oc.accepted_modes or DEFAULT_MODES),
        silenced=oc.silenced or "unsilenced", operationExpected=oc.operation_expected or "none",
    )
    if oc.description:
        kw["description"] = oc.description
    if oc.type == LIFE_SAFETY_POINT:
        return LifeSafety(device_id, oc, LifeSafetyPointObject(**kw))
    return LifeSafety(device_id, oc, LifeSafetyZoneObject(zoneMembers=[], **kw))


def link_zones(where: str, items: List[LifeSafety]) -> None:
    """Resolve the zone_members names of every zone (same device); raises on an unknown name."""
    for z in items:
        if not z.zone:
            continue
        refs = []
        for name in z.cfg.zone_members or []:
            m = next((x for x in items if x.cfg.name == name), None)
            if m is None or m is z:
                raise ValueError(f"{where}: {z.cfg.name}: zone member {name!r} is not another life safety object "
                                 f"of this device")
            refs.append(DeviceObjectReference(objectIdentifier=(m.cfg.type, m.cfg.instance)))
        z.obj.zoneMembers = refs


def member_names(z: LifeSafety, items: List[LifeSafety]) -> List[str]:
    return [m.cfg.name for m in z.members(items)]
