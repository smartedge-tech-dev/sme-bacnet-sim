"""Record real BACnet points into a replay CSV: ``sme-bacnet-sim record ...``.

Two modes, both read-only (the same guarded client as ``clone``):

* polling (default): every ``--interval`` seconds the present-value of the selected points is read with
  ReadPropertyMultiple (one request per device and up to ``--batch`` objects; falls back to ReadProperty for a
  device that rejects it) and appended to the CSV as one row. The file is flushed after every row, so Ctrl-C (or a
  crash) keeps everything recorded so far; ``--resume`` appends to an existing file with the same columns.
* ``--trend-log``: the log-buffer of the selected Trend Log objects is read once with ReadRange (by position, in
  chunks) and written as a CSV, one row per timestamp. Only ReadRange is added to the allowed services.

The CSV is what the ``replay`` behavior reads: column 1 ``time`` (ISO local date-time), one column per point. Column
names are the point names of the config given with ``-c`` (normally the YAML written by ``clone``), so the recording
can be replayed by that config without renaming anything.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as _dt
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bacpypes3.apdu import ErrorRejectAbortNack, ReadRangeRequest
from bacpypes3.basetypes import ErrorType
from bacpypes3.primitivedata import ObjectIdentifier

from . import clone
from .config import (ACCUMULATOR, ANALOG_TYPES, BINARY_TYPES, LOOP, MULTISTATE_TYPES, OBJECT_TYPE_ALIASES,
                     PULSE_CONVERTER, TREND_LOG, load_file)
from .templates import expand_device

RECORDABLE = ANALOG_TYPES | BINARY_TYPES | MULTISTATE_TYPES | {ACCUMULATOR, PULSE_CONVERTER, LOOP}
TIME_COLUMN = "time"


@dataclass
class Point:
    device: Optional[int]  # None: the only target device
    oid: ObjectIdentifier
    column: str

    @property
    def type(self) -> str:
        return str(self.oid[0])


# --------------------------------------------------------------------------- options


def parse_duration(s: str) -> float:
    """``90`` / ``90s`` / ``15m`` / ``2h`` / ``1d`` -> seconds."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", s or "")
    if not m:
        raise ValueError(f"invalid duration {s!r} (e.g. 90, 30s, 15m, 2h, 1d)")
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def parse_ref(item: str) -> Point:
    """``[DEVICE/]TYPE:INSTANCE[=COLUMN]``, TYPE as in the config (``ai``, ``analog-input``, ``trend-log`` ...)."""
    ref, _, col = item.partition("=")
    dev: Optional[int] = None
    if "/" in ref:
        d, _, ref = ref.partition("/")
        dev = int(d)
    t, sep, inst = ref.partition(":")
    t = OBJECT_TYPE_ALIASES.get(t.strip().lower(), t.strip().lower())
    if not sep or not inst.strip().isdigit():
        raise ValueError(f"invalid point {item!r}: expected [DEVICE/]TYPE:INSTANCE[=COLUMN], e.g. ai:1=OAT")
    oid = ObjectIdentifier((t, int(inst)))
    column = col.strip() or (f"{dev}/" if dev is not None else "") + f"{t}:{int(inst)}"
    return Point(dev, oid, column)


def points_from_config(path: str, names: Optional[List[str]], trend_log: bool,
                       devices: Optional[set]) -> List[Point]:
    """Points of a simulator config (normally the YAML written by ``clone``; any simulator config works, e.g. to
    record from another SME BACnetSim). Column = point name; a name used on more than one device becomes
    ``DEVICE/NAME``."""
    cfg = load_file(path)
    pts: List[Point] = []
    for dev in cfg.devices:
        if devices is not None and dev.device_id not in devices:
            continue
        for o in expand_device(dev):  # template objects and auto-assigned instances, exactly as the simulator
            if (o.type == TREND_LOG) != trend_log or (not trend_log and o.type not in RECORDABLE):
                continue
            if names is not None and o.name not in names:
                continue
            pts.append(Point(dev.device_id, ObjectIdentifier((o.type, o.instance)), o.name))
    if names is not None:
        missing = [n for n in names if n not in {p.column for p in pts}]
        if missing:
            kind = "Trend Log" if trend_log else "recordable point (analog / binary / multi-state / accumulator / " \
                                                 "pulse-converter / loop)"
            raise ValueError(f"{path}: no {kind} named {', '.join(missing)}")
    counts: Dict[str, int] = {}
    for p in pts:
        counts[p.column] = counts.get(p.column, 0) + 1
    for p in pts:
        if counts[p.column] > 1:
            p.column = f"{p.device}/{p.column}"
    return pts


def select_points(args: argparse.Namespace) -> List[Point]:
    items = [x.strip() for x in (args.points or "").split(",") if x.strip()] or None
    wanted = {int(x) for x in args.devices.split(",") if x.strip()} if args.devices else None
    if args.config:
        pts = points_from_config(args.config, items, args.trend_log, wanted)
    elif items:
        pts = [parse_ref(x) for x in items]
        for p in pts:
            if args.trend_log and p.type != TREND_LOG:
                raise ValueError(f"{p.column}: --trend-log reads trend-log objects only")
            if not args.trend_log and p.type not in RECORDABLE:
                raise ValueError(f"{p.column}: {p.type} has no recordable present-value")
    else:
        raise ValueError("select points: -c CONFIG (all points, or --points NAME,...) or --points TYPE:INSTANCE,...")
    if not pts:
        raise ValueError("no points selected")
    cols = [p.column for p in pts]
    dup = sorted({c for c in cols if cols.count(c) > 1})
    if dup:
        raise ValueError(f"duplicate column name(s): {', '.join(dup)}")
    if TIME_COLUMN in cols:
        raise ValueError(f"{TIME_COLUMN!r} is the timestamp column; rename that point's column (=COLUMN)")
    return pts


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sme-bacnet-sim record",
        description="Record present-values of real BACnet points (ReadProperty / ReadPropertyMultiple only) into a "
                    "CSV for the replay behavior; --trend-log reads Trend Log buffers with ReadRange instead.")
    clone.add_link_args(ap, "record")
    ap.add_argument("-c", "--config", metavar="YAML",
                    help="take the points from this config (normally written by clone); columns = point names")
    ap.add_argument("--points", metavar="LIST",
                    help="with -c: point names to record (default: all); without -c: [DEVICE/]TYPE:INSTANCE[=COLUMN]"
                         ",... e.g. ai:1=OAT,bi:3=Occupied")
    ap.add_argument("--trend-log", action="store_true",
                    help="read the selected Trend Log objects' log-buffer once (ReadRange) instead of polling")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between samples (default 60, minimum 1)")
    ap.add_argument("--duration", metavar="TIME", help="stop after this long, e.g. 30m, 8h, 1d (default: until Ctrl-C)")
    ap.add_argument("--count", type=int, metavar="N", help="stop after N samples")
    ap.add_argument("--batch", type=int, default=20, help="objects per ReadPropertyMultiple (default 20)")
    ap.add_argument("--no-rpm", action="store_true", help="never use ReadPropertyMultiple")
    ap.add_argument("--resume", action="store_true", help="append to an existing CSV with the same columns")
    ap.add_argument("-o", "--output", required=True, help="output CSV file")
    return ap


# --------------------------------------------------------------------------- values


def fmt_value(v: Any, obj_type: str) -> str:
    """present-value -> CSV cell in the form the replay behavior and the simulator accept."""
    if v is None or isinstance(v, ErrorType):
        return ""
    if obj_type in BINARY_TYPES:
        s = str(v)
        return s if s in ("active", "inactive") else ("active" if int(v) else "inactive")
    if obj_type in MULTISTATE_TYPES:
        return str(int(v))
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(int(v))
    if isinstance(v, float):
        f = float(v)
        if not math.isfinite(f):
            return ""
        return f"{f:.7g}"  # REAL is single precision: 7 significant digits, no 21.299999237060547
    return str(v)


def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def check_header(path: Path, header: List[str]) -> None:
    with open(path, newline="", encoding="utf-8-sig") as f:
        first = next(csv.reader(f), None)
    if [h.strip() for h in first or []] != header:
        raise ValueError(f"{path}: --resume needs the same columns; the file has {first}, this run records "
                         f"{header}")


# --------------------------------------------------------------------------- run


class Recorder:
    def __init__(self, client: clone.ReadOnlyClient, warn, say, use_rpm: bool, batch: int) -> None:
        self.client, self.warn, self.say, self.batch = client, warn, say, max(1, batch)
        self.rpm: Dict[int, bool] = {}
        self.use_rpm = use_rpm
        self.failing: Dict[str, str] = {}  # column -> last error (warned once until it reads again)

    def _missing(self, p: Point, why: str) -> None:
        if self.failing.get(p.column) != why:
            self.failing[p.column] = why
            self.warn(f"{p.column} ({p.oid}): {why}; the cell is left empty")

    async def sample(self, dev: int, addr, pts: List[Point]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.rpm.get(dev, self.use_rpm) and len(pts) > 1:
            try:
                for i in range(0, len(pts), self.batch):
                    chunk = pts[i:i + self.batch]
                    got = await self.client.read_many(addr, [p.oid for p in chunk], "present-value")
                    for p in chunk:
                        v = got.get(str(p.oid))
                        if isinstance(v, ErrorType):
                            self._missing(p, f"{v.errorClass}: {v.errorCode}")
                        elif v is not None:
                            out[p.column] = v
                self.rpm[dev] = True
                return out
            except ErrorRejectAbortNack as e:
                self.rpm[dev] = False
                self.warn(f"device {dev}: ReadPropertyMultiple failed ({e}); using ReadProperty from now on")
                out.clear()
            except asyncio.TimeoutError:
                for p in pts:
                    if p.column not in out:
                        self._missing(p, "timeout")
                return out
        for p in pts:
            try:
                out[p.column] = await self.client.read(addr, p.oid, "present-value")
            except ErrorRejectAbortNack as e:
                self._missing(p, str(e))
            except asyncio.TimeoutError:
                self._missing(p, "timeout")
        return out


def resolve_devices(pts: List[Point], found: Dict[int, Any]) -> Dict[int, List[Point]]:
    by_dev: Dict[int, List[Point]] = {}
    for p in pts:
        if p.device is None:
            if len(found) != 1:
                raise ValueError(f"{p.column}: {len(found)} devices found; give the device as DEVICE/TYPE:INSTANCE "
                                 f"or narrow the target with --devices ID")
            p.device = next(iter(found))
        by_dev.setdefault(p.device, []).append(p)
    return by_dev


async def run_record(args: argparse.Namespace, progress=None, stop: Optional[asyncio.Event] = None) -> Dict[str, Any]:
    """Run a recording; returns {"rows", "warnings", "services", "columns"}."""

    def say(msg: str) -> None:
        (progress or (lambda m: print(m, file=sys.stderr, flush=True)))(msg)

    pts = select_points(args)
    if args.interval < 1:
        raise ValueError("--interval must be at least 1 second")
    duration = parse_duration(args.duration) if args.duration else None
    if args.count is not None and args.count < 1:
        raise ValueError("--count must be at least 1")
    wanted = {p.device for p in pts if p.device is not None}
    if args.devices:
        wanted |= {int(x) for x in args.devices.split(",") if x.strip()}
    if not (args.who_is or args.address or wanted):
        raise ValueError("give a target: --address IP[:PORT], --who-is LOW-HIGH and/or --devices ID,...")
    low = high = None
    if args.who_is:
        low, high = clone.parse_range(args.who_is)
    elif wanted:
        low, high = min(wanted), max(wanted)

    out = Path(args.output)
    header = [TIME_COLUMN] + [p.column for p in pts]
    if out.exists() and out.stat().st_size > 0:
        if not args.resume:
            raise ValueError(f"{out} exists; use --resume to append to it, or another -o")
        if args.trend_log:
            raise ValueError("--resume is for polling; --trend-log rewrites the whole file")
        check_header(out, header)
    log_path = out.with_name(out.name + ".log.jsonl")
    warnings: List[str] = []
    logf = log_path.open("a" if args.resume else "w", encoding="utf-8")

    def log(**kw: Any) -> None:
        kw = {"ts": _dt.datetime.now().isoformat(timespec="milliseconds"), **kw}
        logf.write(json.dumps(kw, ensure_ascii=False, default=str) + "\n")
        logf.flush()

    def warn(msg: str) -> None:
        warnings.append(msg)
        log(kind="warning", message=msg)
        say(f"warning: {msg}")

    allowed = clone.ALLOWED_REQUESTS + ((ReadRangeRequest,) if args.trend_log else ())
    try:
        link = clone.open_link(args, log, say, allowed=allowed, quiet=True)
    except BaseException:
        logf.close()
        raise
    result: Dict[str, Any] = {"rows": 0, "warnings": warnings, "services": link.client.services, "columns": header}
    try:
        found = await clone.discover(args, link, wanted or None, low, high, warn, say)
        if not found:
            raise ValueError("no target device found (see the warnings above)")
        by_dev = resolve_devices(pts, found)
        missing = sorted(set(by_dev) - set(found))
        if missing:
            raise ValueError(f"device(s) {', '.join(map(str, missing))} not found")
        log(kind="record", columns=header, points={p.column: f"{p.device}/{p.oid}" for p in pts})
        if args.trend_log:
            result["rows"] = await record_trend_logs(link.client, found, by_dev, out, header, warn, say)
        else:
            result["rows"] = await poll(args, link.client, found, by_dev, out, header, duration, warn, say, stop)
    finally:
        await clone.close_link(link, log)
        logf.close()
    return result


async def poll(args, client, found, by_dev, out: Path, header: List[str], duration: Optional[float], warn, say,
               stop: Optional[asyncio.Event]) -> int:
    rec = Recorder(client, warn, say, use_rpm=not args.no_rpm, batch=args.batch)
    new = not (out.exists() and out.stat().st_size > 0)
    rows = 0
    with open(out, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
            f.flush()
        say(f"recording {len(header) - 1} point(s) every {args.interval:g} s to {out} (Ctrl-C to stop)")
        start = time.monotonic()
        k = 0
        while True:
            ts = now_iso()
            values: Dict[str, Any] = {}
            for dev, pts in by_dev.items():
                got = await rec.sample(dev, found[dev], pts)
                for p in pts:
                    if p.column in got:
                        values[p.column] = fmt_value(got[p.column], p.type)
                        rec.failing.pop(p.column, None)
            w.writerow([ts] + [values.get(c, "") for c in header[1:]])
            f.flush()
            rows += 1
            if rows == 1 or rows % 10 == 0:
                say(f"{rows} sample(s), last {ts}")
            k += 1
            if args.count is not None and rows >= args.count:
                break
            elapsed = time.monotonic() - start
            if duration is not None and elapsed + 1e-6 >= duration:
                break
            due = start + k * args.interval
            now = time.monotonic()
            if now > due:  # the sample took longer than the interval: skip the missed ticks
                skipped = math.ceil((now - due) / args.interval)
                warn(f"sampling took {now - (due - args.interval):.1f} s (> --interval {args.interval:g} s); "
                     f"{skipped} sample(s) skipped (lower the point count, raise --rate or --interval)")
                k += skipped
                due = start + k * args.interval
            if duration is not None and due - start > duration + 1e-6:
                break  # the next tick is past --duration
            delay = max(0.0, due - time.monotonic())
            if stop is not None:
                try:
                    await asyncio.wait_for(stop.wait(), delay)
                    break
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(delay)
    return rows


# --------------------------------------------------------------------------- Trend Log (ReadRange)


def _record_value(rec: Any) -> Tuple[Optional[_dt.datetime], Any]:
    """BACnetLogRecord -> (local datetime, value); value None for status / time-change / failure records."""
    ts = getattr(rec, "timestamp", None)
    when: Optional[_dt.datetime] = None
    try:
        d, t = ts.date, ts.time
        when = _dt.datetime(d[0] + 1900, d[1], d[2], t[0], t[1], t[2], (t[3] if t[3] != 255 else 0) * 10000)
    except Exception:
        pass
    datum = getattr(rec, "logDatum", None)
    if datum is None:
        return when, None
    for attr in ("realValue", "unsignedValue", "integerValue", "enumeratedValue", "booleanValue"):
        v = getattr(datum, attr, None)
        if v is not None:
            return when, (bool(v) if attr == "booleanValue" else v)
    return when, None


async def read_log(client, addr, oid: ObjectIdentifier, chunk: int = 50) -> List[Tuple[_dt.datetime, Any]]:
    total = int(await client.read(addr, oid, "record-count"))
    out: List[Tuple[_dt.datetime, Any]] = []
    first = 1
    while first <= total:
        recs = await client.read_range(addr, oid, first, min(chunk, total - first + 1))
        if not recs:
            break
        for r in recs:
            when, v = _record_value(r)
            if when is not None and v is not None:
                out.append((when, v))
        first += len(recs)
    return out


def _log_cell(v: Any, source_type: Optional[str]) -> str:
    if isinstance(v, bool):
        return "active" if v else "inactive"
    if source_type in BINARY_TYPES:
        return "active" if int(v) else "inactive"
    return fmt_value(v, source_type or "")


async def record_trend_logs(client, found, by_dev, out: Path, header: List[str], warn, say) -> int:
    series: Dict[str, Dict[_dt.datetime, str]] = {}
    for dev, pts in by_dev.items():
        addr = found[dev]
        for p in pts:
            try:
                ref = await client.read(addr, p.oid, "log-device-object-property")
                src = str(ref.objectIdentifier[0])
            except Exception:
                src = None
            try:
                recs = await read_log(client, addr, p.oid)
            except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
                warn(f"{p.column} ({p.oid}): log-buffer not readable ({e or type(e).__name__}); column left empty")
                recs = []
            series[p.column] = {t: _log_cell(v, src) for t, v in recs}
            say(f"{p.column}: {len(recs)} record(s)")
    times = sorted({t for s in series.values() for t in s})
    cols = header[1:]
    if not times:
        warn("no log records read; nothing written")
        return 0
    # the replay behavior needs a value in the first row: back-fill each column's leading gap with its first value
    first = {c: next((series[c][t] for t in times if t in series[c]), "") for c in cols}
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        seen: Dict[str, bool] = {}
        for t in times:
            row = [t.isoformat(timespec="seconds" if not t.microsecond else "milliseconds")]
            for c in cols:
                v = series[c].get(t, "")
                if v == "" and not seen.get(c):
                    v = first[c]
                if v != "":
                    seen[c] = True
                row.append(v)
            w.writerow(row)
    tmp.replace(out)
    say(f"{len(times)} row(s) written to {out}")
    return len(times)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        res = asyncio.run(run_record(args))
    except KeyboardInterrupt:
        print(f"stopped; the samples so far are in {args.output}", file=sys.stderr)
        return 130
    except (ValueError, OSError) as e:
        print(f"record error: {e}", file=sys.stderr)
        return 2
    print(f"{res['rows']} row(s) in {args.output}, {len(res['warnings'])} warning(s)", file=sys.stderr)
    return 0
