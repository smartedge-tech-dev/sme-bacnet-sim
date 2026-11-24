"""File and Program objects: config, AtomicReadFile / AtomicWriteFile (stream / record, errors), Program_Change.

Uses port 47970 / client port 47971 so it does not clash with other tests or a running simulator.
"""

import asyncio

import pytest
from bacpypes3.apdu import AtomicReadFileACK, AtomicReadFileRequest, AtomicWriteFileACK, AtomicWriteFileRequest
from bacpypes3.app import Application
from bacpypes3.basetypes import AtomicReadFileRequestAccessMethodChoice, AtomicWriteFileRequestAccessMethodChoice
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

from sme_bacnet_sim.config import dump_yaml, parse_text
from sme_bacnet_sim.ede import export_ede, import_ede
from sme_bacnet_sim.engine import Engine, detect_ip

CONFIG = """
network: {ip: auto, port: 47970, virtual_network: 247, router: {device_id: 4194170}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2471
    name: File-Dev
    objects:
      - {type: av, name: Setpoint, value: 20}
      - {type: file, name: Notes, file_type: text/plain, content: "hello world"}
      - {type: file, name: Log, access: record, content: "line1\\nline2\\nline3"}
      - {type: file, name: Firmware, file_type: application/octet-stream, content: "v1.0", read_only: true}
      - {type: file, name: FromDisk, path: data/notes.txt}
      - {type: program, name: Sequencer, instance_of: AHU-Sequence, program_state: running}
"""

FILE = lambda i: ObjectIdentifier(f"file,{i}")  # noqa: E731
PROG = ObjectIdentifier("program,1")


def _code(x) -> str:
    r = getattr(x, "reason", None) or getattr(getattr(x, "errorType", None), "errorCode", None) \
        or getattr(x, "errorCode", None) or x
    return str(r).replace("-", "").lower()


async def _call(coro, timeout=5.0):
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        raise
    except BaseException as e:  # error / reject / abort PDUs are raised by bacpypes3 (not all are Exceptions)
        return e


def _read_stream(addr, oid, start, count):
    return AtomicReadFileRequest(fileIdentifier=oid, destination=addr, accessMethod=AtomicReadFileRequestAccessMethodChoice(
        streamAccess={"fileStartPosition": start, "requestedOctetCount": count}))


def _read_records(addr, oid, start, count):
    return AtomicReadFileRequest(fileIdentifier=oid, destination=addr, accessMethod=AtomicReadFileRequestAccessMethodChoice(
        recordAccess={"fileStartRecord": start, "requestedRecordCount": count}))


def _write_stream(addr, oid, start, data):
    return AtomicWriteFileRequest(fileIdentifier=oid, destination=addr, accessMethod=AtomicWriteFileRequestAccessMethodChoice(
        streamAccess={"fileStartPosition": start, "fileData": data}))


def _write_records(addr, oid, start, recs):
    return AtomicWriteFileRequest(fileIdentifier=oid, destination=addr, accessMethod=AtomicWriteFileRequestAccessMethodChoice(
        recordAccess={"fileStartRecord": start, "recordCount": len(recs), "fileRecordData": recs}))


def test_config_errors():
    for bad in ("{type: file, name: F, content: a, path: b}", "{type: av, name: A, content: x}",
                "{type: file, name: F, access: random}", "{type: av, name: A, program_state: running}",
                "{type: program, name: P, program_state: loading}"):
        with pytest.raises(Exception):
            parse_text(f"devices: [{{device_id: 1, name: D, objects: [{bad}]}}]")


def test_ede_roundtrip():
    files = export_ede(parse_text(CONFIG))
    main = next(v for k, v in files.items() if "state" not in k.lower())
    cfg, warnings = import_ede(main)
    objs = {o.name: o for o in cfg.devices[0].objects}
    assert objs["Notes"].type == "file" and objs["Notes"].content == ""
    assert objs["Sequencer"].type == "program"
    assert any("Notes" in w and "content" in w for w in warnings)


def test_bacnet_file_and_program(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "notes.txt").write_bytes(b"from disk")
    path = tmp_path / "sim.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    asyncio.run(_flow(path))


async def _flow(path):
    ip = detect_ip()
    engine = Engine(parse_text(path.read_text(encoding="utf-8")), str(path))
    await engine.start()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194271), objectName="file-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47971", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47970"), [247])
        iams = await client.who_is(address=Address("247:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2471]
        rt = engine.devices[2471]

        # ---- properties (ReadProperty / RPM)
        assert await client.read_property(addr, FILE(1), "file-size") == 11
        assert await client.read_property(addr, FILE(1), "file-type") == "text/plain"
        assert str(await client.read_property(addr, FILE(2), "file-access-method")) == "record-access"
        res = await client.read_property_multiple(addr, [FILE(2), ["record-count", "file-size", "read-only"],
                                                         FILE(3), ["read-only"]])
        vals = [(str(r[0]), str(r[1]), r[3]) for r in res]
        assert [v[2] for v in vals] == [3, 15, False, True]
        assert await client.read_property(addr, FILE(4), "file-size") == 9  # loaded from data/notes.txt

        # ---- stream read
        r = await _call(client.request(_read_stream(addr, FILE(1), 6, 100)))
        assert isinstance(r, AtomicReadFileACK) and r.endOfFile
        assert bytes(r.accessMethod.streamAccess.fileData) == b"world"
        r = await _call(client.request(_read_stream(addr, FILE(1), 0, 5)))
        assert bytes(r.accessMethod.streamAccess.fileData) == b"hello" and not r.endOfFile

        # ---- stream write: overwrite, append (-1); file-size / modification-date follow (simulated clock)
        engine.set_clock(1700000000.0, "test")
        r = await _call(client.request(_write_stream(addr, FILE(1), 6, b"there")))
        assert isinstance(r, AtomicWriteFileACK) and r.fileStartPosition == 6
        r = await _call(client.request(_write_stream(addr, FILE(1), -1, b"!")))
        assert r.fileStartPosition == 11
        assert await client.read_property(addr, FILE(1), "file-size") == 12
        md = await client.read_property(addr, FILE(1), "modification-date")
        assert tuple(md.date)[0] + 1900 == 2023
        notes = next(f for f in rt.files if f.cfg.name == "Notes")
        assert notes.cfg.content == "hello there!"  # kept in the config for Save
        assert "hello there!" in dump_yaml(engine.config)

        # ---- record read / write
        r = await _call(client.request(_read_records(addr, FILE(2), 1, 5)))
        ra = r.accessMethod.recordAccess
        assert r.endOfFile and ra.fileStartRecord == 1 and ra.returnedRecordCount == 2
        assert [bytes(x) for x in ra.fileRecordData] == [b"line2", b"line3"]
        r = await _call(client.request(_write_records(addr, FILE(2), 1, [b"LINE2"])))
        assert isinstance(r, AtomicWriteFileACK) and r.fileStartRecord == 1
        r = await _call(client.request(_write_records(addr, FILE(2), -1, [b"line4", b"line5"])))
        assert r.fileStartRecord == 3
        assert await client.read_property(addr, FILE(2), "record-count") == 5
        log = next(f for f in rt.files if f.cfg.name == "Log")
        assert log.cfg.content == "line1\nLINE2\nline3\nline4\nline5"

        # ---- path-backed file: written in memory only, the config / disk file is left alone
        r = await _call(client.request(_write_stream(addr, FILE(4), 0, b"FROM")))
        assert isinstance(r, AtomicWriteFileACK)
        disk = next(f for f in rt.files if f.cfg.name == "FromDisk")
        assert disk.data == b"FROM disk" and disk.cfg.content is None
        assert (path.parent / "data" / "notes.txt").read_bytes() == b"from disk"

        # ---- errors
        cases = [
            (_read_stream(addr, FILE(1), 100, 1), "invalidfilestartposition"),
            (_read_records(addr, FILE(2), 9, 1), "invalidfilestartposition"),
            (_write_stream(addr, FILE(1), 50, b"x"), "invalidfilestartposition"),
            (_read_records(addr, FILE(1), 0, 1), "invalidfileaccessmethod"),
            (_write_stream(addr, FILE(2), 0, b"x"), "invalidfileaccessmethod"),
            (_write_stream(addr, FILE(3), 0, b"v2.0"), "fileaccessdenied"),
            (_read_stream(addr, FILE(9), 0, 1), "unknownobject"),
            (_read_stream(addr, ObjectIdentifier("analog-value,1"), 0, 1), "inconsistentobjecttype"),
        ]
        for req, code in cases:
            r = await _call(client.request(req))
            assert _code(r) == code, (req.accessMethod, r)
        r = await _call(client.write_property(addr, FILE(1), "file-size", 0))
        assert _code(r) == "writeaccessdenied"

        # ---- Program: state, Program_Change transitions
        assert str(await client.read_property(addr, PROG, "program-state")) == "running"
        assert await client.read_property(addr, PROG, "instance-of") == "AHU-Sequence"
        for request, state in [("halt", "halted"), ("restart", "running"), ("unload", "idle"),
                               ("load", "running"), ("halt", "halted"), ("run", "running"), ("ready", "running")]:
            await client.write_property(addr, PROG, "program-change", request)
            assert str(await client.read_property(addr, PROG, "program-state")) == state, request
            assert str(await client.read_property(addr, PROG, "program-change")) == "ready"
        await client.write_property(addr, PROG, "program-change", "halt")
        assert await client.read_property(addr, PROG, "description-of-halt") == "halted by request"
        assert str(await client.read_property(addr, PROG, "reason-for-halt")) == "normal"
        r = await _call(client.write_property(addr, PROG, "program-state", "running"))
        assert _code(r) == "writeaccessdenied"
        engine.program_change(2471, 1, "run")  # UI / HTTP API path
        objs = {o["name"]: o for o in engine.snapshot()["devices"][0]["objects"]}
        assert objs["Sequencer"]["value"] == "running" and objs["Notes"]["value"] == 12
        assert objs["Log"]["records"] == 5
    finally:
        client.close()
        await engine.stop()
