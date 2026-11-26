# Behaviors

| `type` | Parameters | Example |
|---|---|---|
| `sine` | `min max period phase noise` | daily or periodic swings |
| `random` | `min max` | uniform noise |
| `random_walk` | `min max step` | drifting sensor |
| `expr` | `expr` | `"Zone1_Cmd"`, `"1.732 * Voltage * Current * PowerFactor / 1000"` |
| `follow` | `target tau noise` | first-order lag to a target: `"SetPoint if OnOff else 30"` |
| `counter` | `rate` | integrates units/second: `"Power / 3600"` → kWh |
| `pulse` | `rate` | accumulator pulses per second (fractions carried over): `"ActivePower * 100 / 3600"` |
| `replay` | `file column interpolate loop offset` | play a CSV time series (below) |

**CSV replay** (`replay`): the first CSV column is the timestamp — elapsed time (`HH:MM:SS` or seconds) or an
ISO datetime — and every other column is a value series. Each point names the `file` and its `column`, so one CSV
can drive many points (the file is parsed once). Relative paths resolve against the config file's directory.
Replay time 0 is the first row and advances with the simulated clock, so it follows `simulation.time_scale`.
`interpolate: linear` (default) or `step` (hold the previous row); binary and multi-state points always step-hold
(`active` / `inactive` / `1` / `0`, state numbers). `offset` starts mid-file (`"06:00:00"`, seconds, or an ISO
datetime for ISO CSVs); `loop: true` repeats, otherwise the last value is held. An empty cell holds the previous
value. Bad timestamps, rows going backwards or an unknown column are reported when the config is loaded. The
point row shows the replay position, e.g. `replay 06:12:30 (26%)`. Example: `configs/replay-example.yaml` with
`configs/data/day-profile.csv`:

```csv
time,oat,rh,occupied,mode
00:00:00,13.8,71,inactive,1
08:00:00,17.2,64,active,2
19:00:00,20.2,56,inactive,1
24:00:00,13.8,71,inactive,1
```

```yaml
- {type: ai, name: OutdoorTemp, units: degreesCelsius,
   behavior: {type: replay, file: data/day-profile.csv, column: oat, loop: true, offset: "06:00:00"}}
- {type: bi, name: Occupied,
   behavior: {type: replay, file: data/day-profile.csv, column: occupied, loop: true, offset: "06:00:00"}}
```

CSV can be recorded from a real device (read-only) with `sme-bacnet-sim record`, see [Cloning](cloning.md#recording-replay-csvs).

Expressions are sandboxed Python expressions. Available names: the device's object names, `t` (sim seconds),
`dt`, `hour` (sim clock, 0–24), `pv("Device", "Object")` to read another device, and
`sin cos exp log sqrt pi abs min max round clamp random uniform noise gauss`.

Objects that are **out of service** stop following their behavior, which is how you inject a fixed value or
a fault. Writing a simulated input from the UI sets it out of service automatically.

## Templates

`lighting`, `split_ac`, `ahu`, `power_meter`, `env_sensor`, `pv_inverter`, `custom` — see
[sme_bacnet_sim/templates.py](https://github.com/smartedge-tech-dev/sme-bacnet-sim/blob/main/sme_bacnet_sim/templates.py). Adding your own is a ~20-line function.

### User device templates

User device templates are YAML files in `--templates-dir`, `$SME_BACNET_SIM_TEMPLATES` or
`~/.sme-bacnet-sim/templates/` (first one set wins). They appear next to the built-in templates in the
**Add device** dialog; **Device templates → Reload user device templates** picks up edited files without a restart.

To make one from a device you have configured, select the device and click **Save as device template** in the
device header. Enter a name (letters, digits, `_ . -`; the default is the device name); if a template of that name
already exists you are asked before it is overwritten. The device's expanded configuration is written to
`<templates dir>/<name>.yaml` (the toast shows the path) and is available in **Add device** at once. The same
action over HTTP is `POST /api/templates/from-device/{id}` (see [HTTP API](http-api.md)).
