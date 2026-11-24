"""Trend Log objects: polled logging on the simulated clock and ReadRange from a bacpypes3 client.

Uses BACnet port 47910 / client port 47911 so it does not clash with other tests or a running simulator.
"""

import asyncio

import pytest
from bacpypes3.apdu import ReadRangeACK, ReadRangeRequest
from bacpypes3.app import Application
from bacpypes3.basetypes import LogRecord, Range, RangeByPosition, RangeBySequenceNumber, RangeByTime
from bacpypes3.constructeddata import ListOf
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine, detect_ip

# time_scale 600 with 0.1 s ticks = 60 sim seconds per tick -> one sample per tick at log_interval 60
CONFIG = """
network: {ip: auto, port: 47910, virtual_network: 210, router: {device_id: 4194110}}
simulation: {tick_seconds: 0.1, time_scale: 600}
devices:
  - device_id: 2101
    name: TL-Dev
    objects:
      - {type: ai, name: Temp, value: 20, behavior: {type: random_walk, min: 18, max: 24, step: 0.2}}
      - {type: bi, name: Flag, value: 1}
      - {type: tl, name: Temp_Log, log_object: Temp, log_interval: 60, buffer_size: 5}
      - {type: tl, name: Flag_Log, log_object: Flag, log_interval: 120}
"""

TL1 = ObjectIdentifier("trend-log,1")


def _records(ack: ReadRangeACK):
    return list(ack.itemData.cast_out(ListOf(LogRecord)))


async def _rr(client, addr, rng=None) -> ReadRangeACK:
    req = ReadRangeRequest(objectIdentifier=TL1, propertyIdentifier="log-buffer", destination=addr)
    if rng is not None:
        req.range = rng
    ack = await client.request(req)
    assert isinstance(ack, ReadRangeACK), ack
    return ack


def test_trendlog_readrange():
    asyncio.run(_readrange())


async def _readrange():
    engine = Engine(parse_text(CONFIG))
    await engine.start()
    ip = detect_ip()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194210), objectName="tl-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47911", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    try:
        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47910"), [210])
        iams = await client.who_is(address=Address("210:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2101]

        # static properties
        assert await client.read_property(addr, TL1, "log-interval") == 6000  # hundredths of a second
        assert await client.read_property(addr, TL1, "buffer-size") == 5
        ref = await client.read_property(addr, TL1, "log-device-object-property")
        assert ref.objectIdentifier == ObjectIdentifier("analog-input,1")

        # let the ring wrap (buffer_size 5), then freeze the simulation so the buffer is stable
        for _ in range(50):
            await asyncio.sleep(0.1)
            if engine.trendlog(2101, 1).obj.totalRecordCount > 8:
                break
        engine.set_simulation(running=False)
        await asyncio.sleep(0.2)
        total = await client.read_property(addr, TL1, "total-record-count")
        assert total > 8
        assert await client.read_property(addr, TL1, "record-count") == 5  # oldest records dropped
        assert await client.read_property(addr, ObjectIdentifier("trend-log,2"), "record-count") > 0

        # read all (no range)
        ack = await _rr(client, addr)
        recs = _records(ack)
        assert ack.itemCount == 5 and len(recs) == 5
        assert list(ack.resultFlags) == [1, 1, 0] and ack.firstSequenceNumber is None
        assert all(18 <= r.logDatum.realValue <= 24 for r in recs)
        stamps = [r.timestamp for r in recs]

        # by position: first 3 (bacpypes3 client helper)
        first3 = await client.read_range(addr, TL1, "log-buffer", range_params=("p", 1, None, None, 3))
        assert [r.timestamp for r in first3] == stamps[:3]
        # by position backwards from the newest
        ack = await _rr(client, addr, Range(byPosition=RangeByPosition(referenceIndex=5, count=-2)))
        assert [r.timestamp for r in _records(ack)] == stamps[3:] and list(ack.resultFlags) == [0, 1, 0]

        # by sequence number: the buffer holds total-4 .. total
        ack = await _rr(client, addr, Range(bySequenceNumber=RangeBySequenceNumber(
            referenceSequenceNumber=total - 3, count=2)))
        assert ack.itemCount == 2 and ack.firstSequenceNumber == total - 3
        assert [r.timestamp for r in _records(ack)] == stamps[1:3]
        assert list(ack.resultFlags) == [0, 0, 0]
        # a sequence number that has been overwritten yields nothing
        ack = await _rr(client, addr, Range(bySequenceNumber=RangeBySequenceNumber(
            referenceSequenceNumber=1, count=1)))
        assert ack.itemCount == 0

        # by time: records newer than the 2nd record's timestamp
        ack = await _rr(client, addr, Range(byTime=RangeByTime(referenceTime=stamps[1], count=10)))
        assert [r.timestamp for r in _records(ack)] == stamps[2:]
        assert ack.firstSequenceNumber == total - 2
        ack = await _rr(client, addr, Range(byTime=RangeByTime(referenceTime=stamps[1], count=-10)))
        assert [r.timestamp for r in _records(ack)] == stamps[:1]

        # sim-clock timestamps are log_interval (60 s) apart
        tl = engine.trendlog(2101, 1)
        ts = [d[0] for d in tl.data()]
        assert all(abs((b - a) - 60) < 0.05 for a, b in zip(ts, ts[1:]))

        # disabling stops logging
        engine.set_trendlog_enable(2101, 1, False)
        engine.set_simulation(running=True)
        await asyncio.sleep(0.4)
        assert await client.read_property(addr, TL1, "total-record-count") == total
    finally:
        client.close()
        await engine.stop()


def _prepare(cfg):
    # bacpypes3 objects need an event loop while they are built
    async def run():
        return Engine(cfg)._prepare(cfg)
    return asyncio.run(run())


def test_trendlog_missing_target():
    cfg = parse_text(CONFIG.replace("log_object: Flag,", "log_object: Nope,"))
    with pytest.raises(ValueError, match=r"TL-Dev.*Flag_Log.*'Nope'"):
        _prepare(cfg)
    with pytest.raises(ValueError, match="log_object"):
        parse_text(CONFIG.replace("log_object: Flag, ", ""))


def test_templates_have_trendlogs():
    cfg = parse_text("""
devices:
  - {device_id: 1, name: AC, template: split_ac}
  - {device_id: 2, name: PM, template: power_meter}
""")
    rts = _prepare(cfg)
    assert [tl.target.cfg.name for tl in rts[1].trendlogs] == ["RoomTemp"]
    assert [tl.target.cfg.name for tl in rts[2].trendlogs] == ["ActivePower"]


# COV logging: port 47950 / client 47951, VNET 250
COV_CONFIG = """
network: {ip: auto, port: 47950, virtual_network: 250, router: {device_id: 4194150}}
simulation: {tick_seconds: 0.1, time_scale: 60}
devices:
  - device_id: 2501
    name: COV-Dev
    objects:
      - {type: av, name: Setp, value: 20, cov_increment: 1.0}
      - {type: bv, name: Flag, value: 1}
      - {type: tl, name: Setp_Log, log_object: Setp, logging_type: cov}
      - {type: tl, name: Flag_Log, log_object: Flag, logging_type: cov}
      - {type: tl, name: Setp_Coarse, log_object: Setp, logging_type: cov, client_cov_increment: 5}
"""


def test_trendlog_cov_mode():
    asyncio.run(_cov_mode())


async def _cov_mode():
    from bacpypes3.basetypes import LoggingType

    engine = Engine(parse_text(COV_CONFIG))
    await engine.start()
    ip = detect_ip()
    client = Application.from_object_list([
        DeviceObject(objectIdentifier=("device", 4194250), objectName="tl-cov-client", vendorIdentifier=999,
                     maxApduLengthAccepted=1476, segmentationSupported="segmented-both"),
        NetworkPortObject(f"{ip}:47951", objectIdentifier=("network-port", 1), objectName="ip"),
    ])
    pts = {p.cfg.name: p for p in engine.devices[2501].points}
    setp, flag = pts["Setp"].obj, pts["Flag"].obj
    tl1, tl2, tl3 = (engine.trendlog(2501, i) for i in (1, 2, 3))

    async def step(obj, attr, value):
        setattr(obj, attr, value)
        await asyncio.sleep(0.25)

    try:
        await asyncio.sleep(0.3)
        # the first record is taken as soon as the log runs
        assert [int(t.obj.totalRecordCount) for t in (tl1, tl2, tl3)] == [1, 1, 1]
        await step(setp, "presentValue", 20.5)  # below COV_Increment 1.0: not logged
        assert int(tl1.obj.totalRecordCount) == 1
        await step(setp, "presentValue", 21.2)  # >= 1.0 from the last record (20)
        await step(setp, "presentValue", 26.0)  # >= 5 (Client_COV_Increment) from 20
        await step(flag, "presentValue", "inactive")
        await step(setp, "outOfService", True)  # status flags change without a value change
        await asyncio.sleep(0.25)  # no change: nothing more is logged
        assert [d[1] for d in tl1.data()] == [20.0, 21.2, 26.0, 26.0]
        assert [d[1] for d in tl3.data()] == [20.0, 26.0, 26.0]
        assert [d[1] for d in tl2.data()] == [1.0, 0.0]
        ts = [d[0] for d in tl1.data()]
        assert ts == sorted(ts) and ts[-1] - ts[0] > 30  # simulated clock (time_scale 60)

        await client.nsap.update_router_references(None, Address(f"{ip.split('/')[0]}:47950"), [250])
        iams = await client.who_is(address=Address("250:*"), timeout=2)
        addr = {i.iAmDeviceIdentifier[1]: i.pduSource for i in iams}[2501]
        assert await client.read_property(addr, TL1, "logging-type") == LoggingType.cov
        assert await client.read_property(addr, TL1, "log-interval") == 0
        inc = await client.read_property(addr, ObjectIdentifier("trend-log,3"), "client-cov-increment")
        assert inc.realIncrement == 5
        recs = _records(await _rr(client, addr))
        assert [r.logDatum.realValue for r in recs] == [20.0, pytest.approx(21.2), 26.0, 26.0]
        assert list(recs[2].statusFlags) == [0, 0, 0, 0] and list(recs[3].statusFlags) == [0, 0, 0, 1]
    finally:
        client.close()
        await engine.stop()


def test_trendlog_cov_config_checks():
    with pytest.raises(ValueError, match="client_cov_increment needs logging_type"):
        parse_text(COV_CONFIG.replace("logging_type: cov, client_cov_increment", "client_cov_increment"))
    with pytest.raises(ValueError):
        parse_text(COV_CONFIG.replace("logging_type: cov}", "logging_type: triggered}", 1))
