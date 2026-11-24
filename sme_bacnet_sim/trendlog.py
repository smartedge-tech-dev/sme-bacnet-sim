"""BACnet Trend Log objects (polled and COV logging) and the server side of ReadRange.

bacpypes3 0.1.0 defines the Trend Log object and the ReadRange PDUs but its
server-side ``do_ReadRangeRequest`` raises NotImplementedError, so the range
selection (ASHRAE 135 clause 15.8) is implemented here.

Timestamps
----------
Records are stamped with the *simulated* clock (``Engine.sim_epoch +
Engine.sim_time``, local time), not the wall clock.  With
``simulation.time_scale`` > 1 the log therefore spans simulated hours/days and
the samples are ``log_interval`` apart, which is what a client trending the
point expects.  ReadRange "by time" compares against the same clock.

Logging types
-------------
* ``polled``: one record every ``log_interval`` simulated seconds.
* ``cov``: a record whenever the logged value changes by at least the
  increment (Client_COV_Increment if configured, else the target's
  COV_Increment for its present-value, else any change; boolean / enumerated /
  integer data: any change) or the target's status flags change.  The first
  record is taken as soon as the log is enabled with an empty buffer.
  Changes are detected once per simulation tick.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, List, Optional, Tuple

from bacpypes3.apdu import (
    ReadRangeACK, ReadRangeRequest, decode_max_apdu_length_accepted, decode_max_segments_accepted,
)
from bacpypes3.basetypes import DateTime, LogRecord, PropertyIdentifier, StatusFlags
from bacpypes3.constructeddata import Any as AnyData, ListOf
from bacpypes3.errors import ExecutionError
from bacpypes3.local.object import Object as _LocalObject
from bacpypes3.object import TrendLogObject as _TrendLogObject
from bacpypes3.primitivedata import Boolean, Date, Enumerated, Integer, Real, Double, Time, Unsigned

LOG_BUFFER = PropertyIdentifier("log-buffer")
RECORD_COUNT = PropertyIdentifier("record-count")
SEQ_MODULO = 0xFFFFFFFF  # sequence numbers run 1 .. 2^32-1 and then wrap (clause 12.25.17)

# conservative encoded size of one LogRecord (12 timestamp + 7 datum + 3 status flags)
_RECORD_BYTES = 24
_ACK_OVERHEAD = 48

# record: (sequence number, sim epoch seconds rounded to 1/100 s, datum choice, value, status flags)
Record = Tuple[int, float, str, Any, Any]


def datum_kind(datatype: type) -> Optional[str]:
    """LogRecord.logDatum choice for a property datatype, or None if not loggable."""
    for cls, kind in ((Boolean, "booleanValue"), (Real, "realValue"), (Double, "realValue"),
                      (Enumerated, "enumeratedValue"), (Unsigned, "unsignedValue"), (Integer, "integerValue")):
        if isinstance(datatype, type) and issubclass(datatype, cls):
            return kind
    return None


def to_datetime(ts: float) -> DateTime:
    lt = time.localtime(ts)
    hundredths = int(round((ts - math.floor(ts)) * 100)) % 100
    return DateTime(
        date=Date((lt.tm_year - 1900, lt.tm_mon, lt.tm_mday, lt.tm_wday + 1)),
        time=Time((lt.tm_hour, lt.tm_min, lt.tm_sec, hundredths)),
    )


def from_datetime(dt: DateTime) -> float:
    (y, mo, d, _), (h, mi, s, hu) = tuple(dt.date), tuple(dt.time)
    if 255 in (y, mo, d, h, mi, s) or mo > 12 or d > 31:
        # wildcard / special values make the reference time ambiguous
        raise ExecutionError(errorClass="property", errorCode="valueOutOfRange")
    return time.mktime((y + 1900, mo, d, h, mi, s, 0, 0, -1)) + (0 if hu == 255 else hu / 100)


class SimTrendLogObject(_LocalObject, _TrendLogObject):
    """Trend Log whose buffer lives in a ring (``_records``); read it with ReadRange."""

    def __init__(self, buffer_size: int, **kwargs: Any) -> None:
        super().__init__(bufferSize=buffer_size, recordCount=0, totalRecordCount=0, **kwargs)
        self._records: Deque[Record] = deque(maxlen=buffer_size)

    async def read_property(self, attr, index=None):  # type: ignore[override]
        if _pid(attr) == LOG_BUFFER:
            # the buffer can be large; clients must use ReadRange (common practice for trend logs)
            raise ExecutionError(errorClass="property", errorCode="readAccessDenied")
        return await super().read_property(attr, index)

    async def write_property(self, attr, value, index=None, priority=None):  # type: ignore[override]
        if _pid(attr) == RECORD_COUNT:
            if int(value) != 0:
                raise ExecutionError(errorClass="property", errorCode="valueOutOfRange")
            self.clear()  # writing zero deletes all records (clause 12.25.16)
            return
        await super().write_property(attr, value, index, priority)

    def clear(self) -> None:
        self._records.clear()
        self.recordCount = 0

    def append(self, ts: float, kind: str, value: Any, flags: Any) -> None:
        seq = int(self.totalRecordCount) % SEQ_MODULO + 1
        if flags is not None:
            flags = StatusFlags(list(flags))  # snapshot: the target may update its flags in place
        self._records.append((seq, round(ts, 2), kind, value, flags))
        self.totalRecordCount = seq
        self.recordCount = len(self._records)

    def records(self) -> List[Record]:
        return list(self._records)


def _pid(attr: Any) -> Optional[PropertyIdentifier]:
    try:
        return PropertyIdentifier(attr)
    except Exception:
        return None


def _log_record(r: Record) -> LogRecord:
    seq, ts, kind, value, flags = r
    rec = LogRecord(timestamp=to_datetime(ts), logDatum={kind: value})
    if flags is not None:
        rec.statusFlags = flags
    return rec


# --------------------------------------------------------------------------- ReadRange


def select_range(records: List[Record], rng: Any) -> Tuple[List[Record], bool]:
    """Apply a ReadRange range (None = whole buffer) to the oldest-first record list.

    Returns (selected records oldest-first, include firstSequenceNumber in the ACK).
    """
    if rng is None:
        return records, False
    if rng.byPosition is not None:
        ref, count = int(rng.byPosition.referenceIndex), int(rng.byPosition.count)
        if count == 0 or not 1 <= ref <= len(records):
            return [], False
        if count > 0:
            return records[ref - 1:ref - 1 + count], False
        return records[max(0, ref + count):ref], False
    if rng.bySequenceNumber is not None:
        ref, count = int(rng.bySequenceNumber.referenceSequenceNumber), int(rng.bySequenceNumber.count)
        lo, hi = (ref, ref + count - 1) if count > 0 else (ref + count + 1, ref)
        return [r for r in records if lo <= r[0] <= hi] if count else [], True
    if rng.byTime is not None:
        ref_ts, count = from_datetime(rng.byTime.referenceTime), int(rng.byTime.count)
        if count > 0:  # first record newer than the reference time, going forward
            return [r for r in records if r[1] > ref_ts][:count], True
        if count < 0:  # newest record older than the reference time, going backward
            older = [r for r in records if r[1] < ref_ts]
            return older[max(0, len(older) + count):], True
        return [], True
    return records, False


def _max_items(apdu: ReadRangeRequest) -> int:
    """How many records fit in the response the client said it can accept."""
    size = decode_max_apdu_length_accepted(apdu.apduMaxResp) or 480
    if apdu.apduSA:
        segs = decode_max_segments_accepted(apdu.apduMaxSegs)
        size *= min(segs or 16, 16)
    return max(1, (size - _ACK_OVERHEAD) // _RECORD_BYTES)


def read_range_ack(obj: SimTrendLogObject, apdu: ReadRangeRequest) -> ReadRangeACK:
    if apdu.propertyArrayIndex is not None:
        raise ExecutionError(errorClass="property", errorCode="propertyIsNotAnArray")
    records = obj.records()
    selected, with_seq = select_range(records, apdu.range)
    limit = _max_items(apdu)
    more = len(selected) > limit
    if more:
        # keep the records nearest the reference point: the head going forward, the tail going backward
        backward = apdu.range is not None and any(
            r is not None and int(r.count) < 0 for r in (apdu.range.byPosition, apdu.range.bySequenceNumber,
                                                          apdu.range.byTime))
        selected = selected[-limit:] if backward else selected[:limit]
    first = bool(selected) and selected[0][0] == records[0][0]
    last = bool(selected) and selected[-1][0] == records[-1][0]
    ack = ReadRangeACK(
        objectIdentifier=apdu.objectIdentifier,
        propertyIdentifier=apdu.propertyIdentifier,
        resultFlags=[int(first), int(last), int(more)],
        itemCount=len(selected),
        itemData=AnyData(ListOf(LogRecord)([_log_record(r) for r in selected]).encode()),
        context=apdu,
    )
    if with_seq and selected:
        ack.firstSequenceNumber = selected[0][0]
    return ack


# --------------------------------------------------------------------------- runtime


@dataclass
class TrendLog:
    """Engine-side state of one trend log: polls its target on the simulated clock."""

    device_id: int
    cfg: Any  # ObjectConfig
    obj: SimTrendLogObject
    target: Any  # engine.Point
    attr: str  # bacpypes3 attribute name of the logged property
    kind: str  # LogRecord.logDatum choice
    interval: float  # sim seconds (polled mode)
    cov: bool = False  # Logging_Type cov instead of polled
    increment: Optional[float] = None  # Client_COV_Increment (cov mode); None = target's COV_Increment
    due: float = 0.0  # next sample time (sim seconds)

    @property
    def key(self) -> str:
        return f"{self.cfg.type}:{self.cfg.instance}"

    def sample(self, sim_time: float, sim_epoch: float) -> bool:
        """Polled: record one sample when an interval is due (missed intervals collapse into one).
        COV: record when the value or the status flags changed enough since the last record."""
        if not self.obj.enable:
            return False
        if self.cov:
            return self._sample_cov(sim_time, sim_epoch)
        if sim_time < self.due:
            return False
        self.obj.append(sim_epoch + sim_time, self.kind, self._value(), getattr(self.target.obj, "statusFlags", None))
        self.due += self.interval * (math.floor((sim_time - self.due) / self.interval) + 1)
        return True

    def _value(self) -> Any:
        value = getattr(self.target.obj, self.attr)
        if self.kind == "realValue":
            return float(value)
        if self.kind == "booleanValue":
            return bool(value)
        return int(value)

    def _sample_cov(self, sim_time: float, sim_epoch: float) -> bool:
        value = self._value()
        flags = getattr(self.target.obj, "statusFlags", None)
        recs = self.obj._records
        if recs:  # compare with the last record (an empty / cleared buffer always takes the current value)
            last, last_flags = recs[-1][3], recs[-1][4]
            same_flags = (list(flags) if flags is not None else None) == \
                (list(last_flags) if last_flags is not None else None)
            if same_flags:
                if value == last:
                    return False
                if self.kind == "realValue" and abs(value - last) < self.cov_increment():
                    return False
        self.obj.append(sim_epoch + sim_time, self.kind, value, flags)
        return True

    def cov_increment(self) -> float:
        """Effective increment for real values: Client_COV_Increment, else the target's COV_Increment."""
        if self.increment is not None:
            return self.increment
        if self.attr == "presentValue":
            inc = getattr(self.target.obj, "covIncrement", None)
            if inc is not None:
                return float(inc)
        return 0.0

    def data(self) -> List[Tuple[float, float]]:
        return [(r[1], float(r[3])) for r in self.obj.records()]

    def status(self) -> dict:
        recs = self.obj._records
        d = {"value": int(self.obj.recordCount), "total": int(self.obj.totalRecordCount),
             "enabled": bool(self.obj.enable)}
        if recs:
            d["last"] = [recs[-1][1], float(recs[-1][3])]
        return d
