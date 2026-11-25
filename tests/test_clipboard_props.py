"""Web API: device duplicate, object copy / paste (reference handling) and the generic property grid.

Calls the FastAPI endpoint functions directly (no HTTP client needed). BACnet port 47996.
"""

import asyncio

import pytest
from fastapi import HTTPException

from sme_bacnet_sim.config import parse_text
from sme_bacnet_sim.engine import Engine
from sme_bacnet_sim.web import PasteReq, WriteReq, create_app

CONFIG = """
network: {ip: auto, port: 47996, virtual_network: 296, router: {device_id: 4194196}}
simulation: {tick_seconds: 0.1, running: false}
devices:
  - device_id: 2961
    name: Src-Dev
    objects:
      - {type: nc, name: NC1, instance: 1}
      - {type: ai, name: Temp, units: degrees-celsius, value: 21}
      - {type: ao, name: Valve, units: percent, min: 0, max: 100}
      - {type: av, name: Limit, value: 20, alarm: {notification_class: NC1, high_limit: 30}}
      - {type: loop, name: TempLoop, controlled_object: Temp, manipulated_object: Valve, setpoint: 22,
         proportional_constant: 5, min: 0, max: 100, units: percent}
      - {type: trend-log, name: TempLog, log_object: Temp, log_interval: 10}
  - device_id: 2962
    name: Other-Dev
    objects:
      - {type: ai, name: Temp, value: 5}
"""


def _routes(app):
    """All routes, including those of included routers (FastAPI >= 0.16x nests them in ``_IncludedRouter``)."""
    for r in app.routes:
        sub = getattr(r, "original_router", None)
        yield from (sub.routes if sub is not None else [r])


def _ep(app, method, path):
    for r in _routes(app):
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r.endpoint
    raise LookupError(path)


async def _status(coro) -> int:
    try:
        await coro
    except HTTPException as e:
        return e.status_code
    return 200


def _objs(engine, device_id):
    dev = next(d for d in engine.config.devices if d.device_id == device_id)
    return {o.name: o for o in dev.objects}


async def _flow():
    engine = Engine(parse_text(CONFIG))
    app = create_app(engine)
    await engine.start()
    try:
        P = "/api/devices/{device_id}"
        dup = _ep(app, "POST", P + "/duplicate")
        cfg = _ep(app, "GET", P + "/objects/config")
        paste = _ep(app, "POST", P + "/objects/paste")
        props = _ep(app, "GET", P + "/objects/{key}/properties")
        put = _ep(app, "PUT", P + "/objects/{key}/properties/{prop}")

        # ---- duplicate device: next free id (2962 is taken), "(copy)" name, same objects
        r = await dup(2961)
        assert r["device_id"] == 2963 and r["name"] == "Src-Dev (copy)"
        assert 2963 in engine.devices and len(engine.devices[2963].points) == len(engine.devices[2961].points)
        assert (await dup(2961))["name"] == "Src-Dev (copy 2)"
        assert await _status(dup(9999)) == 404

        # ---- copy objects
        loop_cfg, temp_cfg = await cfg(2961, keys="loop:1,analog-input:1")
        assert loop_cfg["name"] == "TempLoop" and temp_cfg["name"] == "Temp"
        assert await _status(cfg(2961, keys="analog-input:9")) == 404

        # same device, loop alone: keeps its references
        r = await paste(2961, PasteReq(objects=[loop_cfg]))
        assert r["pasted"] == [{"name": "TempLoop (copy)", "key": "loop:2"}] and not r["rejected"]
        assert _objs(engine, 2961)["TempLoop (copy)"].controlled_object == "Temp"
        # same device, loop with its input: the copy follows the pasted input
        r = await paste(2961, PasteReq(objects=[temp_cfg, loop_cfg]))
        assert [p["name"] for p in r["pasted"]] == ["Temp (copy)", "TempLoop (copy 2)"]
        assert r["pasted"][0]["key"] == "analog-input:2"
        assert _objs(engine, 2961)["TempLoop (copy 2)"].controlled_object == "Temp (copy)"
        assert "analog-input:2" in engine.devices[2961].by_key

        # other device: trend log of Temp resolves there, the loop (Valve) and the alarmed AV (NC1) do not
        objs = await cfg(2961, keys="trend-log:1,loop:1,analog-value:1")
        r = await paste(2962, PasteReq(objects=objs))
        assert [p["name"] for p in r["pasted"]] == ["TempLog"]
        assert {x["name"] for x in r["rejected"]} == {"TempLoop", "Limit"}
        assert any("Valve" in x["reason"] for x in r["rejected"])
        assert _objs(engine, 2962)["TempLog"].log_object == "Temp"
        assert any("rejected" in e["message"] for e in engine.events)
        # with its notification class the alarmed AV is accepted and points at the pasted NC
        objs = await cfg(2961, keys="notification-class:1,analog-value:1")
        r = await paste(2962, PasteReq(objects=objs))
        assert not r["rejected"] and _objs(engine, 2962)["Limit"].alarm.notification_class == "NC1"

        # ---- property grid
        lst = await props(2961, "analog-value:1")
        by = {p["name"]: p for p in lst}
        assert [p["id"] for p in lst] == sorted(p["id"] for p in lst)
        assert by["present-value"]["value"] == 20 and by["present-value"]["editable"] and by["present-value"]["kind"] == "real"
        assert not by["object-identifier"]["writable"] and not by["acked-transitions"]["writable"]
        assert by["event-state"]["kind"] == "enumerated" and "normal" in by["event-state"]["choices"]
        dev_props = {p["name"]: p for p in await props(2961, "device:2961")}
        assert dev_props["object-name"]["value"] == "Src-Dev"
        assert await _status(props(2961, "analog-value:99")) == 404

        assert await _status(put(2961, "analog-value:1", "description", WriteReq(value="hello"))) == 200
        assert str(engine.devices[2961].by_key["analog-value:1"].obj.description) == "hello"
        assert await _status(put(2961, "analog-output:1", "present-value", WriteReq(value=40, priority=5))) == 200
        ao = engine.devices[2961].by_key["analog-output:1"].obj
        assert float(ao.presentValue) == 40 and ao.currentCommandPriority.unsigned == 5
        assert await _status(put(2961, "analog-output:1", "present-value", WriteReq(value=None, priority=5))) == 200
        assert await _status(put(2961, "analog-value:1", "out-of-service", WriteReq(value=True))) == 200
        assert bool(engine.devices[2961].by_key["analog-value:1"].obj.outOfService)

        # read-only / constructed / rejected by the simulator's WriteProperty checks
        assert await _status(put(2961, "analog-value:1", "object-identifier", WriteReq(value="x"))) == 400
        assert await _status(put(2961, "analog-output:1", "priority-array", WriteReq(value=1))) == 400
        assert await _status(put(2961, "analog-value:1", "acked-transitions", WriteReq(value=1))) == 400
        assert await _status(put(2961, "analog-value:1", "notification-class", WriteReq(value=99))) == 400
        assert await _status(put(2961, "analog-value:1", "no-such-prop", WriteReq(value=1))) == 404
    finally:
        await engine.stop()


def test_clipboard_and_properties():
    asyncio.run(_flow())
