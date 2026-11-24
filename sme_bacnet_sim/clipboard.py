"""Copy / paste of devices and objects (web UI clipboard), done on the config level.

Pasted objects get the next free instance of their type and a non-clashing name ("Name (copy)"). Object
references (trend-log ``log_object``, schedule ``targets`` / exception ``calendar``, pulse-converter
``input_object``, loop references, event-enrollment ``monitored_object``, ``notification_class``) are kept
by name; a reference to an object pasted in the same batch follows the renamed copy. An object whose
reference does not resolve in the target device is rejected.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from .config import CALENDAR, NOTIFICATION_CLASS, DeviceConfig, ObjectConfig
from .templates import expand_device

NAME_REFS = ("log_object", "input_object", "controlled_object", "manipulated_object", "setpoint_object",
             "monitored_object")
MAX_DEVICE_ID = 4194302


def _free_name(base: str, used: Set[str]) -> str:
    name, n = base, 1
    while name in used:
        name = f"{base} (copy)" if n == 1 else f"{base} (copy {n})"
        n += 1
    return name


def _remap(oc: ObjectConfig, rename: Dict[str, str], renum: Dict[int, int]) -> ObjectConfig:
    """References to objects of the same paste batch follow the renamed copies."""
    upd: Dict[str, Any] = {f: rename[getattr(oc, f)] for f in NAME_REFS if getattr(oc, f) in rename}

    def nc(ref: Any) -> Any:
        if isinstance(ref, int):
            return renum.get(ref, ref)
        return rename.get(ref, ref)

    if oc.notification_class is not None:
        upd["notification_class"] = nc(oc.notification_class)
    if oc.alarm is not None:
        upd["alarm"] = oc.alarm.model_copy(update={"notification_class": nc(oc.alarm.notification_class)})
    if oc.targets:
        upd["targets"] = [rename.get(x, x) if isinstance(x, str) else x for x in oc.targets]
    if oc.exceptions:
        upd["exceptions"] = [{**e, "calendar": rename.get(e["calendar"], e["calendar"])} if "calendar" in e else e
                             for e in oc.exceptions]
    return oc.model_copy(update=upd)


def _unresolved(oc: ObjectConfig, names: Set[str], ncs: Dict[str, int], cals: Set[str]) -> Optional[str]:
    """Reason why a reference of ``oc`` does not resolve in the target device, None when all resolve."""
    for f in NAME_REFS:
        ref = getattr(oc, f)
        if ref is not None and ref not in names:
            return f"{f} {ref!r} does not exist in the target device"
    for label, ref in (("notification_class", oc.notification_class),
                       ("alarm.notification_class", oc.alarm.notification_class if oc.alarm else None)):
        if ref is not None and not any(n == ref or str(num) == str(ref) for n, num in ncs.items()):
            return f"{label} {ref!r} is not a notification class of the target device"
    for x in oc.targets or []:
        if isinstance(x, str) and x not in names:
            return f"schedule target {x!r} does not exist in the target device"
    for e in oc.exceptions or []:
        if "calendar" in e and e["calendar"] not in cals:
            return f"calendar {e['calendar']!r} does not exist in the target device"
    return None


def paste_objects(dev: DeviceConfig, items: List[Dict[str, Any]]) -> Tuple[List[ObjectConfig], List[Dict[str, str]]]:
    """Objects to append to ``dev`` (renamed / renumbered, references checked) and the rejected ones."""
    existing = expand_device(dev)
    names = {o.name for o in existing} | set(dev.removed or [])  # removed template names stay reserved
    used = {(o.type, o.instance) for o in existing}
    rejected: List[Dict[str, str]] = []
    batch: List[ObjectConfig] = []
    rename: Dict[str, str] = {}
    renum: Dict[int, int] = {}
    for raw in items:
        try:
            oc = ObjectConfig.model_validate(raw)
        except ValidationError as e:
            rejected.append({"name": str(raw.get("name", "?")), "reason": str(e)})
            continue
        name = _free_name(oc.name, names)
        names.add(name)
        inst = 1
        while (oc.type, inst) in used:
            inst += 1
        used.add((oc.type, inst))
        rename[oc.name] = name
        if oc.type == NOTIFICATION_CLASS and oc.instance is not None:
            renum[oc.instance] = inst
        batch.append(oc.model_copy(update={"name": name, "instance": inst}))
    batch = [_remap(oc, rename, renum) for oc in batch]
    base = [o for o in existing]
    while True:  # drop objects with unresolved references until stable (a rejected object may be referenced)
        avail = base + batch
        all_names = {o.name for o in avail}
        ncs = {o.name: o.instance for o in avail if o.type == NOTIFICATION_CLASS}
        cals = {o.name for o in avail if o.type == CALENDAR}
        bad = [(oc, r) for oc in batch if (r := _unresolved(oc, all_names, ncs, cals))]
        if not bad:
            return batch, rejected
        for oc, reason in bad:
            batch.remove(oc)
            orig = next((k for k, v in rename.items() if v == oc.name), oc.name)
            rejected.append({"name": orig, "reason": reason})


def duplicate_device(data: Dict[str, Any], device_id: int) -> Dict[str, Any]:
    """Append a copy of device ``device_id`` to the config dict: next free device id, name "Name (copy)"."""
    src = next((d for d in data["devices"] if d["device_id"] == device_id), None)
    if src is None:
        raise KeyError("device not found")
    used = {d["device_id"] for d in data["devices"]}
    router = (data.get("network") or {}).get("router") or {}
    if router.get("device_id") is not None:
        used.add(router["device_id"])
    n = device_id + 1
    while n in used:
        n += 1
    if n > MAX_DEVICE_ID:
        n = next(i for i in range(MAX_DEVICE_ID + 1) if i not in used)
    new = copy.deepcopy(src)
    new["device_id"] = n
    new["name"] = _free_name(src["name"], {d["name"] for d in data["devices"]})
    data["devices"].append(new)
    return new
