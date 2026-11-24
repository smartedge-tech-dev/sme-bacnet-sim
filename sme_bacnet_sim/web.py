"""FastAPI web UI and REST/WebSocket API."""

from __future__ import annotations

import asyncio
import datetime
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from .clipboard import duplicate_device, paste_objects
from .config import DeviceConfig, SimConfig, dump_yaml, parse_text
from .ede import export_ede_zip, import_ede_files
from .engine import Engine
from .netsettings import apply_network, list_interfaces, network_view
from .templates import expand_device, template_catalog
from .xlsx import EXPORT_FILE, TEMPLATE_FILE, blank_template, export_xlsx, import_xlsx

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


class SimReq(BaseModel):
    running: Optional[bool] = None
    time_scale: Optional[float] = None
    set_time: Optional[str] = None  # ISO 8601; naive = local time


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


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def create_app(engine: Engine) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        yield
        await engine.stop()

    app = FastAPI(title="SME BACnetSim", lifespan=lifespan)

    async def apply(cfg: SimConfig) -> Dict[str, Any]:
        try:
            await engine.reload(cfg)
        except (ValueError, ValidationError) as e:
            raise _bad(e)
        return {"ok": True}

    def cfg_copy() -> Dict[str, Any]:
        return engine.config.model_dump(exclude_none=True)

    # ---- state

    @app.get("/api/state")
    async def state():
        return engine.snapshot()

    @app.get("/api/templates")
    async def templates():
        return template_catalog()

    @app.get("/api/history/{device_id}/{key}")
    async def history(device_id: int, key: str):
        try:
            return engine.history(device_id, key)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.get("/api/devices/{device_id}/trendlog/{instance}")
    async def trendlog(device_id: int, instance: int):
        """Logged buffer of a trend log as [[timestamp (simulated clock, epoch s), value], ...]."""
        try:
            return engine.trendlog(device_id, instance).data()
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/devices/{device_id}/trendlog/{instance}/enable")
    async def trendlog_enable(device_id: int, instance: int, req: EnableReq):
        try:
            engine.set_trendlog_enable(device_id, instance, req.enabled)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @app.post("/api/devices/{device_id}/program/{instance}/change")
    async def program_change(device_id: int, instance: int, req: ProgramReq):
        async with engine._lock:
            try:
                engine.program_change(device_id, instance, req.request)
            except KeyError as e:
                raise HTTPException(404, str(e))
        return {"ok": True}

    @app.post("/api/devices/{device_id}/text-message")
    async def text_message(device_id: int, req: TextMessageReq):
        try:
            dest = await engine.send_text_message(device_id, req.message, req.address, req.priority,
                                                  req.message_class, req.confirmed)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")
        return {"ok": True, "destination": dest}

    @app.post("/api/devices/{device_id}/life-safety/{key}/state")
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

    @app.post("/api/devices/{device_id}/objects/{key}/write")
    async def write(device_id: int, key: str, req: WriteReq):
        try:
            await engine.write(device_id, key, req.value, req.priority)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise _bad(e)
        return {"ok": True}

    @app.post("/api/devices/{device_id}/objects/{key}/relinquish")
    async def relinquish(device_id: int, key: str, req: RelinquishReq):
        try:
            await engine.relinquish(device_id, key, req.priority)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            raise _bad(e)
        return {"ok": True}

    @app.post("/api/devices/{device_id}/objects/{key}/oos")
    async def oos(device_id: int, key: str, req: OosReq):
        try:
            engine.set_oos(device_id, key, req.out_of_service)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    @app.get("/api/devices/{device_id}/objects/{key}/properties")
    async def get_properties(device_id: int, key: str):
        """All properties of an object (key ``type:instance``; ``device:<id>`` for the device object)."""
        try:
            return engine.properties(device_id, key)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.put("/api/devices/{device_id}/objects/{key}/properties/{prop}")
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

    @app.post("/api/devices/{device_id}/objects/{key}/ack")
    async def acknowledge(device_id: int, key: str):
        try:
            engine.acknowledge(device_id, key)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise _bad(e)
        return {"ok": True}

    @app.post("/api/simulation")
    async def simulation(req: SimReq):
        if req.set_time:
            try:
                ts = datetime.datetime.fromisoformat(req.set_time.replace("Z", "+00:00")).timestamp()
            except ValueError as e:
                raise _bad(e)
            engine.set_clock(ts, "web UI")
        engine.set_simulation(req.running, req.time_scale)
        return engine.config.simulation.model_dump()

    @app.post("/api/devices/{device_id}/dcc")
    async def dcc(device_id: int, req: DccReq):
        try:
            engine.set_dcc(device_id, req.state)
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise _bad(e)
        return {"ok": True}

    # ---- configuration

    @app.get("/api/config")
    async def get_config(format: str = "json"):
        if format == "yaml":
            return PlainTextResponse(dump_yaml(engine.config))
        return engine.config.model_dump(exclude_none=True)

    @app.get("/api/config/export")
    async def export(format: str = "yaml"):
        if format == "json":
            body, mt, ext = engine.config.model_dump_json(indent=2, exclude_none=True), "application/json", "json"
        elif format == "ede":
            try:
                body = export_ede_zip(engine.config)
            except ValueError as e:
                raise _bad(e)
            mt, ext = "application/zip", "ede.zip"
        elif format == "xlsx":
            body, warnings = export_xlsx(engine.config)
            if warnings:
                engine.log_event("config", f"Excel export: {len(warnings)} warnings: " + "; ".join(warnings[:5])
                                 + (" ..." if len(warnings) > 5 else ""))
            return Response(body, media_type=XLSX_TYPE,
                            headers={"Content-Disposition": f'attachment; filename="{EXPORT_FILE}"'})
        else:
            body, mt, ext = dump_yaml(engine.config), "application/x-yaml", "yaml"
        return Response(body, media_type=mt,
                        headers={"Content-Disposition": f'attachment; filename="sme-bacnet-sim-config.{ext}"'})

    @app.get("/api/config/xlsx-template")
    async def xlsx_template():
        return Response(blank_template(), media_type=XLSX_TYPE,
                        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILE}"'})

    @app.put("/api/config")
    async def put_config(request: Request):
        text = (await request.body()).decode("utf-8")
        try:
            cfg = parse_text(text)
        except (ValidationError, yaml.YAMLError, ValueError) as e:
            raise _bad(e)
        return await apply(cfg)

    @app.post("/api/config/import")
    async def import_config(file: List[UploadFile] = File(...)):
        # YAML / JSON / Excel: a single file. EDE: main CSV (+ state-text CSV) or a zip of both.
        uploads = {(f.filename or f"upload-{i}"): await f.read() for i, f in enumerate(file)}
        names = ", ".join(uploads)
        warnings: List[str] = []
        try:
            if any(n.lower().endswith(".xlsx") for n in uploads):
                if len(uploads) != 1:
                    raise ValueError("Excel (.xlsx) import takes a single file")
                cfg, warnings = import_xlsx(next(iter(uploads.values())), base=engine.config)
            elif any(n.lower().endswith((".csv", ".zip")) for n in uploads):
                cfg, warnings = import_ede_files(uploads, base=engine.config)
            elif len(uploads) == 1:
                fname, data = next(iter(uploads.items()))
                cfg = parse_text(data.decode("utf-8-sig"), "json" if fname.lower().endswith(".json") else None)
            else:
                raise ValueError("multiple files are only supported for EDE (.csv) import")
        except (ValidationError, yaml.YAMLError, ValueError, UnicodeDecodeError, zipfile.BadZipFile) as e:
            raise _bad(e)
        res = await apply(cfg)
        msg = f"imported {names} ({len(cfg.devices)} devices)"
        if warnings:
            msg += f", {len(warnings)} warnings: " + "; ".join(warnings[:5]) + (" ..." if len(warnings) > 5 else "")
        engine.log_event("config", msg)
        return {**res, "warnings": warnings}

    @app.get("/api/network")
    async def get_network():
        return {**network_view(engine), "interfaces": await asyncio.to_thread(list_interfaces)}

    @app.put("/api/network")
    async def put_network(data: Dict[str, Any] = Body(...)):
        try:
            return await apply_network(engine, data)
        except (ValueError, ValidationError) as e:
            raise _bad(e)

    @app.post("/api/config/save")
    async def save_config():
        if not engine.config_path:
            raise HTTPException(400, "simulator was started without --config; use export instead")
        Path(engine.config_path).write_text(dump_yaml(engine.config), encoding="utf-8")
        engine.log_event("config", f"saved to {engine.config_path}")
        return {"ok": True, "path": engine.config_path}

    @app.get("/api/devices/{device_id}/config")
    async def get_device(device_id: int):
        for d in engine.config.devices:
            if d.device_id == device_id:
                return PlainTextResponse(dump_yaml(d))
        raise HTTPException(404, "device not found")

    @app.put("/api/devices/{device_id}/config")
    async def put_device(device_id: int, request: Request):
        text = (await request.body()).decode("utf-8")
        try:
            dev = DeviceConfig.model_validate(yaml.safe_load(text) or {})
        except (ValidationError, yaml.YAMLError) as e:
            raise _bad(e)
        data = cfg_copy()
        idx = next((i for i, d in enumerate(data["devices"]) if d["device_id"] == device_id), None)
        if idx is None:
            raise HTTPException(404, "device not found")
        data["devices"][idx] = dev.model_dump(exclude_none=True)
        try:
            cfg = SimConfig.model_validate(data)
        except ValidationError as e:
            raise _bad(e)
        res = await apply(cfg)
        engine.log_event("config", f"device {dev.device_id} ({dev.name}) updated")
        return res

    @app.post("/api/devices")
    async def add_device(dev: Dict[str, Any] = Body(...)):
        data = cfg_copy()
        if not dev.get("device_id"):
            used = {d["device_id"] for d in data["devices"]}
            n = 1001
            while n in used:
                n += 1
            dev["device_id"] = n
        try:
            new = DeviceConfig.model_validate(dev)
            data["devices"].append(new.model_dump(exclude_none=True))
            cfg = SimConfig.model_validate(data)
        except ValidationError as e:
            raise _bad(e)
        res = await apply(cfg)
        engine.log_event("config", f"device {new.device_id} ({new.name}) added")
        return {**res, "device_id": new.device_id}

    @app.post("/api/devices/{device_id}/duplicate")
    async def duplicate(device_id: int):
        data = cfg_copy()
        try:
            new = duplicate_device(data, device_id)
        except KeyError:
            raise HTTPException(404, "device not found")
        try:
            cfg = SimConfig.model_validate(data)
        except ValidationError as e:
            raise _bad(e)
        res = await apply(cfg)
        engine.log_event("config", f"device {device_id} duplicated as {new['device_id']} ({new['name']})")
        return {**res, "device_id": new["device_id"], "name": new["name"]}

    def _device_cfg(device_id: int) -> DeviceConfig:
        dev = next((d for d in engine.config.devices if d.device_id == device_id), None)
        if dev is None:
            raise HTTPException(404, "device not found")
        return dev

    @app.get("/api/devices/{device_id}/objects/config")
    async def objects_config(device_id: int, keys: str = ""):
        """Expanded object configs (template objects included), optionally only ``keys`` (comma separated)."""
        want = [k for k in keys.split(",") if k]
        objs = {f"{o.type}:{o.instance}": o for o in expand_device(_device_cfg(device_id))}
        missing = [k for k in want if k not in objs]
        if missing:
            raise HTTPException(404, f"no object {', '.join(missing)} on device {device_id}")
        return [objs[k].model_dump(exclude_none=True) for k in (want or objs)]

    @app.post("/api/devices/{device_id}/objects/paste")
    async def paste(device_id: int, req: PasteReq):
        dev = _device_cfg(device_id)
        try:
            new, rejected = paste_objects(dev, req.objects)
        except ValueError as e:
            raise _bad(e)
        for r in rejected:
            engine.log_event("error", f"paste to device {device_id}: {r['name']} rejected: {r['reason']}")
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
            engine.log_event("config", f"device {device_id}: pasted {', '.join(o.name for o in new)}")
        return {"ok": True, "pasted": [{"name": o.name, "key": f"{o.type}:{o.instance}"} for o in new],
                "rejected": rejected}

    @app.delete("/api/devices/{device_id}")
    async def delete_device(device_id: int):
        data = cfg_copy()
        before = len(data["devices"])
        data["devices"] = [d for d in data["devices"] if d["device_id"] != device_id]
        if len(data["devices"]) == before:
            raise HTTPException(404, "device not found")
        res = await apply(SimConfig.model_validate(data))
        engine.log_event("config", f"device {device_id} deleted")
        return res

    # ---- live updates

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q = engine.subscribe()
        try:
            def snap() -> Dict[str, Any]:
                nonlocal seen
                data = engine.snapshot()
                seen = max((e.get("seq", 0) for e in data.get("events", [])), default=seen)
                return {"type": "snapshot", "data": data}

            seen = 0
            await sock.send_json(snap())
            while True:
                msg = await q.get()
                if msg["type"] == "reload":
                    msg = snap()
                elif msg["type"] == "log" and msg["event"].get("seq", 0) <= seen:
                    # already in a snapshot sent after it was logged (e.g. "pasted ..." logged right after the
                    # reload of a paste / duplicate / import): the UI would list it twice
                    continue
                await sock.send_json(msg)
        except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
            pass
        finally:
            engine.unsubscribe(q)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
