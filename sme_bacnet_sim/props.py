"""Generic property access for the web UI property grid.

Reads every property of a bacpypes3 local object and converts it to JSON; writes basic-typed properties
(real / double / unsigned / integer / boolean / enumerated / character string). Constructed values (arrays,
lists, sequences) are shown as JSON and are read-only here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from bacpypes3.basetypes import PropertyIdentifier
from bacpypes3.constructeddata import AnyAtomic, Array, Choice, Sequence
from bacpypes3.json.util import atomic_encode, sequence_to_json
from bacpypes3.local.cmd import Commandable
from bacpypes3.primitivedata import (
    Atomic, BitString, Boolean, CharacterString, Double, Enumerated, Integer, Null, Real, Unsigned,
)

# Identity properties the UI never writes (bacpypes3 local objects would accept a write and break the object).
UI_READONLY = {"object-identifier", "object-type", "property-list"}

_KINDS = ((Boolean, "boolean"), (Real, "real"), (Double, "double"), (Unsigned, "unsigned"), (Integer, "integer"),
          (Enumerated, "enumerated"), (CharacterString, "charstring"))


def kind_of(datatype: Any) -> Optional[str]:
    """Editable kind of a property datatype, None for constructed / other types."""
    if not isinstance(datatype, type):
        return None
    for cls, kind in _KINDS:
        if issubclass(datatype, cls):
            return kind
    return None


def to_json(v: Any) -> Any:
    """BACnet value -> JSON-compatible value (falls back to str())."""
    if v is None:
        return None
    try:
        if isinstance(v, AnyAtomic):
            return to_json(v.get_value())
        if isinstance(v, BitString):
            return [int(b) for b in v]
        if isinstance(v, Atomic):
            return atomic_encode(v)
        if isinstance(v, Choice):
            for name in v._elements:
                x = getattr(v, name, None)
                if x is not None:
                    return {name: to_json(x)}
            return None
        if isinstance(v, Sequence):
            return sequence_to_json(v)
        if isinstance(v, (Array, list, tuple)):
            return [to_json(x) for x in v]
    except Exception:
        pass
    return str(v)


def _setter(obj: Any, attr: str) -> bool:
    ca = getattr(type(obj), attr, None)
    return not isinstance(ca, property) or ca.fset is not None


def writable(obj: Any, attr: str, extra_ro: Set[str]) -> bool:
    """Whether the simulator accepts a write to the property (bacpypes3 rules plus the simulator's own)."""
    name = str(PropertyIdentifier(attr))
    if name in UI_READONLY or name in extra_ro or not _setter(obj, attr):
        return False
    if name == "priority-array" and isinstance(obj, Commandable):
        return False
    return True


def list_properties(obj: Any, extra_ro: Set[str]) -> List[Dict[str, Any]]:
    """All present properties of a local object, ordered by property identifier."""
    out = []
    for attr in obj._elements:
        try:
            v = getattr(obj, attr)
        except Exception:
            continue
        if v is None:
            continue
        pid = PropertyIdentifier(attr)
        dt = obj.get_property_type(attr)
        kind = kind_of(dt)
        w = writable(obj, attr, extra_ro)
        d: Dict[str, Any] = {
            "id": int(pid), "name": str(pid), "value": to_json(v),
            "datatype": getattr(dt, "__name__", str(dt)), "writable": w, "editable": w and kind is not None,
            "kind": kind,
            "commandable": str(pid) == "present-value" and isinstance(obj, Commandable),
        }
        if kind == "enumerated":
            d["choices"] = [str(dt(n)) for n in sorted(set(dt._enum_map.values()))]
        out.append(d)
    out.sort(key=lambda d: d["id"])
    return out


def coerce(datatype: Any, value: Any, priority: Optional[int]) -> Any:
    """JSON value -> instance of the property datatype; null relinquishes a commanded value."""
    if value is None:
        if priority is None:
            raise ValueError("null is only accepted with a priority (relinquish)")
        return Null(())
    kind = kind_of(datatype)
    if kind is None:
        raise ValueError(f"constructed property ({getattr(datatype, '__name__', datatype)}) is read-only here")
    if kind == "boolean":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "on", "active", "yes")
        return datatype(bool(value))
    if kind in ("real", "double"):
        return datatype(float(value))
    if kind in ("unsigned", "integer"):
        f = float(value)
        if f != int(f):
            raise ValueError(f"{value!r} is not an integer")
        return datatype(int(f))
    if kind == "enumerated":
        return datatype(int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value))
    return datatype(str(value))
