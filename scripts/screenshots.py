"""Regenerate the README / docs screenshots.

Starts the simulator on the demo config (slightly tuned so the curves move), drives the web UI with
Playwright and writes PNGs (plus one animated GIF) to docs/assets/screenshots/<lang>/.

Dev-only tool, not a runtime dependency:

    pip install playwright pillow
    python -m playwright install chromium
    python scripts/screenshots.py            # all languages
    python scripts/screenshots.py --lang en  # one language
"""

from __future__ import annotations

import argparse
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml
from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "screenshots"
LANGS = ("en", "ja", "zh")
VIEWPORT = {"width": 1440, "height": 860}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


HTTP_PORT = free_port()
# Loopback bind: the status bar shows the bind address, and screenshots must not show a LAN address.
BACNET_IP = "127.0.0.1/8"
BACNET_PORT = 47808


def demo_config(tmp: Path) -> Path:
    """The demo building, with a faster clock and the east AC switched on so its room cools down."""
    cfg = yaml.safe_load((ROOT / "configs" / "demo-building.yaml").read_text(encoding="utf-8"))
    cfg["simulation"].update({"tick_seconds": 0.5, "time_scale": 120})
    for dev in cfg["devices"]:
        if dev["device_id"] == 1002:
            dev.setdefault("objects", []).append({"name": "OnOff", "type": "bo", "value": 1})
        if dev["device_id"] == 1100:
            next(o for o in dev["objects"] if o["name"] == "PumpCmd")["value"] = 1
        for o in dev.get("objects", []):
            if o.get("name") == "RoomTempWatch":  # tighter band so the alarm list has something to show
                o.update(description="Room temperature outside 18-22 degC", time_delay=0,
                         event_parameters={"low_limit": 18, "high_limit": 22, "deadband": 0.5})
    path = tmp / "demo-building.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def start_sim(config: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        # relative config path: the network dialog shows it, and a temp path would leak the user name
        [sys.executable, "-m", "sme_bacnet_sim", "-c", config.name, "--http-port", str(HTTP_PORT),
         "--ip", BACNET_IP, "--bacnet-port", str(BACNET_PORT), "--host", "127.0.0.1", "--no-browser"],
        cwd=config.parent, env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{HTTP_PORT}/", timeout=1)
            return proc
        except OSError:
            if proc.poll() is not None:
                raise SystemExit("simulator exited during startup")
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("simulator did not come up")


def open_ui(page: Page, lang: str, theme: str = "light") -> None:
    page.add_init_script(
        f"localStorage.setItem('sme-bacnet-sim.lang', '{lang}');"
        f"localStorage.setItem('sme-bacnet-sim.theme', '{theme}');")
    page.goto(f"http://127.0.0.1:{HTTP_PORT}/")
    page.wait_for_selector("#devList li")
    page.wait_for_timeout(800)


def select(page: Page, device_id: int) -> None:
    page.evaluate(f"selectDevice({device_id})")
    page.wait_for_timeout(600)


def point_row(page: Page, name: str):
    return page.locator("#points tr").filter(has=page.locator(f"td:text-is('{name}')")).first


def close_dialogs(page: Page) -> None:
    page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")


def shoot(page: Page, lang: str, name: str, locator=None) -> None:
    path = OUT / lang / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    (locator or page).screenshot(path=str(path))
    print("wrote", path.relative_to(ROOT))


def gif(page: Page, lang: str, name: str, frames: int = 16, interval_ms: int = 500) -> None:
    """Live-values animation: the point table and trend chart updating, downscaled to keep the file small."""
    images = []
    for _ in range(frames):
        img = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
        img = img.resize((img.width * 2 // 3, img.height * 2 // 3), Image.LANCZOS)
        images.append(img.quantize(colors=128, method=Image.MEDIANCUT))
        page.wait_for_timeout(interval_ms)
    path = OUT / lang / f"{name}.gif"
    images[0].save(path, save_all=True, append_images=images[1:], duration=interval_ms, loop=0, optimize=True)
    print("wrote", path.relative_to(ROOT), f"{path.stat().st_size // 1024} KiB")


def run_lang(browser, lang: str) -> None:
    page = browser.new_page(viewport=VIEWPORT)
    open_ui(page, lang)

    # 1. overview: device list, live points, trend chart of a cooling room
    select(page, 1002)
    point_row(page, "RoomTemp").click()
    page.wait_for_timeout(1500)
    shoot(page, lang, "overview")
    gif(page, lang, "live")

    # 2. a richer device: event enrollment in alarm, notification class, life safety
    select(page, 1006)
    point_row(page, "Temperature").click()
    page.wait_for_timeout(1500)
    shoot(page, lang, "objects")

    # 3. a device built from scratch (expression and follow behaviors)
    select(page, 1100)
    point_row(page, "Flow").click()
    page.wait_for_timeout(1500)
    shoot(page, lang, "custom-device")

    # 4. property inspector
    page.evaluate("openProps(1002, 'device:1002', 'AC-1F-East')")
    page.wait_for_selector("#propsBody tr", state="attached")
    page.wait_for_timeout(500)
    shoot(page, lang, "properties")
    close_dialogs(page)

    # 5. alarm list
    page.evaluate("openAlarms()")
    page.wait_for_timeout(600)
    shoot(page, lang, "alarms")
    close_dialogs(page)

    # 6. network settings
    page.evaluate("openNetwork()")
    page.wait_for_selector("#netIp option", state="attached")
    page.wait_for_timeout(400)
    shoot(page, lang, "network")
    close_dialogs(page)
    page.close()

    if lang == "ja":  # wide shot for the company website's open-source page
        page = browser.new_page(viewport={"width": 1600, "height": 960})
        open_ui(page, lang)
        select(page, 1002)
        point_row(page, "RoomTemp").click()
        page.wait_for_timeout(1500)
        shoot(page, lang, "overview-wide")
        page.close()

    if lang == "en":
        page = browser.new_page(viewport=VIEWPORT, color_scheme="dark")
        open_ui(page, lang, theme="dark")
        select(page, 1002)
        point_row(page, "RoomTemp").click()
        page.wait_for_timeout(1500)
        shoot(page, lang, "overview-dark")
        page.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", choices=LANGS, action="append")
    ap.add_argument("--warmup", type=float, default=20, help="seconds of simulation before the first shot")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        proc = start_sim(demo_config(Path(tmp)))
        try:
            time.sleep(args.warmup)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for lang in args.lang or LANGS:
                    run_lang(browser, lang)
                browser.close()
        finally:
            proc.terminate()
            proc.wait(10)


if __name__ == "__main__":
    main()
