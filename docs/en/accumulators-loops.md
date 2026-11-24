# Accumulators, pulse converters and loops

```yaml
- {type: acc, name: EnergyPulses, units: kilowatt-hours, scale: 0.01, max: 99999999,
   behavior: {type: pulse, rate: "ActivePower * 100 / 3600"}}
- {type: pc, name: EnergyFromPulses, input_object: EnergyPulses, scale_factor: 0.01, units: kilowatt-hours}
- type: loop
  name: SupplyTempLoop
  controlled_object: SupplyTemp      # controlled-variable-reference (present-value)
  manipulated_object: CoolValve      # manipulated-variable-reference (present-value)
  setpoint_object: SupplyTempSP      # or a fixed setpoint: 16
  proportional_constant: 8
  integral_constant: 0.2
  min: 0                             # minimum-output
  max: 100                           # maximum-output
  units: percent                     # output-units
  priority_for_writing: 10
```

| Type | Keys |
|---|---|
| `acc` (Accumulator, 23) | `value` (unsigned count), `units`, `scale` (Scale as a float scale, default 1), `max` (Max_Pres_Value, default 4294967295; above it the count wraps to 0), `prescale` (`[multiplier, modulo_divide]`) |
| `pc` (Pulse Converter, 24) | `value`, `units`, `scale_factor` (default 1), `input_object` (an accumulator of the same device → Input_Reference), `cov_increment` |
| `loop` (Loop, 12) | `controlled_object`, `manipulated_object`, `setpoint` or `setpoint_object`, `proportional_constant` (default 1), `integral_constant` (1/s, default 0), `derivative_constant` (s, default 0), `bias` (default 0), `action` (`direct` / `reverse`, default `direct`), `update_interval` (sim seconds, default 1; the Update_Interval property is in ms), `min` / `max` (output limits, default 0 / 100), `units` (Output_Units), `priority_for_writing` (default 16), `cov_increment` |

- **Accumulator**: driven by any behavior; the `pulse` behavior adds `rate` pulses per second.
- **Pulse converter** with `input_object`: every tick the accumulator's count delta (wrap-around included)
  times Scale_Factor is added to Present_Value, and Count shows the accumulator's count. Without
  `input_object` it is a plain Real value object (behaviors apply).
- **Loop** (textbook PID, on the simulated clock every Update_Interval): `e = PV − setpoint` (direct) or
  `setpoint − PV` (reverse); `output = bias + Kp·e + Ki·∫e dt + Kd·de/dt`, clamped to Minimum_Output ..
  Maximum_Output, with the integral held while the output is saturated (anti-windup). The output goes to the
  loop's Present_Value and to the manipulated object (its priority array at Priority_For_Writing when it is
  commandable, else its present value). Constants, setpoint, action, limits, update interval and write
  priority can be changed with WriteProperty. With a `setpoint_object`, Setpoint follows that object's value.
  Out of service: no computation and no output write. The UI shows the output plus PV / SP.
- **COV**: pulse converters use the COV-increment criteria, loops the generic criteria (present-value /
  status-flags), as defined by bacpypes3. bacpypes3 has no COV criteria for the Accumulator, so SubscribeCOV
  on an accumulator is not available (SubscribeCOVProperty works).
- **CreateObject** creates accumulators and pulse converters (without input reference); loops are declared
  in the config only. **DeleteObject** refuses objects referenced by a pulse converter or loop.
- **EDE**: accumulators and pulse converters are exported (unit code; the `max` column of an accumulator is
  Max_Pres_Value) and imported; loops are exported but skipped on import with a warning (EDE carries no
  references / PID constants).

Not supported: applying Prescale (stored only), Value_Set / Value_Before_Change / Value_Change_Time /
Logging_Record / Pulse_Rate and limit monitoring of the Accumulator; the Adjust_Value semantics of the
Pulse Converter (it is a plain writable property: Count and Present_Value are not adjusted),
Count_Before_Change / Count_Change_Time / Update_Time and COV_Period periodic notifications; intrinsic
reporting on these three types (`alarm` is rejected); references to other devices or to properties other
than Present_Value.
