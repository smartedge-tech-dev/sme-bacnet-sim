"""Foreign device registration of the router port with an external BBMD.

A mock BBMD (plain UDP socket) checks the BVLL Register-Foreign-Device request and answers with a BVLC-Result.
Uses BACnet port 47912 / BBMD port 47910 so it does not clash with a running simulator or other tests.
"""

import argparse
import asyncio

import pytest

from sme_bacnet_sim.__main__ import apply_cli_overrides
from sme_bacnet_sim.config import SimConfig, parse_text
from sme_bacnet_sim.engine import Engine, detect_ip

BBMD_PORT = 47910


def _config(ip: str) -> str:
    return f"""
network:
  ip: auto
  port: 47912
  virtual_network: 210
  router: {{device_id: 4194300}}
  foreign_device: {{bbmd: "{ip}:{BBMD_PORT}", ttl: 60}}
simulation: {{tick_seconds: 0.1}}
devices:
  - {{device_id: 2101, name: AC-1, template: split_ac}}
"""


class MockBBMD(asyncio.DatagramProtocol):
    def __init__(self, result_code: int) -> None:
        self.result_code = result_code
        self.requests: asyncio.Queue = asyncio.Queue()

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if data[:2] == b"\x81\x05" and len(data) == 6:  # BVLL Register-Foreign-Device
            ttl = int.from_bytes(data[4:6], "big")
            self.requests.put_nowait(ttl)
            if ttl:
                self.transport.sendto(b"\x81\x00\x00\x06" + self.result_code.to_bytes(2, "big"), addr)


async def _register(result_code: int):
    ip = detect_ip().split("/")[0]
    loop = asyncio.get_running_loop()
    transport, bbmd = await loop.create_datagram_endpoint(lambda: MockBBMD(result_code), local_addr=(ip, BBMD_PORT))
    engine = Engine(parse_text(_config(ip)))
    await engine.start()
    try:
        assert await asyncio.wait_for(bbmd.requests.get(), 3) == 60
        want = "ok" if result_code == 0 else "nak"
        for _ in range(50):
            if engine.foreign["status"] == want:
                break
            await asyncio.sleep(0.1)
        fd = engine.snapshot()["network"]["foreign_device"]
        assert fd["status"] == want and fd["result_code"] == result_code and fd["bbmd"] == f"{ip}:{BBMD_PORT}"
        assert any(e["kind"] == "foreign" for e in engine.events)
    finally:
        await engine.stop()
    # on stop a registered foreign device deregisters (TTL 0)
    if result_code == 0:
        ttls = []
        while not bbmd.requests.empty():
            ttls.append(bbmd.requests.get_nowait())
        assert 0 in ttls
    transport.close()


def test_foreign_register_ok():
    asyncio.run(_register(0))


def test_foreign_register_nak():
    asyncio.run(_register(0x0030))


def test_foreign_config_and_cli():
    cfg = SimConfig()
    ns = argparse.Namespace(ip=None, bacnet_port=None, foreign_bbmd="10.0.0.5", foreign_ttl=None)
    apply_cli_overrides(cfg, ns)
    assert cfg.network.foreign_device.bbmd == "10.0.0.5:47808" and cfg.network.foreign_device.ttl == 300

    # CLI wins over the config file; TTL alone keeps the configured BBMD
    cfg = parse_text('network: {foreign_device: {bbmd: "10.0.0.6:47809", ttl: 120}}')
    apply_cli_overrides(cfg, argparse.Namespace(ip=None, bacnet_port=None, foreign_bbmd=None, foreign_ttl=30))
    assert cfg.network.foreign_device.bbmd == "10.0.0.6:47809" and cfg.network.foreign_device.ttl == 30

    with pytest.raises(ValueError):
        parse_text('network: {mode: bbmd, foreign_device: {bbmd: "10.0.0.6"}}')
    with pytest.raises(ValueError):
        parse_text('network: {foreign_device: {bbmd: "bbmd.example"}}')
    with pytest.raises(ValueError):
        apply_cli_overrides(SimConfig(), argparse.Namespace(ip=None, bacnet_port=None, foreign_bbmd=None,
                                                            foreign_ttl=30))
