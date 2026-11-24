"""Built-in device templates.

A template is a function ``params -> list[object dict]``.  A device in the
config file may reference a template and then add or override objects by name.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from .config import DeviceConfig, ObjectConfig

Obj = Dict[str, Any]
TEMPLATES: Dict[str, Dict[str, Any]] = {}

# daylight factor 0..1 peaking at 12:00 (uses sim-clock hour)
DAYLIGHT = "max(0, sin(pi * (hour - 6) / 12))"
# summer ambient of an unconditioned room / outdoor air: 27 C at 03:00 .. 33 C at 15:00
AMBIENT = "30 + 3 * sin(2 * pi * (hour - 9) / 24)"
AMBIENT_MAX = 33.0


def template(name: str, title: str, params: Dict[str, Any]):
    def deco(fn: Callable[[Dict[str, Any]], List[Obj]]):
        TEMPLATES[name] = {"name": name, "title": title, "params": params, "build": fn}
        return fn

    return deco


def _flag(v) -> bool:
    return str(v).strip().lower() not in ("false", "0", "no", "off", "none", "")


def _with_alarms(objs: List[Obj], p: Dict[str, Any], alarms: Dict[str, Dict[str, Any]]) -> List[Obj]:
    """Attach intrinsic-reporting blocks plus the default notification class (instance 1) unless alarms: false."""
    if not _flag(p.get("alarms", True)):
        return objs
    for o in objs:
        if o["name"] in alarms:
            o["alarm"] = {"notification_class": "NC1", **alarms[o["name"]]}
    objs.append({"type": "nc", "name": "NC1", "instance": 1,
                 "description": "Default notification class (add recipients to receive event notifications)"})
    return objs


@template("lighting", "Lighting controller",
          {"zones": 4, "dimmable": True, "watts_per_zone": 120, "schedule": True})
def _lighting(p):
    n, dim, w = int(p["zones"]), bool(p["dimmable"]), float(p["watts_per_zone"])
    objs: List[Obj] = []
    power_terms = []
    for i in range(1, n + 1):
        objs.append({"type": "bo", "name": f"Zone{i}_Cmd", "value": 0,
                     "description": f"Zone {i} on/off command",
                     "active_text": "ON", "inactive_text": "OFF"})
        objs.append({"type": "bi", "name": f"Zone{i}_Status", "value": 0,
                     "description": f"Zone {i} on/off feedback",
                     "active_text": "ON", "inactive_text": "OFF",
                     "behavior": {"type": "expr", "expr": f"Zone{i}_Cmd"}})
        if dim:
            objs.append({"type": "ao", "name": f"Zone{i}_Level", "units": "percent", "value": 100,
                         "min": 0, "max": 100, "description": f"Zone {i} dimming level"})
            power_terms.append(f"Zone{i}_Status * Zone{i}_Level / 100")
        else:
            power_terms.append(f"Zone{i}_Status")
    objs.append({"type": "ai", "name": "Power", "units": "watts", "value": 0, "cov_increment": 1,
                 "behavior": {"type": "expr", "expr": f"{w} * ({' + '.join(power_terms)}) * (1 + noise(0.01))"}})
    objs.append({"type": "ai", "name": "Illuminance", "units": "luxes", "value": 0, "cov_increment": 5,
                 "behavior": {"type": "follow", "tau": 5, "noise": 3,
                              "target": f"600 * {DAYLIGHT} + 500 * ({' + '.join(power_terms)}) / {n}"}})
    objs.append({"type": "bi", "name": "Occupancy", "value": 0,
                 "active_text": "Occupied", "inactive_text": "Unoccupied",
                 "behavior": {"type": "expr", "expr": "(1 - Occupancy) if random() < 0.02 else Occupancy"}})
    if _flag(p["schedule"]):
        objs.append({"type": "sch", "name": "Zone1_Schedule", "description": "Zone 1 on weekdays 08:00-18:00",
                     "weekly": {"weekdays": [{"time": "08:00", "value": "ON"}, {"time": "18:00", "value": "OFF"}]},
                     "default": "OFF", "targets": ["Zone1_Cmd"]})
    return objs


@template("split_ac", "Split / packaged air conditioner (indoor unit)",
          {"rated_kw": 2.8, "initial_temp": 28.0, "tau": 180, "schedule": True, "alarms": True,
           "high_limit": 35.0})
def _split_ac(p):
    kw, tau = float(p["rated_kw"]), float(p["tau"])
    ambient = AMBIENT
    objs = [
        {"type": "bo", "name": "OnOff", "value": 0, "active_text": "ON", "inactive_text": "OFF"},
        {"type": "bi", "name": "RunStatus", "value": 0, "active_text": "Running", "inactive_text": "Stopped",
         "behavior": {"type": "expr", "expr": "OnOff"}},
        {"type": "mso", "name": "Mode", "value": 2, "states": ["Auto", "Cool", "Heat", "Fan", "Dry"]},
        {"type": "mso", "name": "FanSpeed", "value": 1, "states": ["Auto", "Low", "Mid", "High"]},
        {"type": "av", "name": "SetPoint", "units": "degrees-celsius", "value": 26.0,
         "commandable": True, "min": 16, "max": 32},
        {"type": "ai", "name": "RoomTemp", "units": "degrees-celsius", "value": float(p["initial_temp"]),
         "cov_increment": 0.1,
         "behavior": {"type": "follow", "tau": tau, "noise": 0.02,
                      "target": f"SetPoint if (OnOff and Mode != 4) else {ambient}"}},
        {"type": "ai", "name": "OutdoorTemp", "units": "degrees-celsius", "value": 30.0, "cov_increment": 0.1,
         "behavior": {"type": "expr", "expr": f"{ambient} + noise(0.05)"}},
        {"type": "ai", "name": "Power", "units": "kilowatts", "value": 0, "cov_increment": 0.01,
         "behavior": {"type": "expr",
                      "expr": f"OnOff * {kw} * (0.25 + 0.75 * clamp(abs(RoomTemp - SetPoint) / 3, 0, 1))"
                              f" * (1 + noise(0.02))"}},
        {"type": "ai", "name": "Energy", "units": "kilowatt-hours", "value": 0, "cov_increment": 0.01,
         "behavior": {"type": "counter", "rate": "Power / 3600"}},
        {"type": "bi", "name": "Alarm", "value": 0, "active_text": "Alarm", "inactive_text": "Normal"},
        {"type": "tl", "name": "RoomTemp_Log", "log_object": "RoomTemp", "log_interval": 60},
    ]
    if _flag(p["schedule"]):
        objs.append({"type": "sch", "name": "OnOff_Schedule", "description": "Run on weekdays 09:00-18:00",
                     "weekly": {"weekdays": [{"time": "09:00", "value": "ON"}, {"time": "18:00", "value": "OFF"}]},
                     "default": "OFF", "targets": ["OnOff"]})
    # RoomTemp high limit is an overheat alarm (AC fault / room left off on a hot day): it sits above the
    # ambient peak (AMBIENT_MAX) so a unit that is simply switched off by its schedule stays normal.
    # Demo an alarm by writing high-limit (e.g. 28) or by setting the room out of service and writing 36.
    return _with_alarms(objs, p, {"RoomTemp": {"high_limit": float(p["high_limit"]), "low_limit": 15,
                                               "deadband": 0.5, "time_delay": 60}})


@template("ahu", "Air handling unit", {"design_pressure": 500, "alarms": True})
def _ahu(p):
    dp = float(p["design_pressure"])
    objs = [
        {"type": "bo", "name": "FanCmd", "value": 0, "active_text": "ON", "inactive_text": "OFF"},
        {"type": "bi", "name": "FanStatus", "value": 0, "active_text": "Running", "inactive_text": "Stopped",
         "behavior": {"type": "expr", "expr": "FanCmd"}},
        {"type": "ao", "name": "FanSpeed", "units": "percent", "value": 60, "min": 0, "max": 100},
        {"type": "ao", "name": "CoolValve", "units": "percent", "value": 0, "min": 0, "max": 100},
        {"type": "av", "name": "SupplyTempSP", "units": "degrees-celsius", "value": 16.0, "commandable": True},
        {"type": "ai", "name": "ReturnTemp", "units": "degrees-celsius", "value": 25.0, "cov_increment": 0.1,
         "behavior": {"type": "random_walk", "min": 23, "max": 28, "step": 0.05}},
        {"type": "ai", "name": "SupplyTemp", "units": "degrees-celsius", "value": 25.0, "cov_increment": 0.1,
         "behavior": {"type": "follow", "tau": 60, "noise": 0.03,
                      "target": "ReturnTemp - FanStatus * CoolValve / 100 * 12"}},
        {"type": "ai", "name": "DuctPressure", "units": "pascals", "value": 0, "cov_increment": 1,
         "behavior": {"type": "follow", "tau": 5, "noise": 2,
                      "target": f"FanStatus * {dp} * (FanSpeed / 100) ** 2"}},
        {"type": "ai", "name": "ReturnCO2", "units": "parts-per-million", "value": 600, "cov_increment": 5,
         "behavior": {"type": "random_walk", "min": 420, "max": 1200, "step": 8}},
        {"type": "bi", "name": "FilterAlarm", "value": 0, "active_text": "Dirty", "inactive_text": "Normal"},
    ]
    return _with_alarms(objs, p, {"FilterAlarm": {"alarm_value": "active"}})


@template("power_meter", "3-phase power meter", {"nominal_voltage": 200, "frequency": 50, "max_current": 50,
                                                        "alarms": True})
def _power_meter(p):
    v, f, imax = float(p["nominal_voltage"]), float(p["frequency"]), float(p["max_current"])
    objs = [
        {"type": "ai", "name": "Voltage", "units": "volts", "value": v, "cov_increment": 0.5,
         "behavior": {"type": "random_walk", "min": v * 0.97, "max": v * 1.03, "step": v * 0.002}},
        {"type": "ai", "name": "Current", "units": "amperes", "value": imax * 0.4, "cov_increment": 0.1,
         "behavior": {"type": "random_walk", "min": imax * 0.05, "max": imax * 0.95, "step": imax * 0.01}},
        {"type": "ai", "name": "PowerFactor", "units": "power-factor", "value": 0.95, "cov_increment": 0.01,
         "behavior": {"type": "random_walk", "min": 0.85, "max": 0.99, "step": 0.002}},
        {"type": "ai", "name": "ActivePower", "units": "kilowatts", "value": 0, "cov_increment": 0.1,
         "behavior": {"type": "expr", "expr": "1.732 * Voltage * Current * PowerFactor / 1000"}},
        {"type": "ai", "name": "Frequency", "units": "hertz", "value": f, "cov_increment": 0.01,
         "behavior": {"type": "random_walk", "min": f - 0.1, "max": f + 0.1, "step": 0.005}},
        {"type": "ai", "name": "Energy", "units": "kilowatt-hours", "value": 0, "cov_increment": 0.1,
         "behavior": {"type": "counter", "rate": "ActivePower / 3600"}},
        {"type": "tl", "name": "ActivePower_Log", "log_object": "ActivePower", "log_interval": 60},
    ]
    return _with_alarms(objs, p, {"Voltage": {"high_limit": round(v * 1.1, 3), "low_limit": round(v * 0.9, 3),
                                              "deadband": round(v * 0.01, 3), "time_delay": 10}})


@template("env_sensor", "Room environment sensor", {})
def _env_sensor(p):
    return [
        {"type": "ai", "name": "Temperature", "units": "degrees-celsius", "value": 24, "cov_increment": 0.1,
         "behavior": {"type": "expr", "expr": "24 + 2 * sin(2 * pi * (hour - 9) / 24) + noise(0.05)"}},
        {"type": "ai", "name": "Humidity", "units": "percent-relative-humidity", "value": 50, "cov_increment": 0.5,
         "behavior": {"type": "random_walk", "min": 35, "max": 65, "step": 0.3}},
        {"type": "ai", "name": "CO2", "units": "parts-per-million", "value": 600, "cov_increment": 5,
         "behavior": {"type": "follow", "tau": 120, "noise": 5, "target": "450 + 600 * Occupancy"}},
        {"type": "bi", "name": "Occupancy", "value": 0, "active_text": "Occupied", "inactive_text": "Unoccupied",
         "behavior": {"type": "expr", "expr": "(1 - Occupancy) if random() < 0.01 else Occupancy"}},
    ]


@template("pv_inverter", "PV inverter", {"capacity_kw": 50})
def _pv(p):
    cap = float(p["capacity_kw"])
    return [
        {"type": "ai", "name": "Irradiance", "units": "watts-per-square-meter", "value": 0, "cov_increment": 5,
         "behavior": {"type": "expr", "expr": f"1000 * {DAYLIGHT} * uniform(0.75, 1.0)"}},
        {"type": "ao", "name": "PowerLimit", "units": "percent", "value": 100, "min": 0, "max": 100,
         "description": "Output curtailment limit"},
        {"type": "ai", "name": "ActivePower", "units": "kilowatts", "value": 0, "cov_increment": 0.1,
         "behavior": {"type": "expr",
                      "expr": f"min({cap} * Irradiance / 1000 * 0.95, {cap} * PowerLimit / 100) * (Status == 2)"}},
        {"type": "ai", "name": "Energy", "units": "kilowatt-hours", "value": 0, "cov_increment": 0.1,
         "behavior": {"type": "counter", "rate": "ActivePower / 3600"}},
        {"type": "msi", "name": "Status", "value": 2, "states": ["Stopped", "Running", "Fault"],
         "behavior": {"type": "expr", "expr": "Status if Status == 3 else (2 if Irradiance > 20 else 1)"}},
    ]


@template("custom", "Empty device (define objects yourself)", {})
def _custom(p):
    return []


def expand_device(dev: DeviceConfig) -> List[ObjectConfig]:
    """Template objects merged with the device's own objects (same name overrides)."""
    objs: List[Obj] = []
    if dev.template:
        t = TEMPLATES.get(dev.template)
        if t is None:
            raise ValueError(f"{dev.name}: unknown template {dev.template!r} (known: {', '.join(TEMPLATES)})")
        params = {**t["params"], **dev.params}
        objs = t["build"](params)
    result: Dict[str, ObjectConfig] = {o["name"]: ObjectConfig.model_validate(o) for o in objs}
    for o in dev.objects:
        if o.name in result:
            merged = {**result[o.name].model_dump(exclude_none=True), **o.model_dump(exclude_unset=True)}
            result[o.name] = ObjectConfig.model_validate(merged)
        else:
            result[o.name] = o
    for name in dev.removed or []:  # objects deleted with DeleteObject
        result.pop(name, None)
    # auto-assign instance numbers per object type
    used: Dict[str, set] = {}
    for o in result.values():
        if o.instance is not None:
            used.setdefault(o.type, set()).add(o.instance)
    final = []
    for o in result.values():
        if o.instance is None:
            s = used.setdefault(o.type, set())
            n = 1
            while n in s:
                n += 1
            s.add(n)
            o = o.model_copy(update={"instance": n})
        final.append(o)
    return final


def template_catalog() -> List[Dict[str, Any]]:
    return [{"name": t["name"], "title": t["title"], "params": t["params"]} for t in TEMPLATES.values()]
