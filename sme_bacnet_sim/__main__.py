"""Command line entry point: ``python -m sme_bacnet_sim [--config FILE]``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sme_sim_common.cli import add_common_args, run_validate, run_web

from . import __version__
from .config import ForeignDeviceConfig, SimConfig, load_file
from .engine import Engine
from .templates import REGISTRY
from .web import create_app

# Company website contact page (the site's default language, ja, is served at "/").
CONTACT_URL = "https://smartedge-tech.com/contact/"


def print_banner() -> None:
    """Print the one-line startup banner; never fail on consoles that can't encode CJK (cp932/cp936...)."""
    text = f"SME BACnetSim v{__version__} by smart-edge (智届科技) — custom development: {CONTACT_URL}"
    ascii_text = f"SME BACnetSim v{__version__} by smart-edge - custom development: {CONTACT_URL}"
    out = sys.stdout
    if out is None:  # e.g. pythonw: no console at all
        return
    try:
        enc = getattr(out, "encoding", None) or "ascii"
        text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        text = ascii_text
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, OSError):
        try:
            print(ascii_text, flush=True)
        except OSError:
            pass


def apply_cli_overrides(cfg: SimConfig, args: argparse.Namespace) -> None:
    """Command line options win over the config file."""
    if args.ip:
        cfg.network.ip = args.ip
    if args.bacnet_port:
        cfg.network.port = args.bacnet_port
    if args.foreign_bbmd or args.foreign_ttl is not None:
        fd = cfg.network.foreign_device
        if not args.foreign_bbmd and fd is None:
            raise ValueError("--foreign-ttl needs --foreign-bbmd or network.foreign_device in the config")
        bbmd = args.foreign_bbmd or fd.bbmd
        ttl = args.foreign_ttl if args.foreign_ttl is not None else (fd.ttl if fd else 300)
        if cfg.network.mode == "bbmd":
            raise ValueError("--foreign-bbmd cannot be combined with network.mode: bbmd")
        cfg.network.foreign_device = ForeignDeviceConfig(bbmd=bbmd, ttl=ttl)


def load_user_templates(args: argparse.Namespace) -> None:
    """User templates from --templates-dir / the environment variable / ~/.sme-bacnet-sim/templates."""
    for err in REGISTRY.load_user_templates(getattr(args, "templates_dir", None)):
        print(f"template error: {err.get('path')}: {err.get('error')}", file=sys.stderr)


def _check(cfg: SimConfig, path: Path) -> None:
    """``validate``: build the device runtimes once (templates, behaviors, schedules ...) without binding."""
    engine = Engine(cfg, config_path=str(path))
    engine._prepare(cfg)


def main(argv=None) -> int:
    rest = sys.argv[1:] if argv is None else list(argv)
    if rest[:1] == ["clone"]:  # subcommand; without it the options below are unchanged
        from .clone import main as clone_main
        return clone_main(rest[1:])
    if rest[:1] == ["record"]:
        from .record import main as record_main
        return record_main(rest[1:])
    if rest[:1] == ["validate"]:
        return run_validate(rest[1:], prog="sme-bacnet-sim", load=load_file, build=_check,
                            before=load_user_templates, summary=lambda c: f"{len(c.devices)} devices")
    ap = argparse.ArgumentParser(prog="sme-bacnet-sim", description="BACnet/IP device simulator with a web UI")
    # -c/--config (default: configs/demo-building.yaml if present), --host, --http-port (alias --port),
    # --no-browser, --version, -v, --templates-dir
    add_common_args(ap, default_http_port=8080, app_name="sme-bacnet-sim", version=__version__)
    ap.add_argument("--ip", help='BACnet bind address, e.g. "192.168.1.10/24" (overrides config)')
    ap.add_argument("--bacnet-port", type=int, help="BACnet/IP UDP port (overrides config, default 47808)")
    ap.add_argument("--foreign-bbmd", metavar="HOST[:PORT]",
                    help="register as a foreign device with this BBMD (IPv4, default port 47808; overrides config)")
    ap.add_argument("--foreign-ttl", type=int, metavar="SECONDS",
                    help="foreign device Time-to-Live in seconds (default 300; overrides config)")
    args = ap.parse_args(rest)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_user_templates(args)

    path = args.config
    if path is None:
        default = Path(__file__).resolve().parent.parent / "configs" / "demo-building.yaml"
        path = str(default) if default.exists() else None
    try:
        cfg = load_file(path) if path else SimConfig()
        text = Path(path).read_text(encoding="utf-8") if path and not path.lower().endswith(".json") else None
    except Exception as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    before = cfg.network.model_dump()
    try:
        apply_cli_overrides(cfg, args)
    except ValueError as e:
        print(f"argument error: {e}", file=sys.stderr)
        return 2
    if cfg.network.model_dump() != before:
        text = None  # command line overrides: the running config text is re-dumped (comments are lost on save)

    engine = Engine(cfg, config_path=path, config_text=text)
    print_banner()
    run_web(create_app(engine), args, name="SME BACnetSim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
