# Behavior

| `type` | 参数 | 示例 |
|---|---|---|
| `sine` | `min max period phase noise` | 每日或周期性的波动 |
| `random` | `min max` | 均匀噪声 |
| `random_walk` | `min max step` | 漂移的传感器 |
| `expr` | `expr` | `"Zone1_Cmd"`、`"1.732 * Voltage * Current * PowerFactor / 1000"` |
| `follow` | `target tau noise` | 对目标的一阶滞后：`"SetPoint if OnOff else 30"` |
| `counter` | `rate` | 按 单位/秒 积分：`"Power / 3600"` → kWh |
| `pulse` | `rate` | Accumulator 每秒脉冲数（小数部分结转）：`"ActivePower * 100 / 3600"` |

表达式是沙箱化的 Python 表达式。可用名称：设备内的对象名称、`t`（仿真秒数）、`dt`、`hour`（仿真时钟，0–24）、用于读取其他设备的 `pv("Device", "Object")`，以及 `sin cos exp log sqrt pi abs min max round clamp random uniform noise gauss`。

处于 **out of service** 的对象会停止跟随其 behavior，这就是注入固定值或故障的方法。在 UI 中写入模拟输入时，会自动将其置为 out of service。

## 模板

`lighting`、`split_ac`、`ahu`、`power_meter`、`env_sensor`、`pv_inverter`、`custom`——见 [sme_bacnet_sim/templates.py](https://github.com/smartedge-tech-dev/sme-bacnet-sim/blob/main/sme_bacnet_sim/templates.py)。添加自己的模板只需一个约 20 行的函数。
