"""Accumulator, Pulse Converter and Loop objects.

The object classes are bacpypes3's ``AccumulatorObject`` / ``PulseConverterObject`` / ``LoopObject`` (property
definitions) combined with the local ``Object`` (property list, monitors), with the COV criteria bacpypes3
defines for them (Pulse Converter: COV increment, Loop: generic; bacpypes3 has none for Accumulator).

Runtime (called from ``Engine.step``):

* :class:`PulseInput` -- a pulse converter with ``input_object`` adds the count delta of that accumulator,
  times Scale_Factor, to its Present_Value (wrap-around of the accumulator is taken into account).
* :class:`PidLoop` -- textbook PID: ``output = bias + Kp * e + Ki * integral(e dt) + Kd * de/dt`` with
  ``e = PV - setpoint`` (direct action) or ``setpoint - PV`` (reverse), clamped to Minimum_Output ..
  Maximum_Output with conditional integration (anti-windup).  Every Update_Interval the output goes to
  Present_Value and to the manipulated object (its priority array at Priority_For_Writing when it is
  commandable).  Gains, setpoint, action, limits and interval are read from the object each time, so clients
  can tune the loop with WriteProperty.  Out of service: no computation and no output write.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bacpypes3.basetypes import ObjectPropertyReference, PriorityValue, SetpointReference
from bacpypes3.local.cov import GenericCriteria, PulseConverterCriteria
from bacpypes3.local.object import Object as _Object
from bacpypes3.object import (
    AccumulatorObject as _AccumulatorObject,
    LoopObject as _LoopObject,
    PulseConverterObject as _PulseConverterObject,
)

from .config import ACCUMULATOR, LOOP, PULSE_CONVERTER, DeviceConfig, ObjectConfig

ACC_MAX_DEFAULT = 4294967295  # max-pres-value when the config gives no max (Unsigned32 range)


class AccumulatorObject(_Object, _AccumulatorObject):
    pass


class PulseConverterObject(_Object, _PulseConverterObject):
    _cov_criteria = PulseConverterCriteria


class LoopObject(_Object, _LoopObject):
    _cov_criteria = GenericCriteria


CONTROL_CLASSES = {ACCUMULATOR: AccumulatorObject, PULSE_CONVERTER: PulseConverterObject, LOOP: LoopObject}


def acc_max(oc: ObjectConfig) -> int:
    return int(oc.max) if oc.max is not None else ACC_MAX_DEFAULT


def control_kwargs(oc: ObjectConfig, cov_increment: float) -> Dict[str, Any]:
    """Type-specific constructor arguments; references to other objects are set by :func:`build_controls`."""
    kw: Dict[str, Any] = {}
    if oc.type == ACCUMULATOR:
        mx = acc_max(oc)
        kw["presentValue"] = min(mx, max(0, int(oc.value or 0)))
        kw["units"] = oc.units or "no-units"
        kw["scale"] = {"floatScale": float(oc.scale if oc.scale is not None else 1.0)}
        kw["maxPresValue"] = mx
        if oc.prescale is not None:
            kw["prescale"] = {"multiplier": oc.prescale[0], "moduloDivide": oc.prescale[1]}
    elif oc.type == PULSE_CONVERTER:
        kw["presentValue"] = float(oc.value or 0.0)
        kw["units"] = oc.units or "no-units"
        kw["scaleFactor"] = float(oc.scale_factor if oc.scale_factor is not None else 1.0)
        kw["adjustValue"] = 0.0
        kw["count"] = 0
        kw["covIncrement"] = cov_increment
        kw["covPeriod"] = 0
    else:  # loop
        lo = float(oc.min) if oc.min is not None else 0.0
        hi = float(oc.max) if oc.max is not None else 100.0
        kw["presentValue"] = min(hi, max(lo, float(oc.value if oc.value is not None else lo)))
        kw["outputUnits"] = oc.units or "no-units"
        kw["updateInterval"] = int(round((oc.update_interval or 1.0) * 1000))  # milliseconds
        kw["setpoint"] = float(oc.setpoint or 0.0)
        kw["setpointReference"] = SetpointReference()
        kw["action"] = oc.action or "direct"
        kw["proportionalConstant"] = float(oc.proportional_constant if oc.proportional_constant is not None else 1.0)
        kw["integralConstant"] = float(oc.integral_constant or 0.0)
        kw["derivativeConstant"] = float(oc.derivative_constant or 0.0)
        kw["proportionalConstantUnits"] = "no-units"
        kw["integralConstantUnits"] = "per-second"
        kw["derivativeConstantUnits"] = "seconds"
        kw["bias"] = float(oc.bias or 0.0)
        kw["minimumOutput"] = lo
        kw["maximumOutput"] = hi
        kw["priorityForWriting"] = oc.priority_for_writing or 16
        kw["covIncrement"] = cov_increment
    return kw


def _ref(p: Any) -> ObjectPropertyReference:
    return ObjectPropertyReference(objectIdentifier=(p.cfg.type, p.cfg.instance), propertyIdentifier="presentValue")


def _target(dev: DeviceConfig, points: List[Any], owner: str, field: str, name: str) -> Any:
    p = next((x for x in points if x.cfg.name == name), None)
    if p is None or p.cfg.name == owner:
        raise ValueError(f"device {dev.name} ({dev.device_id}): {owner}: {field} {name!r} is not another "
                         "value object of this device")
    return p


class PulseInput:
    """Pulse converter fed by an accumulator of the same device."""

    def __init__(self, point: Any, acc: Any) -> None:
        self.point, self.acc = point, acc
        self.last: Optional[int] = int(acc.read())

    @property
    def refs(self) -> List[Any]:
        return [self.acc]

    def reset(self) -> None:
        self.last = None

    def step(self, dt: float) -> None:
        n = int(self.acc.read())
        obj = self.point.obj
        last = n if self.last is None else self.last
        d = n - last
        if d < 0:  # wrap-around past max-pres-value (a jump back near 0 from the lower half is a reset)
            mx = int(self.acc.obj.maxPresValue)
            d = n + mx + 1 - last if last > mx // 2 else n
        self.last = n
        if int(obj.count) != n:
            obj.count = n
        if d and not obj.outOfService:
            obj.presentValue = float(obj.presentValue) + d * float(obj.scaleFactor)


class PidLoop:
    """PID controller of a Loop object (see module docstring)."""

    def __init__(self, point: Any, controlled: Any, manipulated: Any, setpoint: Optional[Any]) -> None:
        self.point, self.cv, self.mv, self.sp = point, controlled, manipulated, setpoint
        self.reset()

    @property
    def refs(self) -> List[Any]:
        return [x for x in (self.cv, self.mv, self.sp) if x is not None]

    def reset(self) -> None:
        self.integral = 0.0
        self.prev_error: Optional[float] = None
        self.elapsed = 0.0

    def step(self, dt: float) -> None:
        obj = self.point.obj
        self.elapsed += dt
        if self.elapsed + 1e-9 < int(obj.updateInterval) / 1000:
            return
        h, self.elapsed = self.elapsed, 0.0
        pv = float(self.cv.read())
        obj.controlledVariableValue = pv
        if self.sp is not None:
            obj.setpoint = float(self.sp.read())
        if obj.outOfService:
            self.prev_error = None
            return
        sp = float(obj.setpoint)
        e = sp - pv if str(obj.action) == "reverse" else pv - sp
        kp, ki, kd = float(obj.proportionalConstant), float(obj.integralConstant), float(obj.derivativeConstant)
        lo, hi = float(obj.minimumOutput), float(obj.maximumOutput)
        bias = float(obj.bias)
        deriv = 0.0 if self.prev_error is None or h <= 0 else (e - self.prev_error) / h
        integral = self.integral + e * h
        out = bias + kp * e + ki * integral + kd * deriv
        if (out > hi and ki * e > 0) or (out < lo and ki * e < 0):  # anti-windup: hold the integral
            integral = self.integral
            out = bias + kp * e + ki * integral + kd * deriv
        self.integral, self.prev_error = integral, e
        out = min(hi, max(lo, out))
        obj.presentValue = out
        v = self.mv.coerce(out)
        if self.mv.commandable:
            prio = min(16, max(1, int(obj.priorityForWriting)))
            self.mv.obj.priorityArray[prio - 1] = PriorityValue(self.mv.typed(v))
        else:
            self.mv.obj.presentValue = v


def build_controls(dev: DeviceConfig, points: List[Any]) -> List[Any]:
    """Resolve references of pulse converters and loops; sets ``point.control``.  Pulse inputs come first."""
    pulses, loops = [], []
    for p in points:
        c = p.cfg
        if c.type == PULSE_CONVERTER and c.input_object:
            acc = _target(dev, points, c.name, "input_object", c.input_object)
            if acc.cfg.type != ACCUMULATOR:
                raise ValueError(f"device {dev.name} ({dev.device_id}): {c.name}: input_object "
                                 f"{c.input_object!r} is not an accumulator")
            p.obj.inputReference = _ref(acc)
            p.control = PulseInput(p, acc)
            pulses.append(p.control)
        elif c.type == LOOP:
            cv = _target(dev, points, c.name, "controlled_object", c.controlled_object)
            mv = _target(dev, points, c.name, "manipulated_object", c.manipulated_object)
            sp = _target(dev, points, c.name, "setpoint_object", c.setpoint_object) if c.setpoint_object else None
            p.obj.controlledVariableReference = _ref(cv)
            p.obj.manipulatedVariableReference = _ref(mv)
            p.obj.controlledVariableUnits = cv.cfg.units or "no-units"
            p.obj.controlledVariableValue = float(cv.read())
            if sp is not None:
                p.obj.setpointReference = SetpointReference(setpointReference=_ref(sp))
                p.obj.setpoint = float(sp.read())
            p.control = PidLoop(p, cv, mv, sp)
            loops.append(p.control)
    return pulses + loops
