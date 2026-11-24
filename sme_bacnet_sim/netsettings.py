"""BACnet network settings from the web UI (#6): local IPv4 interfaces, validation, live apply and write-back.

Applying reuses ``Engine.reload()``, which tears the BACnet stack down and binds it again with the new
``network`` section, so no process restart is needed. Only the top-level ``network:`` block of the config file
is rewritten; other (possibly unsaved) changes held in memory are not written.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from .config import NetworkConfig, SimConfig

# ---------------------------------------------------------------- interfaces


def _windows_interfaces() -> List[Dict[str, Any]]:
    """IPv4 addresses from PowerShell Get-NetIPAddress (locale independent; UTF-8 so adapter names survive)."""
    cmd = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
           "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' } | "
           "ForEach-Object { \"{0}`t{1}`t{2}\" -f $_.InterfaceAlias, $_.IPAddress, $_.PrefixLength }")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                         timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    items = []
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.strip().split("\t")
        if len(parts) == 3 and parts[2].isdigit():
            items.append({"name": parts[0], "ip": parts[1], "prefix": int(parts[2])})
    return items


def _linux_interfaces() -> List[Dict[str, Any]]:
    """Primary IPv4 address of every Linux interface (SIOCGIFADDR / SIOCGIFNETMASK)."""
    import fcntl
    import struct

    items = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            req = struct.pack("256s", name.encode()[:15])
            try:
                ip = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, req)[20:24])  # SIOCGIFADDR
                mask = fcntl.ioctl(s.fileno(), 0x891B, req)[20:24]  # SIOCGIFNETMASK
            except OSError:
                continue  # no IPv4 address
            items.append({"name": name, "ip": ip, "prefix": bin(int.from_bytes(mask, "big")).count("1")})
    finally:
        s.close()
    return items


def parse_ifconfig(text: str) -> List[Dict[str, Any]]:
    """IPv4 addresses with interface names from macOS / BSD ``ifconfig -a`` output."""
    items, name = [], None
    for line in text.splitlines():
        m = re.match(r"^([^\s:]+):", line)
        if m:
            name = m.group(1)
            continue
        m = re.search(r"\binet (?:addr:)?(\d+\.\d+\.\d+\.\d+)\S*\s+(?:-->\s*\S+\s+)?netmask\s+(\S+)", line)
        if not m or name is None:
            continue
        mask = m.group(2)
        try:
            value = int(mask, 16) if mask.lower().startswith("0x") else int.from_bytes(socket.inet_aton(mask), "big")
        except (ValueError, OSError):
            continue
        bits = f"{value:032b}"
        if "01" not in bits:  # contiguous masks only
            items.append({"name": name, "ip": m.group(1), "prefix": bits.count("1")})
    return items


def _bsd_interfaces() -> List[Dict[str, Any]]:
    for exe in ("/sbin/ifconfig", "ifconfig"):
        try:
            out = subprocess.run([exe, "-a"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        return parse_ifconfig(out)
    return []


def list_interfaces() -> List[Dict[str, Any]]:
    """Local IPv4 interfaces: ``[{name, ip, prefix, address: "ip/prefix"}]``, LAN addresses first, loopback last.

    Best effort: an empty list means the platform could not be queried (the UI then only offers "auto" and the
    address that is configured now)."""
    try:
        if sys.platform == "win32":
            items = _windows_interfaces()
        elif sys.platform.startswith("linux"):
            items = _linux_interfaces()
        else:
            items = _bsd_interfaces()
    except Exception:  # pragma: no cover - sandboxes without PowerShell / ioctl
        items = []
    seen, result = set(), []
    for it in items:
        if it["ip"] in seen:
            continue
        seen.add(it["ip"])
        result.append({**it, "address": f"{it['ip']}/{it['prefix']}"})

    def rank(it: Dict[str, Any]) -> int:
        a = ipaddress.IPv4Address(it["ip"])
        return 2 if a.is_loopback else 1 if a.is_link_local else 0

    return sorted(result, key=rank)


# ---------------------------------------------------------------- validation / apply


def _host(ip: str) -> str:
    return ip.split("/")[0]


def check_ip(ip: str, interfaces: List[Dict[str, Any]]) -> None:
    """``auto`` or ``<ipv4>[/prefix]`` of a local interface (not checked when the interfaces are unknown)."""
    if ip == "auto":
        return
    try:
        ipaddress.IPv4Interface(ip)
    except ValueError:
        raise ValueError(f"network.ip: {ip!r} is not 'auto' or '<ipv4>[/prefix]'") from None
    if interfaces and _host(ip) not in {it["ip"] for it in interfaces}:
        raise ValueError(f"network.ip: {_host(ip)} is not an address of this computer")


def check_port_free(ip: str, port: int) -> None:
    """Try to bind the BACnet/IP UDP port; raises ValueError when another program holds it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((_host(ip), port))
    except OSError as e:
        raise ValueError(f"network.port: UDP {_host(ip)}:{port} is in use or cannot be bound ({e.strerror or e})") \
            from None
    finally:
        s.close()


def network_view(engine: Any) -> Dict[str, Any]:
    return {"network": engine.config.network.model_dump(exclude_none=True), "bind": engine.bind_address,
            "config_path": engine.config_path}


async def apply_network(engine: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a new ``network`` section, rebind the BACnet stack with it and write it back to the config file.

    Returns ``{"ok", "bind", "saved": path | None, "save_error": str | None}``; raises ValueError /
    pydantic.ValidationError when the settings are rejected (nothing is changed then)."""
    from .engine import detect_ip, with_prefix

    net = NetworkConfig.model_validate(data)
    cfg = SimConfig.model_validate({**engine.config.model_dump(exclude_none=True),
                                    "network": net.model_dump(exclude_none=True)})
    if net.ip != "auto":
        check_ip(net.ip, await asyncio.to_thread(list_interfaces))
    new_ip = _host(detect_ip() if net.ip == "auto" else with_prefix(net.ip))
    cur_ip, _, cur_port = engine.bind_address.rpartition(":")
    if (new_ip, str(net.port)) != (_host(cur_ip), cur_port):  # our own socket holds the current address
        check_port_free(new_ip, net.port)
    await engine.reload(cfg)
    saved, save_error = None, None
    if engine.config_path:
        try:
            write_network_section(engine.config_path, cfg.network)
            saved = engine.config_path
        except (OSError, ValueError, yaml.YAMLError) as e:
            save_error = str(e)
    engine.log_event("config", f"network settings applied ({engine.bind_address})"
                     + (f", saved to {saved}" if saved else f", not saved: {save_error}" if save_error else ""))
    return {"ok": True, "bind": engine.bind_address, "saved": saved, "save_error": save_error}


# ---------------------------------------------------------------- write-back


def replace_yaml_block(text: str, key: str, block: str) -> str:
    """Replace the top-level ``key:`` block of a YAML document (or insert it after the leading comments).

    Indented lines and comments inside the block are replaced; column-0 comments / blank lines right before the
    next top-level key are left to that key."""
    if not block.endswith("\n"):
        block += "\n"
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(key)}\s*:", ln)), None)
    if start is None:
        i = 0
        while i < len(lines) and (not lines[i].strip() or lines[i].startswith("#")):
            i += 1
        return "".join(lines[:i]) + block + ("\n" if i < len(lines) else "") + "".join(lines[i:])
    end = start + 1
    while end < len(lines) and not re.match(r"[^\s#]", lines[end]):
        end += 1
    if end < len(lines):  # keep the comment header of the next section
        while end - 1 > start and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
            end -= 1
    return "".join(lines[:start]) + block + "".join(lines[end:])


def write_network_section(path: Union[str, Path], net: NetworkConfig) -> None:
    """Write ``net`` as the ``network`` section of a YAML / JSON config file, keeping everything else."""
    p = Path(path)
    data = net.model_dump(exclude_none=True)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if p.suffix.lower() == ".json":
        doc = json.loads(text) if text.strip() else {}
        doc["network"] = data
        p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    old: Optional[Dict[str, Any]] = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(old, dict):
        raise ValueError(f"{p}: not a YAML mapping")
    want = {**old, "network": data}
    new = replace_yaml_block(text, "network",
                             yaml.safe_dump({"network": data}, allow_unicode=True, sort_keys=False))
    try:
        ok = yaml.safe_load(new) == want
    except yaml.YAMLError:
        ok = False
    if not ok:  # unusual layout (e.g. anchors, flow style at top level): rewrite the document without comments
        new = yaml.safe_dump(want, allow_unicode=True, sort_keys=False)
    p.write_text(new, encoding="utf-8")
