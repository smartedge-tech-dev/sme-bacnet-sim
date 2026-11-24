# Accumulator、Pulse Converter 与 Loop

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

| 类型 | 键 |
|---|---|
| `acc`（Accumulator，23） | `value`（unsigned 计数）、`units`、`scale`（Scale，float scale，默认 1）、`max`（Max_Pres_Value，默认 4294967295；超过后计数回绕到 0）、`prescale`（`[multiplier, modulo_divide]`） |
| `pc`（Pulse Converter，24） | `value`、`units`、`scale_factor`（默认 1）、`input_object`（同一设备的 Accumulator → Input_Reference）、`cov_increment` |
| `loop`（Loop，12） | `controlled_object`、`manipulated_object`、`setpoint` 或 `setpoint_object`、`proportional_constant`（默认 1）、`integral_constant`（1/s，默认 0）、`derivative_constant`（s，默认 0）、`bias`（默认 0）、`action`（`direct` / `reverse`，默认 `direct`）、`update_interval`（模拟秒，默认 1；Update_Interval 属性单位为 ms）、`min` / `max`（输出上下限，默认 0 / 100）、`units`（Output_Units）、`priority_for_writing`（默认 16）、`cov_increment` |

- **Accumulator**：可由任意 behavior 驱动；`pulse` behavior 每秒累加 `rate` 个脉冲。
- **Pulse Converter**（带 `input_object`）：每个 tick 把 Accumulator 的计数增量（已考虑回绕）× Scale_Factor 累加到 Present_Value，Count 显示 Accumulator 的计数。没有 `input_object` 时它就是普通的 Real 值对象（可使用 behavior）。
- **Loop**（教科书式 PID，按模拟时钟每个 Update_Interval 运算一次）：`e = PV − setpoint`（direct）或 `setpoint − PV`（reverse）；`output = bias + Kp·e + Ki·∫e dt + Kd·de/dt`，限制在 Minimum_Output .. Maximum_Output，输出饱和时停止积分（anti-windup）。输出写入 Loop 的 Present_Value 和被操作对象（可命令对象写入 Priority_For_Writing 的 priority array，否则写 present value）。各常数、setpoint、action、上下限、更新周期和写入优先级都可用 WriteProperty 修改。有 `setpoint_object` 时 Setpoint 跟随该对象的值。Out of service 时不运算也不写输出。UI 显示输出以及 PV / SP。
- **COV**：按 bacpypes3 的定义，Pulse Converter 使用 COV increment 判据，Loop 使用通用判据（present-value / status-flags）。bacpypes3 没有 Accumulator 的 COV 判据，因此 Accumulator 不支持 SubscribeCOV（SubscribeCOVProperty 可用）。
- **CreateObject** 可创建 Accumulator 和 Pulse Converter（不带 input reference）；Loop 只能在配置文件中声明。**DeleteObject** 拒绝删除被 Pulse Converter 或 Loop 引用的对象。
- **EDE**：Accumulator 和 Pulse Converter 可导出（单位代码；Accumulator 的 `max` 列为 Max_Pres_Value）和导入；Loop 会被导出，但导入时跳过并给出警告（EDE 不携带引用和 PID 常数）。

Not supported：Prescale 的应用（仅保存其值）；Accumulator 的 Value_Set / Value_Before_Change / Value_Change_Time / Logging_Record / Pulse_Rate 和限值监视；Pulse Converter 的 Adjust_Value 语义（作为普通可写属性处理，不调整 Count 和 Present_Value）、Count_Before_Change / Count_Change_Time / Update_Time 以及 COV_Period 定期通知；这三类对象的 intrinsic reporting（`alarm` 会报错）；引用其他设备或 Present_Value 以外的属性。
