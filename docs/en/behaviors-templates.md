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

Expressions are sandboxed Python expressions. Available names: the device's object names, `t` (sim seconds),
`dt`, `hour` (sim clock, 0–24), `pv("Device", "Object")` to read another device, and
`sin cos exp log sqrt pi abs min max round clamp random uniform noise gauss`.

Objects that are **out of service** stop following their behavior, which is how you inject a fixed value or
a fault. Writing a simulated input from the UI sets it out of service automatically.

## Templates

`lighting`, `split_ac`, `ahu`, `power_meter`, `env_sensor`, `pv_inverter`, `custom` — see
[sme_bacnet_sim/templates.py](https://github.com/smartedge-tech-dev/sme-bacnet-sim/blob/main/sme_bacnet_sim/templates.py). Adding your own is a ~20-line function.
