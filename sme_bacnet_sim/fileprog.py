"""File and Program objects, AtomicReadFile / AtomicWriteFile.

File: the content lives in memory (loaded from ``content`` or ``path`` at start).  Stream access works on the
bytes; record access treats every line as one record (the record data has no line terminator).  Semantics of
the services follow the public bacpypes sample file objects:

* read: start beyond the end -> ``services / invalid-file-start-position``; the returned data stops at the end
  of the file and End_Of_File tells whether it was reached.
* write: start ``-1`` appends; start beyond the end -> ``invalid-file-start-position``; otherwise the data
  overwrites from the start position (and extends the file).  The ACK returns the actual start position.
* wrong access method -> ``services / invalid-file-access-method``; Read_Only -> ``services /
  file-access-denied``; not a File object -> ``services / inconsistent-object-type``.

Program: a simulated program state machine driven by Program_Change (see :class:`SimProgram`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from bacpypes3.apdu import AtomicReadFileACK, AtomicWriteFileACK
from bacpypes3.basetypes import AtomicReadFileACKAccessMethodChoice
from bacpypes3.errors import ExecutionError
from bacpypes3.local.object import Object as _Object
from bacpypes3.object import FileObject as _FileObject, ProgramObject as _ProgramObject

from .config import FILE, PROGRAM, ObjectConfig
from .trendlog import from_datetime, to_datetime

# properties a client may not write (WriteProperty answers write-access-denied)
FILE_READONLY = {"file-size", "modification-date", "file-access-method", "record-count", "read-only"}
PROGRAM_READONLY = {"program-state", "reason-for-halt", "description-of-halt", "instance-of"}

# Program_Change request -> new Program_State (the request is acknowledged by resetting it to ``ready``)
PROGRAM_TRANSITIONS = {"load": "running", "run": "running", "restart": "running", "halt": "halted",
                       "unload": "idle"}


class FileObject(_Object, _FileObject):
    async def _post_init(self) -> None:
        pass  # no notification-class lookup (File has no Notification_Class)


class ProgramObject(_Object, _ProgramObject):
    pass


def _error(code: str, cls: str = "services") -> ExecutionError:
    return ExecutionError(errorClass=cls, errorCode=code)


@dataclass
class SimFile:
    device_id: int
    cfg: Any  # ObjectConfig
    obj: FileObject
    data: bytes = b""  # stream access
    records: List[bytes] = field(default_factory=list)  # record access

    @property
    def key(self) -> str:
        return f"{FILE}:{self.cfg.instance}"

    @property
    def stream(self) -> bool:
        return self.cfg.access != "record"

    def _sync(self, now: Optional[float] = None) -> None:
        """Update File_Size / Record_Count (and Modification_Date when ``now`` is given)."""
        if self.stream:
            self.obj.fileSize = len(self.data)
        else:
            self.obj.fileSize = sum(len(r) for r in self.records)
            self.obj.recordCount = len(self.records)
        if now is not None:
            self.obj.modificationDate = to_datetime(now)

    def text(self) -> Optional[str]:
        """Current content as text (None if it is not UTF-8)."""
        raw = self.data if self.stream else b"\n".join(self.records)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None

    # ---- AtomicReadFile / AtomicWriteFile

    def check_access(self, stream: bool, write: bool) -> None:
        if stream != self.stream:
            raise _error("invalidFileAccessMethod")
        if write and bool(self.obj.readOnly):
            raise _error("fileAccessDenied")

    def read(self, apdu: Any) -> AtomicReadFileACK:
        am = apdu.accessMethod
        if am.streamAccess is not None:
            self.check_access(True, False)
            start, count = int(am.streamAccess.fileStartPosition), int(am.streamAccess.requestedOctetCount)
            if start < 0 or start > len(self.data):
                raise _error("invalidFileStartPosition")
            chunk = self.data[start:start + count]
            eof = start + len(chunk) >= len(self.data)
            method = AtomicReadFileACKAccessMethodChoice(
                streamAccess={"fileStartPosition": start, "fileData": chunk})
        else:
            self.check_access(False, False)
            ra = am.recordAccess
            start, count = int(ra.fileStartRecord), int(ra.requestedRecordCount)
            if start < 0 or start > len(self.records):
                raise _error("invalidFileStartPosition")
            recs = self.records[start:start + count]
            eof = start + len(recs) >= len(self.records)
            method = AtomicReadFileACKAccessMethodChoice(
                recordAccess={"fileStartRecord": start, "returnedRecordCount": len(recs), "fileRecordData": recs})
        return AtomicReadFileACK(endOfFile=eof, accessMethod=method, context=apdu)

    def write(self, apdu: Any, now: float) -> AtomicWriteFileACK:
        am = apdu.accessMethod
        if am.streamAccess is not None:
            self.check_access(True, True)
            start, data = int(am.streamAccess.fileStartPosition), bytes(am.streamAccess.fileData)
            if start == -1:
                start = len(self.data)
            if start < 0 or start > len(self.data):
                raise _error("invalidFileStartPosition")
            self.data = self.data[:start] + data + self.data[start + len(data):]
            ack = AtomicWriteFileACK(fileStartPosition=start, context=apdu)
        else:
            self.check_access(False, True)
            ra = am.recordAccess
            start, recs = int(ra.fileStartRecord), [bytes(r) for r in ra.fileRecordData]
            if start == -1:
                start = len(self.records)
            if start < 0 or start > len(self.records):
                raise _error("invalidFileStartPosition")
            self.records[start:start + len(recs)] = recs
            ack = AtomicWriteFileACK(fileStartRecord=start, context=apdu)
        self._sync(now)
        if self.cfg.path is None:  # keep the content in the config so Save / Export store it
            txt = self.text()
            if txt is not None:
                self.cfg.content = txt
        return ack

    def status(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"value": int(self.obj.fileSize), "read_only": bool(self.obj.readOnly)}
        if not self.stream:
            d["records"] = int(self.obj.recordCount)
        try:
            d["modified"] = from_datetime(self.obj.modificationDate)
        except Exception:
            d["modified"] = None
        return d


def build_file(device_id: int, oc: ObjectConfig, base_dir: Path, now: float) -> SimFile:
    if oc.path is not None:
        p = Path(oc.path)
        p = p if p.is_absolute() else base_dir / p
        raw = p.read_bytes()
    else:
        raw = (oc.content or "").encode("utf-8")
    record = oc.access == "record"
    kw: Dict[str, Any] = dict(objectIdentifier=(FILE, oc.instance), objectName=oc.name,
                              fileType=oc.file_type or "text/plain", fileSize=0,
                              modificationDate=to_datetime(now), archive=False, readOnly=bool(oc.read_only),
                              fileAccessMethod="recordAccess" if record else "streamAccess")
    if oc.description:
        kw["description"] = oc.description
    if record:
        kw["recordCount"] = 0
    f = SimFile(device_id, oc, FileObject(**kw))
    if record:
        f.records = raw.splitlines()
    else:
        f.data = raw
    f._sync()
    return f


@dataclass
class SimProgram:
    """Simulated program: Program_Change requests move Program_State immediately.

    load / run / restart -> running, halt -> halted (Reason_For_Halt ``normal``), unload -> idle; ``ready`` does
    nothing.  Every request is accepted in every state and Program_Change returns to ``ready`` once applied.
    """
    device_id: int
    cfg: Any  # ObjectConfig
    obj: ProgramObject

    @property
    def key(self) -> str:
        return f"{PROGRAM}:{self.cfg.instance}"

    def apply(self, request: str) -> Optional[Tuple[str, str]]:
        """Apply a Program_Change request; returns (old state, new state) or None for ``ready``."""
        new = PROGRAM_TRANSITIONS.get(request)
        self.obj.programChange = "ready"
        if new is None:
            return None
        old = str(self.obj.programState)
        self.obj.programState = new
        if new == "halted":
            self.obj.reasonForHalt = "normal"
            self.obj.descriptionOfHalt = "halted by request"
        else:
            self.obj.descriptionOfHalt = ""
        return old, new

    def poll(self) -> Optional[Tuple[str, str]]:
        """Pick up a Program_Change written by a client."""
        req = str(self.obj.programChange)
        return None if req == "ready" else self.apply(req)

    def status(self) -> Dict[str, Any]:
        return {"value": str(self.obj.programState), "reason": str(self.obj.reasonForHalt),
                "halt_text": str(self.obj.descriptionOfHalt or "")}


def build_program(device_id: int, oc: ObjectConfig) -> SimProgram:
    state = oc.program_state or "idle"
    kw: Dict[str, Any] = dict(objectIdentifier=(PROGRAM, oc.instance), objectName=oc.name,
                              programState=state, programChange="ready", reasonForHalt="normal",
                              descriptionOfHalt="", instanceOf=oc.instance_of or oc.name,
                              statusFlags=[0, 0, 0, 0], outOfService=False, reliability="no-fault-detected")
    if oc.program_location:
        kw["programLocation"] = oc.program_location
    if oc.description:
        kw["description"] = oc.description
    return SimProgram(device_id, oc, ProgramObject(**kw))
