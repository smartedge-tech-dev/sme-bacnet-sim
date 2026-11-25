"""BACnet network settings from the UI (#6): validation, live rebind and write-back of the network section.

Uses BACnet ports 47940-47943 and virtual network 240 so it does not clash with a running simulator or other tests.
"""

import asyncio
import json
import socket

import pytest
import yaml
from pydantic import ValidationError

from sme_bacnet_sim.config import NetworkConfig, load_file
from sme_bacnet_sim.engine import Engine, detect_ip
from sme_bacnet_sim.netsettings import (apply_network, check_ip, check_port_free, list_interfaces, parse_ifconfig,
                                        write_network_section)

CONFIG = """\
# header comment
network:
  ip: auto              # pick the NIC
  port: 47940
  virtual_network: 240
  router: {device_id: 4194240}

# simulation section
simulation: {tick_seconds: 0.1}   # fast
devices:
  - {device_id: 2401, name: AC-1, template: split_ac}
"""




def test_write_network_section_yaml_and_json(tmp_path):
    net = NetworkConfig(ip="10.0.0.5/16", port=47999, network_number=7, virtual_network=8, mode="bbmd")
    p = tmp_path / "c.yaml"
    p.write_text(CONFIG, encoding="utf-8")
    write_network_section(p, net)
    text = p.read_text(encoding="utf-8")
    assert "# simulation section" in text and "# header comment" in text
    cfg = load_file(p)
    assert cfg.network == net and cfg.devices[0].name == "AC-1" and cfg.simulation.tick_seconds == 0.1

    j = tmp_path / "c.json"
    j.write_text(json.dumps({"devices": [], "network": {"port": 1}}), encoding="utf-8")
    write_network_section(j, net)
    doc = json.loads(j.read_text(encoding="utf-8"))
    assert doc["network"]["port"] == 47999 and doc["devices"] == []


def test_write_network_section_unusual_layout_falls_back(tmp_path):
    p = tmp_path / "flow.yaml"
    p.write_text("{network: {port: 1}, devices: []}\n", encoding="utf-8")
    write_network_section(p, NetworkConfig(port=2))
    assert yaml.safe_load(p.read_text(encoding="utf-8")) == {"network": NetworkConfig(port=2).model_dump(
        exclude_none=True), "devices": []}


def test_parse_ifconfig():
    out = ("lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n"
           "en0: flags=8863<UP,BROADCAST> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n"
           "\tinet 192.168.10.23 netmask 0xffff0000 broadcast 192.168.255.255\n"
           "utun3: flags=8051<UP,POINTOPOINT> mtu 1380\n\tinet 10.8.0.2 --> 10.8.0.1 netmask 0xffffff00\n")
    assert parse_ifconfig(out) == [{"name": "lo0", "ip": "127.0.0.1", "prefix": 8},
                                   {"name": "en0", "ip": "192.168.10.23", "prefix": 16},
                                   {"name": "utun3", "ip": "10.8.0.2", "prefix": 24}]


def test_list_interfaces_contains_detected_ip():
    items = list_interfaces()
    if not items:
        pytest.skip("interfaces cannot be listed on this platform")
    assert all(it["address"] == f"{it['ip']}/{it['prefix']}" for it in items)
    ip = detect_ip().split("/")[0]
    if ip != "127.0.0.1":
        assert ip in {it["ip"] for it in items}


def test_check_ip():
    ifs = [{"name": "eth0", "ip": "192.168.1.10", "prefix": 24}]
    check_ip("auto", ifs)
    check_ip("192.168.1.10/24", ifs)
    check_ip("192.168.1.10", ifs)
    check_ip("10.1.1.1/8", [])  # interfaces unknown: not checked
    with pytest.raises(ValueError, match="not an address of this computer"):
        check_ip("192.168.1.11/24", ifs)
    with pytest.raises(ValueError, match="not 'auto'"):
        check_ip("eth0", ifs)


def test_check_port_free():
    ip = detect_ip().split("/")[0]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((ip, 47943))
    try:
        with pytest.raises(ValueError, match="in use"):
            check_port_free(ip, 47943)
    finally:
        s.close()
    check_port_free(ip, 47943)


def _net(engine: Engine, **kw):
    return {**engine.config.network.model_dump(exclude_none=True), **kw}


def test_apply_network_rebinds_and_saves(tmp_path):
    asyncio.run(_rebind_and_save(tmp_path))


async def _rebind_and_save(tmp_path):
    path = tmp_path / "sim.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    engine = Engine(load_file(path), config_path=str(path))
    await engine.start()
    try:
        assert engine.bind_address.endswith(":47940")
        # rejected settings change nothing
        with pytest.raises(ValidationError):
            await apply_network(engine, _net(engine, network_number=240))
        with pytest.raises(ValidationError):
            await apply_network(engine, _net(engine, router={"device_id": 2401}))  # clashes with a device
        with pytest.raises(ValueError, match="not an address"):
            await apply_network(engine, _net(engine, ip="203.0.113.77/24"))
        ip = detect_ip().split("/")[0]
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind((ip, 47942))
        try:
            with pytest.raises(ValueError, match="in use"):
                await apply_network(engine, _net(engine, port=47942))
        finally:
            blocker.close()
        assert engine.bind_address.endswith(":47940") and path.read_text(encoding="utf-8") == CONFIG

        # unchanged address: our own socket is not reported as "in use"
        res = await apply_network(engine, _net(engine, mode="bbmd"))
        assert res["saved"] == str(path) and engine.config.network.mode == "bbmd"

        res = await apply_network(engine, _net(engine, port=47941, network_number=5, mode="normal",
                                               foreign_device={"bbmd": f"{ip}:47808", "ttl": 120}))
        assert res["ok"] and engine.bind_address.endswith(":47941")
        start = [e["message"] for e in engine.events if e["kind"] == "start"]
        assert "BBMD)" in start[-2] and f"network 5, foreign device of BBMD {ip}:47808 (TTL 120 s)" in start[-1]
        saved = load_file(path)
        assert saved.network.port == 47941 and saved.network.network_number == 5
        assert saved.network.foreign_device.ttl == 120 and saved.devices[0].name == "AC-1"
        assert "# simulation section" in path.read_text(encoding="utf-8")
    finally:
        await engine.stop()


def test_apply_network_without_config_file():
    asyncio.run(_without_config_file())


async def _without_config_file():
    engine = Engine(load_file_text(CONFIG))
    await engine.start()
    try:
        res = await apply_network(engine, _net(engine, port=47941))
        assert res["saved"] is None and res["save_error"] is None and engine.bind_address.endswith(":47941")
    finally:
        await engine.stop()


def load_file_text(text: str):
    from sme_bacnet_sim.config import parse_text
    return parse_text(text)
