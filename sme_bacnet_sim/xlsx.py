"""Excel (.xlsx) point-list import / export.

Workbook layout (one header row of English column names per sheet; the row below it starts with ``#`` and
carries a Japanese / Chinese description; any row whose first cell starts with ``#`` is ignored on import):

* ``Devices``: one row per device (``device_id``, ``name``, ``template``, ``params`` ...)
* ``Points``: one row per object of a device (``device_id``, ``type``, ``instance``, ``name``, ``units`` ...)
* ``StateTexts``: multi-state texts, referenced from ``Points.state_texts`` by ``ref``
* ``Network``: optional ``key`` / ``value`` rows for the network and simulation settings
  (``network.ip``, ``simulation.time_scale`` ...); without the sheet the running settings are kept

Settings without a dedicated column (schedules, trend-log settings, notification-class recipients, loop
constants ...) are carried in the ``extra`` column as a YAML flow mapping, so export -> import gives back an
equivalent configuration.  Devices with a ``template`` keep it: their Points rows are the template overrides /
additions, exactly as in YAML.

The workbook is an :class:`sme_sim_common.xlsx.XlsxSchema` (:data:`SCHEMA`); the BACnet-specific column
converters (object type, engineering units, alarm values, notification-class reference) are callable kinds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import yaml
from bacpypes3.basetypes import EngineeringUnits
from pydantic import ValidationError
from sme_sim_common.xlsx import Sheet, SheetRow, XlsxSchema, convert, flow

from .config import (BINARY_TYPES, MULTISTATE_TYPES, DeviceConfig, NetworkConfig, ObjectConfig, SimConfig,
                     SimulationConfig)
from .ede import _object_type

TEMPLATE_FILE = "sme-bacnet-sim-points-template.xlsx"
EXPORT_FILE = "sme-bacnet-sim-points.xlsx"
STATE_TEXT_COLUMNS = 8  # text_N columns in the blank template (more are added on export when needed)

# ---------------------------------------------------------------- BACnet column converters (callable kinds)

def _strip(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


def _type(v: Any) -> str:
    v = _strip(v)
    t = _object_type(str(v))
    if t is None:
        raise ValueError(f"unknown object type {v!r}")
    return t


def _units(v: Any) -> str:
    v = _strip(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        name = str(EngineeringUnits(int(v)))
        if name.isdigit():
            raise ValueError(f"unknown unit code {v!r}")
        return name
    return str(v)


def _alarm_values(v: Any) -> Any:
    """``active`` / ``2,3`` (comma list, digits as int) or a YAML list such as ``[a, "b,c"]``."""
    s = str(_strip(v))
    if s.startswith("["):
        return yaml.safe_load(s)
    return [int(x) if x.strip().isdigit() else x.strip() for x in s.split(",") if x.strip()]


def _ncref(v: Any) -> Any:
    """Notification class: instance number or object name."""
    return convert("port", v)




# column -> (kind, description "ja / zh")
DEVICE_COLUMNS: Dict[str, Tuple[Any, str]] = {
    "device_id": ("int", "デバイスインスタンス番号（必須）/ 设备实例号（必填）"),
    "name": ("str", "デバイス名（必須）/ 设备名（必填）"),
    "description": ("str", "説明 / 描述"),
    "template": ("str", "テンプレート名（空欄＝なし）/ 模板名（空＝不用模板）"),
    "params": ("yaml", "テンプレートパラメータ YAML 例 {zones: 4} / 模板参数 YAML，例 {zones: 4}"),
    "vendor_id": ("int", "ベンダー ID（既定 999）/ 厂商 ID（默认 999）"),
    "vendor_name": ("str", "ベンダー名 / 厂商名"),
    "model_name": ("str", "モデル名 / 型号"),
    "location": ("str", "設置場所 / 位置"),
    "dcc_password": ("str", "DeviceCommunicationControl パスワード / 密码"),
    "reinit_password": ("str", "ReinitializeDevice パスワード / 密码"),
    "extra": ("yaml", "列のない設定（YAML マッピング）/ 无对应列的设置（YAML 映射）"),
}
POINT_COLUMNS: Dict[str, Tuple[Any, str]] = {
    "device_id": ("int", "所属デバイス（必須）/ 所属设备（必填）"),
    "type": (_type, "オブジェクトタイプ 例 analog-input（必須）/ 对象类型，例 analog-input（必填）"),
    "instance": ("int", "インスタンス番号（空欄＝自動）/ 实例号（空＝自动）"),
    "name": ("str", "オブジェクト名（必須・デバイス内で一意）/ 对象名（必填，设备内唯一）"),
    "description": ("str", "説明 / 描述"),
    "units": (_units, "単位 例 degrees-celsius / 单位，例 degrees-celsius"),
    "value": ("value", "初期値 / 初始值"),
    "commandable": ("bool", "コマンダブル（TRUE / FALSE）/ 可命令（TRUE / FALSE）"),
    "min": ("float", "最小値 / 最小值"),
    "max": ("float", "最大値 / 最大值"),
    "cov_increment": ("float", "COV 増分 / COV 增量"),
    "state_texts": ("int", "StateTexts シートの ref / StateTexts 表的 ref"),
    "inactive_text": ("str", "バイナリ inactive テキスト / 二值 inactive 文本"),
    "active_text": ("str", "バイナリ active テキスト / 二值 active 文本"),
    "behavior": ("yaml", "挙動 YAML 例 {type: sine, min: 20, max: 26} / 行为 YAML"),
    "alarm_class": (_ncref, "アラームの通知クラス（名前または番号）/ 报警通知类（名称或编号）"),
    "alarm_high_limit": ("float", "上限アラーム / 上限报警"),
    "alarm_low_limit": ("float", "下限アラーム / 下限报警"),
    "alarm_deadband": ("float", "デッドバンド / 死区"),
    "alarm_values": (_alarm_values, "アラーム値（バイナリ: active、多状態: 2,3）/ 报警值（二值: active，多态: 2,3）"),
    "alarm_time_delay": ("int", "時間遅延（秒）/ 延时（秒）"),
    "extra": ("yaml", "列のない設定（YAML マッピング）/ 无对应列的设置（YAML 映射）"),
}
STATE_COLUMNS_DESC = {"ref": "参照番号（Points.state_texts）/ 引用号（Points.state_texts）",
                      "text_1": "状態 1 のテキスト / 状态 1 的文本"}
NETWORK_COLUMNS_DESC = {"key": "設定キー 例 network.ip / 设置键，例 network.ip", "value": "値 / 值"}

# Points columns that come straight from an ObjectConfig field
_DIRECT = ("type", "instance", "name", "description", "units", "commandable", "min", "max", "cov_increment",
           "inactive_text", "active_text", "behavior")
_ALARM_COLS = {"alarm_class": "notification_class", "alarm_high_limit": "high_limit",
               "alarm_low_limit": "low_limit", "alarm_deadband": "deadband", "alarm_time_delay": "time_delay"}


class XlsxImportError(ValueError):
    """Import errors; each message names the sheet, row and column."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        shown = errors[:20] + ([f"... {len(errors) - 20} more"] if len(errors) > 20 else [])
        super().__init__(f"{len(errors)} error(s) in the Excel file: " + "; ".join(shown))


# ---------------------------------------------------------------- sheets

def _sheet(title: str, columns: Dict[str, Tuple[Any, str]], **kw: Any) -> Sheet:
    return Sheet(title, [(c, d) for c, (_, d) in columns.items()], kinds={c: k for c, (k, _) in columns.items()},
                 **kw)


def _state_columns(first: int, last: int) -> List[Tuple[str, str]]:
    return [(f"text_{i}", STATE_COLUMNS_DESC.get(f"text_{i}", f"状態 {i} / 状态 {i}")) for i in range(first, last + 1)]


SHEETS = [
    _sheet("Devices", DEVICE_COLUMNS, required=("device_id", "name")),
    _sheet("Points", POINT_COLUMNS, required=("device_id", "type", "name")),
    Sheet("StateTexts", [("ref", STATE_COLUMNS_DESC["ref"]), *_state_columns(1, STATE_TEXT_COLUMNS)],
          kinds={"ref": "int"}, required=("ref",), optional=True, open_columns=True),
    Sheet("Network", list(NETWORK_COLUMNS_DESC.items()), kinds={"value": "value"}, optional=True,
          required_headers=("key", "value")),
]


# ---------------------------------------------------------------- export

def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _flatten(prefix: str, d: Dict[str, Any], out: List[Tuple[str, Any]]) -> None:
    for k, v in d.items():
        if isinstance(v, dict):
            _flatten(f"{prefix}{k}.", v, out)
        else:
            out.append((prefix + k, v if _scalar(v) else flow(v)))


def _export_rows(cfg: SimConfig):
    """``(rows, extra StateTexts columns, warnings)`` for :meth:`XlsxSchema.export_xlsx`. A row dict carries the
    column values plus the leftover model fields, which :meth:`XlsxSchema.row` puts into ``extra``."""
    warnings: List[str] = []
    states: Dict[Tuple[str, ...], int] = {}
    device_rows, point_rows = [], []
    for dev in cfg.devices:
        d = dev.model_dump(exclude_unset=True, exclude_none=True)
        d.pop("objects", None)
        device_rows.append({"device_id": dev.device_id, "name": dev.name, **d})
        for o in dev.objects:
            od = o.model_dump(exclude_unset=True, exclude_none=True)
            row: Dict[str, Any] = {"device_id": dev.device_id}
            for col in _DIRECT:
                if col in od:
                    row[col] = od.pop(col)
            if "value" in od and _scalar(od["value"]):
                row["value"] = od.pop("value")
            if od.get("states") is not None and o.type in MULTISTATE_TYPES:
                key = tuple(od.pop("states"))
                row["state_texts"] = states.setdefault(key, len(states) + 1)
            alarm = od.pop("alarm", None)
            if alarm:
                for col, fld in _ALARM_COLS.items():
                    if fld in alarm:
                        row[col] = alarm.pop(fld)
                av = alarm.pop("alarm_values", None) if o.type in MULTISTATE_TYPES else alarm.pop("alarm_value", None)
                if isinstance(av, list):
                    av = ",".join(map(str, av)) if not any("," in str(x) for x in av) else flow(av)
                if av is not None:
                    row["alarm_values"] = av
                if alarm:
                    od["alarm"] = alarm
            if o.path is not None:
                warnings.append(f"device {dev.device_id}: {o.type} {o.name}: file content is loaded from path "
                                f"{o.path!r}, which is exported as a reference only (relative to the importing config)")
            point_rows.append({**row, **od})
    width = max([STATE_TEXT_COLUMNS] + [len(k) for k in states])
    state_rows = [{"ref": ref, **{f"text_{i}": t for i, t in enumerate(texts, 1)}} for texts, ref in states.items()]
    net: List[Tuple[str, Any]] = []
    _flatten("network.", cfg.network.model_dump(exclude_none=True), net)
    _flatten("simulation.", cfg.simulation.model_dump(exclude_none=True), net)
    rows = {"Devices": device_rows, "Points": point_rows, "StateTexts": state_rows,
            "Network": [{"key": k, "value": v} for k, v in net]}
    return rows, {"StateTexts": _state_columns(STATE_TEXT_COLUMNS + 1, width)}, warnings


# ---------------------------------------------------------------- import

def _pydantic_errors(e: ValidationError, prefix: str, colmap: Dict[str, str]) -> List[str]:
    out = []
    for err in e.errors():
        loc = [str(x) for x in err["loc"]]
        col = (colmap.get(".".join(loc[:2])) or colmap.get(loc[0], "extra")) if loc else None
        out.append(f"{prefix}{', column ' + repr(col) if col else ''}: {'.'.join(loc)}: {err['msg']}")
    return out


def _build(tables: Dict[str, List[SheetRow]], base: Optional[SimConfig], errors: List[str],
           warnings: List[str]) -> Optional[SimConfig]:
    # state texts
    states: Dict[int, List[str]] = {}
    for r in tables["StateTexts"]:
        if "ref" not in r.values:  # conversion / required error already reported
            continue
        ref = r.values["ref"]
        texts = {int(k[5:]): v for k, v in r.values.items() if k != "ref" and k[5:].isdigit()}
        n = max(texts, default=0)
        if not n:
            errors.append(f"StateTexts row {r.row_no}, column 'text_1': no state texts")
        elif ref in states:
            errors.append(f"StateTexts row {r.row_no}, column 'ref': duplicate ref {ref}")
        else:
            states[ref] = [texts.get(i, "") for i in range(1, n + 1)]

    # devices
    devices: Dict[int, Dict[str, Any]] = {}
    dev_rows: Dict[int, int] = {}
    for r in tables["Devices"]:
        d = dict(r.values)
        if "device_id" not in d or "name" not in d:
            continue
        if d["device_id"] in devices:
            errors.append(f"Devices row {r.row_no}, column 'device_id': duplicate device_id {d['device_id']}")
            continue
        extra = d.pop("extra", {})
        devices[d["device_id"]] = {**extra, **d, "objects": []}
        dev_rows[d["device_id"]] = r.row_no

    # points
    names: Dict[Tuple[int, str], int] = {}
    point_rows: Dict[Tuple[int, str, int], int] = {}
    colmap = {c: c for c in _DIRECT}
    colmap.update({"value": "value", "states": "state_texts", "alarm.alarm_value": "alarm_values",
                   "alarm.alarm_values": "alarm_values"})
    colmap.update({f"alarm.{f}": c for c, f in _ALARM_COLS.items()})
    for r in tables["Points"]:
        n_errors = len(errors)
        p = dict(r.values)
        prefix = f"Points row {r.row_no}"
        if not all(c in p for c in ("device_id", "type", "name")):
            continue
        dev = devices.get(p["device_id"])
        if dev is None:
            errors.append(f"{prefix}, column 'device_id': device {p['device_id']} is not in the Devices sheet")
            continue
        key = (p["device_id"], p["name"])
        if key in names:
            errors.append(f"{prefix}, column 'name': duplicate object name {p['name']!r} in device "
                          f"{p['device_id']} (also row {names[key]})")
            continue
        names[key] = r.row_no
        o: Dict[str, Any] = dict(p.pop("extra", {}))
        for col in _DIRECT:
            if col in p:
                o[col] = p[col]
        if "value" in p:
            o["value"] = p["value"]
        if "state_texts" in p:
            texts = states.get(p["state_texts"])
            if texts is None:
                errors.append(f"{prefix}, column 'state_texts': ref {p['state_texts']} not in the StateTexts sheet")
            elif o["type"] in MULTISTATE_TYPES:
                o["states"] = texts
            elif o["type"] in BINARY_TYPES:
                o.setdefault("inactive_text", texts[0])
                if len(texts) > 1:
                    o.setdefault("active_text", texts[1])
            else:
                warnings.append(f"{prefix}: state_texts ignored for {o['type']}")
        alarm = {k: p[c] for c, k in _ALARM_COLS.items() if c in p}
        if "alarm_values" in p:
            av = p["alarm_values"]
            if o["type"] in MULTISTATE_TYPES:
                alarm["alarm_values"] = av if isinstance(av, list) else [av]
            else:
                alarm["alarm_value"] = av[0] if isinstance(av, list) and len(av) == 1 else av
        if alarm:
            o["alarm"] = {**(o.get("alarm") or {}), **alarm}
        if not r.ok or len(errors) > n_errors:  # the row already has errors: no follow-up validation errors
            continue
        try:
            obj = ObjectConfig.model_validate(o)
        except ValidationError as e:
            errors.extend(_pydantic_errors(e, prefix, colmap))
            continue
        if obj.instance is not None:
            ik = (p["device_id"], obj.type, obj.instance)
            if ik in point_rows:
                errors.append(f"{prefix}, column 'instance': duplicate {obj.type} {obj.instance} in device "
                              f"{p['device_id']} (also row {point_rows[ik]})")
                continue
            point_rows[ik] = r.row_no
        dev["objects"].append(obj)

    result = []
    for dev_id, d in devices.items():
        try:
            result.append(DeviceConfig.model_validate(d))
        except ValidationError as e:
            errors.extend(_pydantic_errors(e, f"Devices row {dev_rows[dev_id]}", {c: c for c in DEVICE_COLUMNS}))

    # network / simulation settings. As in 0.4.0, any data row rebuilds both sections from the sheet (keys
    # without a value fall back to the defaults); without data rows the running settings are kept.
    base = base or SimConfig()
    network, simulation = base.network.model_copy(deep=True), base.simulation.model_copy(deep=True)
    rows = tables["Network"]
    tree: Dict[str, Dict[str, Any]] = {"network": {}, "simulation": {}}
    key_rows: Dict[str, int] = {}
    for r in rows:
        k = str(r.raw.get("key", "")).strip()
        top, _, rest = k.partition(".")
        if top not in tree or not rest:
            errors.append(f"Network row {r.row_no}, column 'key': unknown key {k!r} "
                          "(network.<name> or simulation.<name>)")
            continue
        if "value" not in r.raw:  # the key is checked first, then a row without a value is skipped
            continue
        node = tree[top]
        parts = rest.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = r.raw["value"]
        key_rows[k] = r.row_no
    if rows:
        for top, model in (("network", NetworkConfig), ("simulation", SimulationConfig)):
            try:
                validated = model.model_validate(tree[top])
            except ValidationError as e:
                for err in e.errors():
                    k = ".".join([top] + [str(x) for x in err["loc"]])
                    row = next((rn for kk, rn in key_rows.items() if k.startswith(kk) or kk.startswith(k)), None)
                    where = f"Network row {row}, column 'value'" if row else "Network"
                    errors.append(f"{where}: {k}: {err['msg']}")
                continue
            if top == "network":
                network = validated
            else:
                simulation = validated

    if errors:
        return None
    try:
        return SimConfig(network=network, simulation=simulation, devices=result)
    except ValidationError as e:
        errors.extend(f"Devices / Network: {err['msg']}" for err in e.errors())
        return None


#: The BACnet workbook behind sme-sim-common's xlsx routes (``GET /api/config/xlsx``, ``.../xlsx-template``,
#: ``POST /api/config/import``).
SCHEMA = XlsxSchema(SHEETS, export_rows=_export_rows, build=_build, template_file=TEMPLATE_FILE,
                    export_file=EXPORT_FILE)


def blank_template() -> bytes:
    """An empty workbook with all sheets, column names and description rows."""
    return SCHEMA.blank_template()


def export_xlsx(cfg: SimConfig) -> Tuple[bytes, List[str]]:
    """Export a SimConfig as a point-list workbook. Returns (xlsx bytes, warnings)."""
    return SCHEMA.export_xlsx(cfg)


def import_xlsx(data: bytes, base: Optional[SimConfig] = None) -> Tuple[SimConfig, List[str]]:
    """Parse a point-list workbook into a SimConfig. Returns (config, warnings); raises XlsxImportError."""
    cfg, messages = SCHEMA.import_xlsx(data, base)
    if cfg is None:
        raise XlsxImportError(messages)
    return cfg, messages
