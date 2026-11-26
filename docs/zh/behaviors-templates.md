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
| `replay` | `file column interpolate loop offset` | 回放 CSV 时间序列（见下） |

**CSV 回放**（`replay`）：CSV 第 1 列是时间戳（经过时间 `HH:MM:SS` 或秒数，或 ISO 日期时间），其余各列是数值序列。
每个点指定 `file` 和 `column`，因此一个 CSV 可驱动多个点（文件只解析一次）。相对路径以配置文件所在目录为基准。
回放时刻 0 是第一行，随仿真时钟推进（跟随 `simulation.time_scale`）。`interpolate: linear`（默认）或 `step`
（保持上一行）；二值 / 多态点始终按 step 保持（`active` / `inactive` / `1` / `0`、状态编号）。`offset` 从中途开始
（`"06:00:00"`、秒数，ISO CSV 可用 ISO 日期时间），`loop: true` 循环播放，否则保持最后一个值。空单元格保持上一个值。
非法时间戳、时间倒退的行、不存在的列在加载配置时报错。点的行显示回放位置（例 `replay 06:12:30 (26%)`）。
示例：`configs/replay-example.yaml` 与 `configs/data/day-profile.csv`：

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

CSV 可用 `sme-bacnet-sim record` 从真实设备（只读）录制，见[克隆](cloning.md)。

表达式是沙箱化的 Python 表达式。可用名称：设备内的对象名称、`t`（仿真秒数）、`dt`、`hour`（仿真时钟，0–24）、用于读取其他设备的 `pv("Device", "Object")`，以及 `sin cos exp log sqrt pi abs min max round clamp random uniform noise gauss`。

处于 **out of service** 的对象会停止跟随其 behavior，这就是注入固定值或故障的方法。在 UI 中写入模拟输入时，会自动将其置为 out of service。

## 模板

`lighting`、`split_ac`、`ahu`、`power_meter`、`env_sensor`、`pv_inverter`、`custom`——见 [sme_bacnet_sim/templates.py](https://github.com/smartedge-tech-dev/sme-bacnet-sim/blob/main/sme_bacnet_sim/templates.py)。添加自己的模板只需一个约 20 行的函数。

### 用户设备模板

用户设备模板是放在 `--templates-dir`、`$SME_BACNET_SIM_TEMPLATES` 或 `~/.sme-bacnet-sim/templates/`（先指定者优先）下的
YAML 文件，会和内置模板一起出现在**添加设备**对话框中。编辑文件后，用 **设备模板 → 重新加载用户设备模板** 即可无需重启生效。

要从已配置好的设备生成模板：选中设备，点击设备头部的 **保存为设备模板**，输入名称（字母、数字和 `_ . -`，默认取设备名）；
同名模板已存在时会先确认是否覆盖。设备展开后的配置会写入 `<模板目录>/<名称>.yaml`（保存路径显示在提示中），并立即可在
**添加设备** 中选用。对应的 HTTP 操作是 `POST /api/templates/from-device/{id}`（见 [HTTP API](http-api.md)）。
