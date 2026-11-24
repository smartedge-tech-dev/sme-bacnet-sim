# Trend Log

`type: tl`（或 `trend-log`）会创建一个 BACnet Trend Log 对象，用于记录**同一设备**内的另一个对象（轮询或按变化记录），并将采样保存在环形缓冲区中（最旧的记录会被丢弃，`stop-when-full` 为 false）：

```yaml
- {type: tl, name: RoomTemp_Log, log_object: RoomTemp, log_interval: 60, buffer_size: 1000}
- {type: tl, name: RoomTemp_Cov, log_object: RoomTemp, logging_type: cov, client_cov_increment: 0.5}
```

| 键 | 默认值 | 说明 |
|---|---|---|
| `log_object` | （必填） | 被记录对象的名称；必须存在于该设备中 |
| `log_property` | `present-value` | 目标对象的任意数值 / 枚举 / 布尔属性 |
| `log_interval` | `60` | **仿真**秒数（BACnet `log-interval` 以 1/100 秒上报）；仅用于轮询模式 |
| `logging_type` | `polled` | `polled` 或 `cov`（BACnet `logging-type`） |
| `client_cov_increment` | 目标对象的 `cov-increment` | 仅用于 `cov` 模式；被记录的实数值的最小变化量 |
| `buffer_size` | `1000` | 环形缓冲区大小 |
| `enabled` | `true` | `enable` 属性的初始值（也可通过 BACnet 和 UI 写入） |

采样基于仿真时钟，并以仿真日期时间作为时间戳，因此在 `time_scale: 3600` 时，一小时的真实时间会按配置的间隔产生一天的历史数据。当一个 tick 比 `log_interval` 更长时，错过的间隔会合并为一次采样。使用 **ReadRange** 读取缓冲区（按位置、按序列号、按时间，或不带范围以读取响应能容纳的全部内容）；`log-buffer` 不能通过 ReadProperty 读取。向 `record-count` 写入 `0` 会清空日志。`split_ac` 和 `power_meter` 模板各包含一个 Trend Log。EDE 导出 / 导入会携带 Trend Log（见下文 EDE 部分）。

**COV 记录**（`logging_type: cov`）：不按间隔采样，而是在被记录的值相对上一条记录变化至少达到增量时追加一条记录——增量为 `client_cov_increment`（若已设置，读回时为 `client-cov-increment`），否则在记录 present value 时取目标对象的 `cov-increment`，否则任何变化都记录；布尔 / 枚举 / 整数值在任何变化时都记录——或在目标对象的 status flags 变化时记录。启用日志且缓冲区为空时（清空之后同样如此）会立即记录第一条。变化在每个仿真 tick 检测一次，并以仿真时钟打时间戳；`log-interval` 读取为 0。
不支持：`triggered` 记录类型、记录其他设备的对象（因此也不支持对它们的 COV 订阅 / `cov-resubscription-interval`），以及缓冲区中的 log-status / time-change 记录。
