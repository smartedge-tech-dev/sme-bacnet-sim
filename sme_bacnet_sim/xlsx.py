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
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

import yaml
from bacpypes3.basetypes import EngineeringUnits
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import ValidationError

from .config import (BINARY_TYPES, MULTISTATE_TYPES, DeviceConfig, NetworkConfig, ObjectConfig, SimConfig,
                     SimulationConfig)
from .ede import _object_type

TEMPLATE_FILE = "sme-bacnet-sim-points-template.xlsx"
EXPORT_FILE = "sme-bacnet-sim-points.xlsx"
CELL_LIMIT = 32767  # Excel's maximum characters per cell
STATE_TEXT_COLUMNS = 8  # text_N columns in the blank template (more are added on export when needed)

# column -> (kind, description "ja / zh")
DEVICE_COLUMNS: Dict[str, Tuple[str, str]] = {
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
POINT_COLUMNS: Dict[str, Tuple[str, str]] = {
    "device_id": ("int", "所属デバイス（必須）/ 所属设备（必填）"),
    "type": ("type", "オブジェクトタイプ 例 analog-input（必須）/ 对象类型，例 analog-input（必填）"),
    "instance": ("int", "インスタンス番号（空欄＝自動）/ 实例号（空＝自动）"),
    "name": ("str", "オブジェクト名（必須・デバイス内で一意）/ 对象名（必填，设备内唯一）"),
    "description": ("str", "説明 / 描述"),
    "units": ("units", "単位 例 degrees-celsius / 单位，例 degrees-celsius"),
    "value": ("value", "初期値 / 初始值"),
    "commandable": ("bool", "コマンダブル（TRUE / FALSE）/ 可命令（TRUE / FALSE）"),
    "min": ("float", "最小値 / 最小值"),
    "max": ("float", "最大値 / 最大值"),
    "cov_increment": ("float", "COV 増分 / COV 增量"),
    "state_texts": ("int", "StateTexts シートの ref / StateTexts 表的 ref"),
    "inactive_text": ("str", "バイナリ inactive テキスト / 二值 inactive 文本"),
    "active_text": ("str", "バイナリ active テキスト / 二值 active 文本"),
    "behavior": ("yaml", "挙動 YAML 例 {type: sine, min: 20, max: 26} / 行为 YAML"),
    "alarm_class": ("ncref", "アラームの通知クラス（名前または番号）/ 报警通知类（名称或编号）"),
    "alarm_high_limit": ("float", "上限アラーム / 上限报警"),
    "alarm_low_limit": ("float", "下限アラーム / 下限报警"),
    "alarm_deadband": ("float", "デッドバンド / 死区"),
    "alarm_values": ("list", "アラーム値（バイナリ: active、多状態: 2,3）/ 报警值（二值: active，多态: 2,3）"),
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


# ---------------------------------------------------------------- helpers

def _flow(v: Any) -> str:
    return yaml.safe_dump(v, default_flow_style=True, sort_keys=False, allow_unicode=True, width=10 ** 9).strip()


def _scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _sheet(wb: Workbook, title: str, columns: Dict[str, str], first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(list(columns))
    ws.append(["# " + d if i == 0 else d for i, d in enumerate(columns.values())])
    bold, grey = Font(bold=True), Font(italic=True, color="666666")
    fill = PatternFill("solid", fgColor="DDEBF7")
    for i, name in enumerate(columns, 1):
        ws.cell(1, i).font, ws.cell(1, i).fill = bold, fill
        ws.cell(2, i).font = grey
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(40, len(name) + 6))
    ws.freeze_panes = "A3"
    return ws


def _workbook(state_cols: int = STATE_TEXT_COLUMNS) -> Workbook:
    wb = Workbook()
    _sheet(wb, "Devices", {k: d for k, (_, d) in DEVICE_COLUMNS.items()}, first=True)
    _sheet(wb, "Points", {k: d for k, (_, d) in POINT_COLUMNS.items()})
    st = dict(STATE_COLUMNS_DESC)
    for i in range(2, state_cols + 1):
        st[f"text_{i}"] = f"状態 {i} / 状态 {i}"
    _sheet(wb, "StateTexts", st)
    _sheet(wb, "Network", NETWORK_COLUMNS_DESC)
    return wb


def _save(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def blank_template() -> bytes:
    """An empty workbook with all sheets, column names and description rows."""
    return _save(_workbook())


# ---------------------------------------------------------------- export

def _flatten(prefix: str, d: Dict[str, Any], out: List[Tuple[str, Any]]) -> None:
    for k, v in d.items():
        if isinstance(v, dict):
            _flatten(f"{prefix}{k}.", v, out)
        else:
            out.append((prefix + k, v if _scalar(v) else _flow(v)))


def export_xlsx(cfg: SimConfig) -> Tuple[bytes, List[str]]:
    """Export a SimConfig as a point-list workbook. Returns (xlsx bytes, warnings)."""
    warnings: List[str] = []
    states: Dict[Tuple[str, ...], int] = {}
    device_rows, point_rows = [], []

    def cell(where: str, col: str, v: Any) -> Any:
        if isinstance(v, str) and len(v) > CELL_LIMIT:
            warnings.append(f"{where}: {col} longer than {CELL_LIMIT} characters (Excel cell limit), left out")
            return None
        return v

    for dev in cfg.devices:
        d = dev.model_dump(exclude_unset=True, exclude_none=True)
        d.pop("objects", None)
        row = {"device_id": dev.device_id, "name": dev.name}
        for col in DEVICE_COLUMNS:
            if col in d and col not in ("extra",):
                v = d.pop(col)
                row[col] = _flow(v) if col == "params" else v
        if not row.get("params"):
            row.pop("params", None)
        if d:
            row["extra"] = _flow(d)
        where = f"device {dev.device_id}"
        device_rows.append({k: cell(where, k, v) for k, v in row.items()})
        for o in dev.objects:
            od = o.model_dump(exclude_unset=True, exclude_none=True)
            where = f"device {dev.device_id}: {o.type} {o.name}"
            row = {"device_id": dev.device_id}
            for col in _DIRECT:
                if col in od:
                    v = od.pop(col)
                    row[col] = _flow(v) if col == "behavior" else v
            if "value" in od and _scalar(od["value"]):
                row["value"] = od.pop("value")
            if od.get("states") is not None and o.type in MULTISTATE_TYPES:
                key = tuple(od.pop("states"))
                row["state_texts"] = states.setdefault(key, len(states) + 1)
            alarm = od.pop("alarm", None)
            if alarm:
                for col, field in _ALARM_COLS.items():
                    if field in alarm:
                        row[col] = alarm.pop(field)
                av = alarm.pop("alarm_values", None) if o.type in MULTISTATE_TYPES else alarm.pop("alarm_value", None)
                if isinstance(av, list):
                    av = ",".join(map(str, av)) if not any("," in str(x) for x in av) else _flow(av)
                if av is not None:
                    row["alarm_values"] = av
                if alarm:
                    od["alarm"] = alarm
            if o.path is not None:
                warnings.append(f"{where}: file content is loaded from path {o.path!r}, which is exported "
                                "as a reference only (relative to the importing config)")
            if od:
                row["extra"] = _flow(od)
            point_rows.append({k: cell(where, k, v) for k, v in row.items()})

    width = max([STATE_TEXT_COLUMNS] + [len(k) for k in states])
    wb = _workbook(width)
    for title, cols, rows in (("Devices", DEVICE_COLUMNS, device_rows), ("Points", POINT_COLUMNS, point_rows)):
        ws = wb[title]
        for r in rows:
            ws.append([r.get(c) for c in cols])
    ws = wb["StateTexts"]
    for texts, ref in states.items():
        ws.append([ref, *texts])
    ws = wb["Network"]
    net: List[Tuple[str, Any]] = []
    _flatten("network.", cfg.network.model_dump(exclude_none=True), net)
    _flatten("simulation.", cfg.simulation.model_dump(exclude_none=True), net)
    for k, v in net:
        ws.append([k, v])
    return _save(wb), warnings


# ---------------------------------------------------------------- import

def _norm(s: Any) -> str:
    return str(s).strip().lower().replace(" ", "_").replace("-", "_") if s is not None else ""


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _convert(kind: str, v: Any) -> Any:
    """Cell value -> config value for a column kind; raises ValueError with a short reason."""
    if isinstance(v, str):
        v = v.strip()
    if kind == "int":
        if isinstance(v, bool):
            raise ValueError(f"not an integer: {v!r}")
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit()):
            return int(v)
        raise ValueError(f"not an integer: {v!r}")
    if kind == "float":
        try:
            if isinstance(v, bool):
                raise ValueError
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"not a number: {v!r}") from None
    if kind == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes", "y", "1", "on"):
            return True
        if s in ("false", "no", "n", "0", "off"):
            return False
        raise ValueError(f"not TRUE / FALSE: {v!r}")
    if kind == "yaml":
        try:
            data = yaml.safe_load(str(v))
        except yaml.YAMLError as e:
            raise ValueError(f"invalid YAML: {str(e).splitlines()[0]}") from None
        if not isinstance(data, dict):
            raise ValueError("expected a YAML mapping such as {key: value}")
        return data
    if kind == "type":
        t = _object_type(str(v))
        if t is None:
            raise ValueError(f"unknown object type {v!r}")
        return t
    if kind == "units":
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            name = str(EngineeringUnits(int(v)))
            if name.isdigit():
                raise ValueError(f"unknown unit code {v!r}")
            return name
        return str(v)
    if kind == "list":
        s = str(v)
        if s.startswith("["):
            return yaml.safe_load(s)
        return [int(x) if x.strip().isdigit() else x.strip() for x in s.split(",") if x.strip()]
    if kind == "ncref":
        return _convert("int", v) if isinstance(v, (int, float)) or str(v).isdigit() else str(v)
    if kind == "str":
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    return v  # value: as read


def _table(ws, columns: Optional[Dict[str, Tuple[str, str]]], errors: List[str], warnings: List[str],
           required: Tuple[str, ...]) -> List[Tuple[int, Dict[str, Any]]]:
    """Read a sheet as (row number, {column: raw value}) for the non-empty, non-comment rows."""
    header: Optional[Dict[int, str]] = None
    rows = []
    for row_no, values in enumerate(ws.iter_rows(values_only=True), 1):
        if all(_blank(v) for v in values):
            continue
        first = next((v for v in values if not _blank(v)), None)
        if isinstance(first, str) and first.lstrip().startswith("#"):
            continue
        if header is None:
            header = {}
            for i, v in enumerate(values):
                name = _norm(v)
                if not name:
                    continue
                if columns is not None and name not in columns and not name.startswith("text_"):
                    warnings.append(f"{ws.title}: unknown column {v!r} ignored")
                    continue
                header[i] = name
            missing = [c for c in required if c not in header.values()]
            if missing:
                errors.append(f"{ws.title} row {row_no}: missing column(s) {', '.join(missing)}")
                return []
            continue
        rows.append((row_no, {name: values[i] for i, name in header.items()
                              if i < len(values) and not _blank(values[i])}))
    return rows


def _pydantic_errors(e: ValidationError, prefix: str, colmap: Dict[str, str]) -> List[str]:
    out = []
    for err in e.errors():
        loc = [str(x) for x in err["loc"]]
        col = (colmap.get(".".join(loc[:2])) or colmap.get(loc[0], "extra")) if loc else None
        out.append(f"{prefix}{', column ' + repr(col) if col else ''}: {'.'.join(loc)}: {err['msg']}")
    return out


def import_xlsx(data: bytes, base: Optional[SimConfig] = None) -> Tuple[SimConfig, List[str]]:
    """Parse a point-list workbook into a SimConfig. Returns (config, warnings); raises XlsxImportError."""
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as e:  # not a zip / not a workbook
        raise ValueError(f"not a readable .xlsx file: {e}") from None
    errors: List[str] = []
    warnings: List[str] = []
    for title in ("Devices", "Points"):
        if title not in wb.sheetnames:
            errors.append(f"sheet {title!r} is missing")
    if errors:
        raise XlsxImportError(errors)

    def convert(sheet: str, row_no: int, cols: Dict[str, Tuple[str, str]], raw: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        for col, v in raw.items():
            if col not in cols:
                continue
            try:
                out[col] = _convert(cols[col][0], v)
            except ValueError as e:
                errors.append(f"{sheet} row {row_no}, column {col!r}: {e}")
        return out

    # state texts
    states: Dict[int, List[str]] = {}
    if "StateTexts" in wb.sheetnames:
        for row_no, raw in _table(wb["StateTexts"], None, errors, warnings, ("ref",)):
            try:
                ref = _convert("int", raw.pop("ref"))
            except (KeyError, ValueError) as e:
                errors.append(f"StateTexts row {row_no}, column 'ref': {e if isinstance(e, ValueError) else 'empty'}")
                continue
            texts = {int(k[5:]): _convert("str", v) for k, v in raw.items() if k[5:].isdigit()}
            n = max(texts, default=0)
            if not n:
                errors.append(f"StateTexts row {row_no}, column 'text_1': no state texts")
            elif ref in states:
                errors.append(f"StateTexts row {row_no}, column 'ref': duplicate ref {ref}")
            else:
                states[ref] = [texts.get(i, "") for i in range(1, n + 1)]

    # devices
    devices: Dict[int, Dict[str, Any]] = {}
    dev_rows: Dict[int, int] = {}
    for row_no, raw in _table(wb["Devices"], DEVICE_COLUMNS, errors, warnings, ("device_id", "name")):
        d = convert("Devices", row_no, DEVICE_COLUMNS, raw)
        for col in ("device_id", "name"):
            if col not in raw:
                errors.append(f"Devices row {row_no}, column {col!r}: required")
        if "device_id" not in d or "name" not in d:
            continue
        if d["device_id"] in devices:
            errors.append(f"Devices row {row_no}, column 'device_id': duplicate device_id {d['device_id']}")
            continue
        extra = d.pop("extra", {})
        devices[d["device_id"]] = {**extra, **d, "objects": []}
        dev_rows[d["device_id"]] = row_no

    # points
    names: Dict[Tuple[int, str], int] = {}
    point_rows: Dict[Tuple[int, str, int], int] = {}
    colmap = {c: c for c in _DIRECT}
    colmap.update({"value": "value", "states": "state_texts", "alarm.alarm_value": "alarm_values",
                   "alarm.alarm_values": "alarm_values"})
    colmap.update({f"alarm.{f}": c for c, f in _ALARM_COLS.items()})
    for row_no, raw in _table(wb["Points"], POINT_COLUMNS, errors, warnings, ("device_id", "type", "name")):
        n_errors = len(errors)
        p = convert("Points", row_no, POINT_COLUMNS, raw)
        prefix = f"Points row {row_no}"
        for col in ("device_id", "type", "name"):
            if col not in raw:
                errors.append(f"{prefix}, column {col!r}: required")
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
        names[key] = row_no
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
        if len(errors) > n_errors:  # the row already has errors: don't add follow-up validation errors
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
            point_rows[ik] = row_no
        dev["objects"].append(obj)

    result = []
    for dev_id, d in devices.items():
        try:
            result.append(DeviceConfig.model_validate(d))
        except ValidationError as e:
            errors.extend(_pydantic_errors(e, f"Devices row {dev_rows[dev_id]}", {c: c for c in DEVICE_COLUMNS}))

    # network / simulation settings
    base = base or SimConfig()
    network, simulation = base.network.model_copy(deep=True), base.simulation.model_copy(deep=True)
    if "Network" in wb.sheetnames:
        tree: Dict[str, Dict[str, Any]] = {"network": {}, "simulation": {}}
        key_rows: Dict[str, int] = {}
        rows = _table(wb["Network"], {"key": ("str", ""), "value": ("value", "")}, errors, warnings, ("key", "value"))
        for row_no, raw in rows:
            k = str(raw.get("key", "")).strip()
            top, _, rest = k.partition(".")
            if top not in tree or not rest:
                errors.append(f"Network row {row_no}, column 'key': unknown key {k!r} "
                              "(network.<name> or simulation.<name>)")
                continue
            if "value" not in raw:
                continue
            node = tree[top]
            parts = rest.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = raw["value"]
            key_rows[k] = row_no
        if rows:
            for top, model in (("network", NetworkConfig), ("simulation", SimulationConfig)):
                try:
                    validated = model.model_validate(tree[top])
                except ValidationError as e:
                    for err in e.errors():
                        k = ".".join([top] + [str(x) for x in err["loc"]])
                        row = next((r for kk, r in key_rows.items() if k.startswith(kk) or kk.startswith(k)), None)
                        where = f"Network row {row}, column 'value'" if row else "Network"
                        errors.append(f"{where}: {k}: {err['msg']}")
                    continue
                if top == "network":
                    network = validated
                else:
                    simulation = validated

    if errors:
        raise XlsxImportError(errors)
    try:
        cfg = SimConfig(network=network, simulation=simulation, devices=result)
    except ValidationError as e:
        raise XlsxImportError([f"Devices / Network: {err['msg']}" for err in e.errors()]) from None
    return cfg, warnings
