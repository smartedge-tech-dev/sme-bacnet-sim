"""EDE (Engineering Data Exchange, B.I.G.-EU, layout 2.3) import / export.

An EDE export consists of two semicolon-separated CSV files:

* the main file: one row per BACnet object (device rows included, object-type 8)
* the state-text file: one row per state-text reference; for binary objects
  "Text 1" is the inactive text and "Text 2" the active text, for multi-state
  objects the texts are the states 1..N.

Simulator-specific mappings (EDE 2.3 has no dedicated columns for these):

* trend logs: the "vendor-specific-address" column carries the trend-log settings
  as ``key=value`` pairs separated by ``|`` (e.g. ``log_object=Temp|log_interval=60``).
  On import without it the logged object is guessed from the trend-log name
  (``<object>_Log``) or the first value object of the device.
* hi-limit / low-limit map to ``alarm.high_limit`` / ``alarm.low_limit`` of analog
  objects.  On import the alarm refers to the device's first notification class;
  one is created when the device has none.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bacpypes3.basetypes import EngineeringUnits
from bacpypes3.primitivedata import ObjectType

from bacpypes3.basetypes import LifeSafetyState

from .config import (ACCUMULATOR, ANALOG_TYPES, BINARY_TYPES, LIFE_SAFETY_TYPES, LOOP, MULTISTATE_TYPES, OBJECT_TYPES, PULSE_CONVERTER,
                     DeviceConfig, ObjectConfig, SimConfig)
from .templates import expand_device

MAIN_FILE = "sme-bacnet-sim-ede.csv"
STATE_TEXT_FILE = "sme-bacnet-sim-ede-statetexts.csv"

MAIN_COLUMNS = [
    "keyname", "device obj.-instance", "object-name", "object-type", "object-instance", "description",
    "present-value-default", "min-present-value", "max-present-value", "settable", "supports COV",
    "hi-limit", "low-limit", "state-text-reference", "unit-code", "vendor-specific-address",
]
HEADER_KEYS = {"PROJECT_NAME", "VERSION_OF_REFERENCEFILE", "TIMESTAMP_OF_LAST_CHANGE",
               "AUTHOR_OF_LAST_CHANGE", "VERSION_OF_LAYOUT"}
DEVICE_TYPE = 8
VALUE_TYPES = {"analog-value", "binary-value", "multi-state-value"}
# trend-log settings carried in the vendor-specific-address column
TL_KEYS = ("log_object", "log_property", "log_interval", "logging_type", "client_cov_increment", "buffer_size",
           "enabled")
LOGGABLE_TYPES = set(ANALOG_TYPES) | set(BINARY_TYPES) | set(MULTISTATE_TYPES)

# canonical column name -> accepted header spellings (normalized: lower case, no spaces)
_ALIASES = {
    "keyname": ["keyname"],
    "device": ["deviceobj.-instance", "deviceobj.instance", "deviceinstance", "device"],
    "name": ["object-name", "objectname"],
    "type": ["object-type", "objecttype"],
    "instance": ["object-instance", "objectinstance"],
    "description": ["description"],
    "value": ["present-value-default", "presentvaluedefault"],
    "min": ["min-present-value", "minpresentvalue"],
    "max": ["max-present-value", "maxpresentvalue"],
    "settable": ["settable"],
    "cov": ["supportscov"],
    "hi": ["hi-limit"],
    "lo": ["low-limit"],
    "stref": ["state-text-reference", "statetextreference"],
    "unit": ["unit-code", "unitcode"],
    "vendor": ["vendor-specific-address"],
}
_DEFAULT_POS = {k: i for i, k in enumerate(_ALIASES)}  # standard column order


# ---------------------------------------------------------------- export

def _num(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else repr(f)


def _csv(rows: List[List[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    for r in rows:
        w.writerow(["" if c is None else c for c in r])
    return buf.getvalue()


def _header(title: str, project: str) -> List[List[str]]:
    return [
        [title],
        ["PROJECT_NAME", project],
        ["VERSION_OF_REFERENCEFILE", "1"],
        ["TIMESTAMP_OF_LAST_CHANGE", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["AUTHOR_OF_LAST_CHANGE", "SME BACnetSim"],
        ["VERSION_OF_LAYOUT", "2.3"],
    ]


def _binary_value(v: Any) -> Optional[str]:
    if v is None:
        return None
    return "1" if str(v).strip().lower() in ("1", "true", "on", "active") else "0"


def _tl_vendor(o: ObjectConfig) -> str:
    """Trend-log settings for the vendor-specific-address column."""
    parts = []
    for k in TL_KEYS:
        v = getattr(o, k)
        if v is not None:
            parts.append(f"{k}={str(v).lower() if isinstance(v, bool) else _num(v)}")
    return "|".join(parts)


def export_ede(cfg: SimConfig, project: str = "SME BACnetSim") -> Dict[str, str]:
    """Return {file name: CSV text} for the EDE main file and the state-text file."""
    main = _header("#Engineering-Data-Exchange - B.I.G.-EU", project)
    main.append(["#mandatory", "mandatory", "mandatory", "mandatory", "mandatory"] + ["optional"] * 11)
    main.append(["# " + MAIN_COLUMNS[0]] + MAIN_COLUMNS[1:])
    texts: List[List[str]] = []
    for dev in cfg.devices:
        main.append([f"{dev.name}", dev.device_id, dev.name, DEVICE_TYPE, dev.device_id, dev.description,
                     "", "", "", "N", "N", "", "", "", "", ""])
        for o in expand_device(dev):
            ref = ""
            if o.type in BINARY_TYPES and (o.active_text or o.inactive_text):
                texts.append([o.inactive_text or "inactive", o.active_text or "active"])
                ref = str(len(texts))
            elif o.type in MULTISTATE_TYPES:
                texts.append(list(o.states or []))
                ref = str(len(texts))
            if o.type in BINARY_TYPES:
                value = _binary_value(o.value)
            elif o.type in LIFE_SAFETY_TYPES:  # BACnetLifeSafetyState as its number
                value = str(int(LifeSafetyState(o.value or "quiet")))
            else:
                value = _num(o.value)
            unit = hi = lo = ""
            if o.type in ANALOG_TYPES or o.type in (ACCUMULATOR, PULSE_CONVERTER, LOOP):
                unit = str(int(EngineeringUnits(o.units or "no-units")))
                if o.alarm is not None:
                    hi, lo = _num(o.alarm.high_limit), _num(o.alarm.low_limit)
            main.append([
                f"{dev.name}_{o.name}", dev.device_id, o.name, int(ObjectType(o.type)), o.instance,
                o.description, value, _num(o.min), _num(o.max), "Y" if o.is_commandable else "N",
                "N" if o.type in ("trend-log", "schedule", "calendar", "notification-class", "file", "program",
                                 "event-enrollment") else "Y",
                hi, lo, ref, unit, _tl_vendor(o) if o.type == "trend-log" else "",
            ])
    st = _header("#State-Text-File - B.I.G.-EU", project)
    width = max([len(t) for t in texts] + [2])
    st.append(["#State-Text-Reference"] + [f"Text {i + 1}" for i in range(width)])
    st += [[i + 1] + t for i, t in enumerate(texts)]
    return {MAIN_FILE: _csv(main), STATE_TEXT_FILE: _csv(st)}


def export_ede_zip(cfg: SimConfig) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in export_ede(cfg).items():
            z.writestr(name, text.encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------- import

def decode_bytes(data: bytes) -> str:
    """Decode an uploaded EDE file: UTF-8 (with or without BOM), falling back to cp1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _rows(text: str) -> List[List[str]]:
    text = text.lstrip("﻿")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    sample = "\n".join(lines)
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    return [[c.strip() for c in r] for r in csv.reader(lines, delimiter=delim)]


def is_state_text_file(text: str) -> bool:
    for r in _rows(text)[:12]:
        first = (r[0] if r else "").lower().replace(" ", "")
        if "state-text-file" in first or (first.startswith("#") and "text1" in "".join(r).lower().replace(" ", "")):
            return True
    return False


def _norm(s: str) -> str:
    return s.lstrip("#").strip().lower().replace(" ", "")


def _int(s: str) -> Optional[int]:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ".")) if s else None
    except ValueError:
        return None


def _parse_state_texts(text: Optional[str]) -> Dict[int, List[str]]:
    result: Dict[int, List[str]] = {}
    if not text:
        return result
    for r in _rows(text):
        if not r or r[0].startswith("#") or r[0] in HEADER_KEYS:
            continue
        ref = _int(r[0])
        if ref is None:
            continue
        texts = list(r[1:])
        while texts and not texts[-1]:
            texts.pop()
        result[ref] = texts
    return result


def _object_type(s: str) -> Optional[str]:
    code = _int(s)
    try:
        name = str(ObjectType(code if code is not None else s.strip().lower()))
    except Exception:
        return None
    return name


def import_ede(main_text: str, state_text: Optional[str] = None,
               base: Optional[SimConfig] = None) -> Tuple[SimConfig, List[str]]:
    """Parse an EDE main file (+ optional state-text file) into a SimConfig.

    Returns (config, warnings). Network / simulation settings are taken from `base`.
    """
    warnings: List[str] = []
    states = _parse_state_texts(state_text)
    pos = dict(_DEFAULT_POS)
    devices: Dict[int, Dict[str, Any]] = {}

    for line_no, r in enumerate(_rows(main_text), 1):
        if not r or r[0] in HEADER_KEYS:
            continue
        if r[0].startswith("#") or _norm(r[0]) == "keyname":
            names = [_norm(c) for c in r]
            if names and names[0] == "keyname":  # column header row: map columns by name
                pos = {}
                for key, aliases in _ALIASES.items():
                    for i, n in enumerate(names):
                        if n in aliases:
                            pos[key] = i
                            break
            continue

        def col(key: str) -> str:
            i = pos.get(key)
            return r[i] if i is not None and i < len(r) else ""

        dev_id, inst = _int(col("device")), _int(col("instance"))
        otype = _object_type(col("type"))
        if dev_id is None or inst is None or otype is None:
            warnings.append(f"line {line_no}: skipped (unreadable device / object type / instance)")
            continue
        dev = devices.setdefault(dev_id, {"name": None, "description": "", "objects": [], "names": set()})
        if otype == "device":
            dev["name"] = col("name") or None
            dev["description"] = col("description")
            continue
        if otype == LOOP:
            # EDE carries no controlled / manipulated variable references or tuning constants
            warnings.append(f"device {dev_id}: loop {inst} ({col('name')}) skipped "
                            "(EDE does not carry its references / PID constants; add it in YAML)")
            continue
        if otype == "event-enrollment":
            # EDE carries no monitored object / event type / event parameters
            warnings.append(f"device {dev_id}: event-enrollment {inst} ({col('name')}) skipped "
                            "(EDE does not carry its monitored object / event parameters; add it in YAML)")
            continue
        if otype in ("schedule", "calendar"):
            # EDE carries no weekly / exception schedule or date list, so these cannot be rebuilt
            warnings.append(f"device {dev_id}: {otype} {inst} ({col('name')}) skipped "
                            "(EDE does not carry its schedule / dates; add it in YAML)")
            continue
        if otype in ("file", "program"):
            o = {"type": otype, "instance": inst, "name": col("name") or f"{otype}-{inst}",
                 "description": col("description")}
            if otype == "file":
                # EDE carries no file content / type / access method: imported as an empty stream file
                o["content"] = ""
                warnings.append(f"device {dev_id}: file {inst} ({o['name']}): content, file type and access "
                                "method are not carried by EDE; imported as an empty stream file")
            dev["names"].add(o["name"])
            dev["objects"].append(o)
            continue
        if otype not in OBJECT_TYPES and otype not in ("trend-log", "notification-class") \
                and otype not in LIFE_SAFETY_TYPES:
            warnings.append(f"device {dev_id}: {otype} {inst} ({col('name')}) skipped (unsupported object type)")
            continue

        name = col("name") or f"{otype}-{inst}"
        if name in dev["names"]:
            new = f"{name}_{otype}{inst}"
            warnings.append(f"device {dev_id}: duplicate object name {name!r} renamed to {new!r}")
            name = new
        dev["names"].add(name)
        o: Dict[str, Any] = {"type": otype, "instance": inst, "name": name}
        if col("description"):
            o["description"] = col("description")
        if otype == "notification-class":
            # EDE has no columns for priorities / ack-required / recipients: defaults, no recipients
            warnings.append(f"device {dev_id}: notification-class {inst} ({name}) imported without recipients "
                            "(EDE does not carry priorities / recipients; add them in YAML)")
            dev["objects"].append(o)
            continue
        if otype == "trend-log":
            o["vendor"] = col("vendor")  # resolved once all objects of the device are known
            dev["objects"].append(o)
            continue
        if otype in LIFE_SAFETY_TYPES:  # state number -> name; mode / zone members are not carried by EDE
            code = _int(col("value"))
            if code is not None and not str(LifeSafetyState(code)).isdigit():
                o["value"] = str(LifeSafetyState(code))
            dev["objects"].append(o)
            continue
        raw_value = col("value")
        ref = _int(col("stref"))
        texts = states.get(ref) if ref is not None else None
        if ref is not None and texts is None and state_text:
            warnings.append(f"device {dev_id}: {name}: state-text reference {ref} not found")

        if otype in (ACCUMULATOR, PULSE_CONVERTER):
            if otype == ACCUMULATOR:
                o["value"] = _int(raw_value)
                o["max"] = _int(col("max"))
            else:
                o["value"] = _float(raw_value)
            code = _int(col("unit"))
            if code is not None and not str(EngineeringUnits(code)).isdigit():
                o["units"] = str(EngineeringUnits(code))
        elif otype in ANALOG_TYPES:
            o["value"] = _float(raw_value)
            o["min"], o["max"] = _float(col("min")), _float(col("max"))
            hi, lo = _float(col("hi")), _float(col("lo"))
            if hi is not None or lo is not None:
                o["alarm"] = {"high_limit": hi, "low_limit": lo}  # notification class resolved per device
            code = _int(col("unit"))
            if code is not None:
                unit = str(EngineeringUnits(code))
                if unit.isdigit():
                    warnings.append(f"device {dev_id}: {name}: unknown unit-code {code} ignored")
                else:
                    o["units"] = unit
        elif otype in BINARY_TYPES:
            if raw_value:
                o["value"] = int(_binary_value(raw_value))
            if texts:
                o["inactive_text"] = texts[0] or None
                if len(texts) > 1:
                    o["active_text"] = texts[1] or None
        else:  # multi-state
            o["value"] = _int(raw_value)
            if texts:
                o["states"] = texts
            else:
                n = max(_int(col("max")) or 0, o["value"] or 0, 2)
                o["states"] = [f"State {i}" for i in range(1, n + 1)]
                warnings.append(f"device {dev_id}: {name}: no state texts, generated {n} placeholder states")
        if otype in VALUE_TYPES and col("settable").upper().startswith("Y"):
            o["commandable"] = True
        dev["objects"].append(o)

    result = []
    for dev_id, d in devices.items():
        objects = _resolve_device(dev_id, d["objects"], warnings)
        result.append(DeviceConfig(device_id=dev_id, name=d["name"] or f"Device-{dev_id}",
                                   description=d["description"], objects=objects))
    base = base or SimConfig()
    cfg = SimConfig(network=base.network.model_copy(deep=True), simulation=base.simulation.model_copy(deep=True),
                    devices=result)
    return cfg, warnings


def _resolve_device(dev_id: int, objs: List[Dict[str, Any]], warnings: List[str]) -> List[ObjectConfig]:
    """Fill in trend-log targets and alarm notification classes, then validate the device's objects."""
    names = {o["name"] for o in objs}
    values = [o for o in objs if o["type"] in LOGGABLE_TYPES]
    ncs = [o for o in objs if o["type"] == "notification-class"]
    if ncs:
        nc_name = ncs[0]["name"]
    elif any("alarm" in o for o in objs):
        nc_inst = 1
        nc_name = next(n for n in (f"NC-{nc_inst}", f"NC-{nc_inst}-ede") if n not in names)
        objs.append({"type": "notification-class", "instance": nc_inst, "name": nc_name})
        warnings.append(f"device {dev_id}: hi-limit / low-limit given but no notification class; "
                        f"created {nc_name} (no recipients)")
    result = []
    for o in objs:
        if "alarm" in o:
            o["alarm"] = {"notification_class": nc_name, **{k: v for k, v in o["alarm"].items() if v is not None}}
        if o["type"] == "trend-log":
            kv = {}
            for part in o.pop("vendor").split("|"):
                k, sep, v = part.partition("=")
                if sep and k.strip() in TL_KEYS:
                    kv[k.strip()] = v.strip()
            if kv.get("enabled") is not None:
                kv["enabled"] = kv["enabled"].lower() in ("true", "1", "y", "yes")
            if kv.get("log_object") not in names:
                base = o["name"]
                for suffix in ("_Log", "_log", "Log", "_TL"):
                    if base.endswith(suffix):
                        base = base[:-len(suffix)]
                        break
                guess = base if any(v["name"] == base for v in values) else (values[0]["name"] if values else None)
                if guess is None:
                    warnings.append(f"device {dev_id}: trend-log {o['instance']} ({o['name']}) skipped "
                                    "(no logged object in the EDE row and no value object to log)")
                    continue
                if "log_object" in kv:
                    warnings.append(f"device {dev_id}: trend-log {o['name']}: log_object {kv['log_object']!r} "
                                    f"not found, logging {guess!r}")
                else:
                    warnings.append(f"device {dev_id}: trend-log {o['name']}: EDE does not carry the logged "
                                    f"object, logging {guess!r}")
                kv["log_object"] = guess
            o.update(kv)
        result.append(ObjectConfig.model_validate({k: v for k, v in o.items() if v is not None}))
    return result


def import_ede_files(files: Dict[str, bytes], base: Optional[SimConfig] = None) -> Tuple[SimConfig, List[str]]:
    """Import uploaded EDE files (CSV files and / or a zip of them); the state-text file is detected by its header."""
    texts: Dict[str, str] = {}
    for fname, data in files.items():
        if fname.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".csv"):
                        texts[n] = decode_bytes(z.read(n))
        else:
            texts[fname] = decode_bytes(data)
    main = [t for t in texts.values() if not is_state_text_file(t)]
    st = [t for t in texts.values() if is_state_text_file(t)]
    if len(main) != 1:
        raise ValueError(f"expected exactly one EDE main file, got {len(main)}")
    if len(st) > 1:
        raise ValueError(f"expected at most one EDE state-text file, got {len(st)}")
    return import_ede(main[0], st[0] if st else None, base)
