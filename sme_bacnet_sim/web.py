"""Web UI and REST/WebSocket API: the sme-sim-common standard app plus the BACnet routes.

sme-sim-common (``make_base_app``) serves ``/``, ``/static``, ``/sme-sim-common``, ``/api/version``, ``/api/state``,
``GET|PUT /api/config`` (YAML text), ``/api/config/save``, the xlsx routes (``/api/config/xlsx``,
``/api/config/xlsx-template``, ``/api/config/import``), ``/api/simulation``, the device-template routes, the
device routes (``POST /api/devices``, ``.../duplicate``, ``DELETE``, ``GET|PUT .../config``, keyed by the integer
``device_id``) and ``/ws``. This module supplies the BACnet hooks (free device ids, ``set_time``, EDE / YAML / JSON
import) and adds the BACnet routes through an ``APIRouter``.
"""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sme_sim_common.web import make_base_app

from . import __version__
from .clipboard import duplicate_hook, paste_objects
from .config import DeviceConfig, SimConfig, dump_yaml, parse_text
from .ede import export_ede_zip, import_ede_files
from .engine import Engine
from .netsettings import apply_network, list_interfaces, network_view
from .templates import REGISTRY, expand_device
from .xlsx import SCHEMA

STATIC = Path(__file__).parent / "static"


class WriteReq(BaseModel):
    value: Any
    priority: Optional[int] = None


class RelinquishReq(BaseModel):
    priority: Optional[int] = None


class OosReq(BaseModel):
    out_of_service: bool


class EnableReq(BaseModel):
    enabled: bool


class ProgramReq(BaseModel):
    request: Literal["ready", "load", "run", "halt", "restart", "unload"]


class PasteReq(BaseModel):
    objects: List[Dict[str, Any]]  # object configs as returned by GET /api/devices/{id}/objects/config


class DccReq(BaseModel):
    state: str  # enable / disable / disable-initiation


class TextMessageReq(BaseModel):
    message: str
    address: Optional[str] = None  # "<net>:<mac>" / "<ip>:<port>" ...; default: global broadcast
    priority: Literal["normal", "urgent"] = "normal"
    message_class: Optional[Union[int, str]] = None
    confirmed: bool = False


class LifeSafetyReq(BaseModel):
    state: str  # BACnetLifeSafetyState, e.g. quiet / alarm / pre-alarm / fault


def _bad(e: Exception) -> HTTPException:
    if isinstance(e, ValidationError):
        parts = []
        for err in e.errors():
            loc, text = ".".join(str(x) for x in err["loc"]), str(err["msg"]).removeprefix("Value error, ")
            parts.append(f"{loc}: {text}" if loc else text)
        msg = "; ".join(parts)
    else:
        msg = str(e)
    return HTTPException(status_code=400, detail=msg)


def bacnet_router(engine: Engine) -> APIRouter:
    """The BACnet-specific routes."""
    r = APIRouter()

    async def apply(cfg: SimConfig) -> Dict[str, Any]:
        try:
            await engine.reload(cfg)
        except (ValueError, ValidationError) as e:
            raise _bad(e)
        return {"ok": True}

    def cfg_copy() -> Dict[str, Any]:
        return engine.config.model_dump(exclude_none=True)

    def device_cfg(device_id: int) -> DeviceConfig:
        dev = next((d for d in engine.config.devices if d.device_id == device_id), None)
        if dev is None:
            raise HTTPException(404, "device not found")
        return dev

    # ---- state

    @r.get("/api/history/{device_id}/{key}")
    async def history(device_id: int, key: str):
        try:
            return engine.history(device_id, key)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @r.get("/api/devices/{device_id}/trendlog/{instance}")
    async def trendlog(device_id: int, instance: int):
        """Logged buffer of a trend log as [[timestamp (simulated clock, epoch s), value], ...]."""
        try:
            return engine.trendlog(device_id, instance).data()
        except KeyError as e:
            raise HTTPException(404, str(e))

    @r.post("/api/devices/{device_id}/trendlog/{instance}/enable")
    async def trendlog_enable(device_id: int, instance: int, req: EnableReq):
        try:
            engine.set_trendlog_enable(device_id, instance, req.enabled)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @r.post("/api/devices/{device_id}/program/{instance}/change")
    async def program_change(device_id: int, instance: int, req: ProgramReq):
        async with engine._lock:
            try:
                engine.program_change(device_id, instance, req.request)
            except KeyError as e:
                raise HTTPException(404, str(e))
        return {"ok": True}

    @r.post("/api/devices/{device_id}/text-message")
    async def text_message(device_id: int, req: TextMessageReq):
        try:
            dest = await engine.send_text_message(device_id, req.message, req.address, req.priority,
                                                  req.message_class, req.confirmed)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")
        return {"ok": True, "destination": dest}

    @r.post("/api/devices/{device_id}/life-safety/{key}/state")
    async def life_safety_state(device_id: int, key: str, req: LifeSafetyReq):
        from bacpypes3.basetypes import LifeSafetyState
        try:
            state = str(LifeSafetyState(req.state))
            if state.isdigit():
                raise ValueError(f"unknown state {req.state!r}")
        except Exception as e:
            raise HTTPException(400, str(e))
        async with engine._lock:
            try:
                engine.set_life_safety(device_id, key, state)
            except KeyError as e:
                raise HTTPException(404, str(e))
            except ValueError as e:
                raise HTTPException(400, str(e))
        return {"ok": True}

    # ---- point operations

    @r.post("/api/devices/{device_id}/objects/{key}/write")
    async def write(device_id: int, key: str, req: WriteReq):
        try:
            await engine.write(device_id, key, req.value, req.priority)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise _bad(e)
        return {"ok": True}

    @r.post("/api/devices/{device_id}/objects/{key}/relinquish")
    async def relinquish(device_id: int, key: str, req: RelinquishReq):
        try:
            await engine.relinquish(device_id, key, req.priority)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise _bad(e)
        return {"ok": True}

    @r.post("/api/devices/{device_id}/objects/{key}/oos")
    async def oos(device_id: int, key: str, req: OosReq):
        try:
            engine.set_oos(device_id, key, req.out_of_service)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @r.get("/api/devices/{device_id}/objects/{key}/properties")
    async def get_properties(device_id: int, key: str):
        """All properties of an object (key ``type:instance``; ``device:<id>`` for the device object)."""
        try:
            return engine.properties(device_id, key)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @r.put("/api/devices/{device_id}/objects/{key}/properties/{prop}")
    async def put_property(device_id: int, key: str, prop: str, req: WriteReq):
        """Write one basic-typed property through the same path as a BACnet WriteProperty."""
        async with engine._lock:
            try:
                await engine.write_property(device_id, key, prop, req.value, req.priority)
            except KeyError as e:
                raise HTTPException(404, str(e))
            except Exception as e:
                raise _bad(e)
        return {"ok": True}

    @r.post("/api/devices/{device_id}/objects/{key}/ack")
    async def acknowledge(device_id: int, key: str):
        try:
            engine.acknowledge(device_id, key)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise _bad(e)
        return {"ok": True}

    @r.post("/api/devices/{device_id}/dcc")
    async def dcc(device_id: int, req: DccReq):
        try:
            engine.set_dcc(device_id, req.state)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise _bad(e)
        return {"ok": True}

    # ---- configuration (GET|PUT /api/config, save and the xlsx routes are sme-sim-common's)

    @r.get("/api/config/export")
    async def export(format: str = "yaml"):
        if format == "json":
            body, mt, ext = engine.config.model_dump_json(indent=2, exclude_none=True), "application/json", "json"
        elif format == "ede":
            try:
                body = export_ede_zip(engine.config)
            except ValueError as e:
                raise _bad(e)
            mt, ext = "application/zip", "ede.zip"
        elif format == "yaml":
            body, mt, ext = dump_yaml(engine.config), "application/x-yaml", "yaml"
        else:
            raise HTTPException(400, f"unknown format {format!r} (yaml, json, ede; Excel: GET /api/config/xlsx)")
        return Response(body, media_type=mt,
                        headers={"Content-Disposition": f'attachment; filename="sme-bacnet-sim-config.{ext}"'})

    @r.get("/api/network")
    async def get_network():
        return {**network_view(engine), "interfaces": await asyncio.to_thread(list_interfaces)}

    @r.put("/api/network")
    async def put_network(data: Dict[str, Any] = Body(...)):
        try:
            return await apply_network(engine, data)
        except (ValueError, ValidationError) as e:
            raise _bad(e)

    # ---- objects of a device (add / duplicate / delete / edit of devices: the common routes)

    @r.get("/api/devices/{device_id}/objects/config")
    async def objects_config(device_id: int, keys: str = ""):
        """Expanded object configs (template objects included), optionally only ``keys`` (comma separated)."""
        want = [k for k in keys.split(",") if k]
        objs = {f"{o.type}:{o.instance}": o for o in expand_device(device_cfg(device_id))}
        missing = [k for k in want if k not in objs]
        if missing:
            raise HTTPException(404, f"no object {', '.join(missing)} on device {device_id}")
        return [objs[k].model_dump(exclude_none=True) for k in (want or objs)]

    @r.post("/api/devices/{device_id}/objects/paste")
    async def paste(device_id: int, req: PasteReq):
        dev = device_cfg(device_id)
        try:
            new, rejected = paste_objects(dev, req.objects)
        except ValueError as e:
            raise _bad(e)
        for x in rejected:
            engine.log("error", f"paste to device {device_id}: {x['name']} rejected: {x['reason']}")
        if new:
            data = cfg_copy()
            d = next(x for x in data["devices"] if x["device_id"] == device_id)
            d["objects"] = [*d.get("objects", []), *(o.model_dump(exclude_none=True) for o in new)]
            names = {o.name for o in new}
            if d.get("removed"):
                d["removed"] = [n for n in d["removed"] if n not in names] or None
            try:
                cfg = SimConfig.model_validate(data)
            except ValidationError as e:
                raise _bad(e)
            await apply(cfg)
            engine.log("config", f"device {device_id}: pasted {', '.join(o.name for o in new)}")
        return {"ok": True, "pasted": [{"name": o.name, "key": f"{o.type}:{o.instance}"} for o in new],
                "rejected": rejected}

    return r


# ---- sme-sim-common hooks

def _used_ids(engine: Engine) -> set:
    cfg = engine.config
    used = {d.device_id for d in cfg.devices}
    if cfg.network.router.device_id is not None:
        used.add(cfg.network.router.device_id)
    return used


def create_hook(engine: Engine, body: Dict[str, Any]) -> Dict[str, Any]:
    """``POST /api/devices`` without a ``device_id``: the first free id from 1001."""
    if body.get("device_id"):
        return body
    used, n = _used_ids(engine), 1001
    while n in used:
        n += 1
    return {**body, "device_id": n}


def simulation_hook(engine: Engine, rest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``POST /api/simulation`` ``{"set_time": ISO 8601}`` (naive = local time) moves the simulated clock."""
    unknown = sorted(set(rest) - {"set_time"})
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(unknown)} (running, time_scale, set_time)")
    if "set_time" not in rest:
        return None
    ts = datetime.datetime.fromisoformat(str(rest["set_time"]).replace("Z", "+00:00")).timestamp()
    engine.set_clock(ts, "web UI")
    return {k: v for k, v in engine.config.simulation.model_dump().items() if k not in ("running", "time_scale")}


def import_ede(engine: Engine, files: Dict[str, bytes]) -> Tuple[SimConfig, List[str]]:
    """EDE import: main CSV (+ state-text CSV) or a zip of both."""
    return import_ede_files(files, base=engine.config)


def import_text(engine: Engine, files: Dict[str, bytes]) -> Tuple[SimConfig, List[str], str]:
    """YAML / JSON import: the file text becomes the config text (comments kept)."""
    if len(files) != 1:
        raise ValueError("YAML / JSON import takes a single file")
    (name, data), = files.items()
    text = data.decode("utf-8-sig")
    return parse_text(text, "json" if name.lower().endswith(".json") else None), [], text


IMPORT_HOOKS = {".csv": import_ede, ".zip": import_ede, ".yaml": import_text, ".yml": import_text,
                ".json": import_text}


def create_app(engine: Engine, *, manage_engine: bool = True):
    return make_base_app(engine, static_dir=STATIC, product_routers=[bacnet_router(engine)],
                         title="SME BACnetSim", version=__version__, config_model=SimConfig,
                         xlsx=SCHEMA, templates=REGISTRY, devices_attr="devices", device_key="device_id",
                         key_type=int, create_hook=create_hook, duplicate_hook=duplicate_hook,
                         simulation_hook=simulation_hook, import_hooks=IMPORT_HOOKS, manage_engine=manage_engine)
