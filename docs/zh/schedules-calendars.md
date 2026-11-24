# Schedule 与 Calendar

`type: sch`（或 `schedule`）会创建一个 BACnet Schedule 对象，把它的值写入同一设备或**另一个模拟设备**的对象；`type: cal`（或 `calendar`）会创建一个 Calendar 对象，其 `present-value` 在所列日期上为 true。

```yaml
- {type: cal, name: Holidays, dates: ["2026-12-25", {from: "2026-12-29", to: "2027-01-03"}, "*-01-01"]}
- type: sch
  name: Light_Sch
  targets:                      # written via list-of-object-property-references
    - Zone1_Cmd                 # object of this device
    - {device: AHU-1, object: Fan_Cmd}            # object of another simulated device (name or device id)
    - {device: 300100, object: "binary-value:4"}  # device outside the simulator: listed, never written
  priority_for_writing: 16
  default: "OFF"                # schedule-default
  weekly:
    weekdays: [{time: "08:00", value: "ON"}, {time: "18:00", value: "OFF"}]
    sat: [{time: "09:00", value: "ON"}, {time: "12:00", value: null}]   # null = back to default
  exceptions:
    - {calendar: Holidays, priority: 10, times: [{time: "00:00", value: "OFF"}]}
    - {date: "2026-11-03", priority: 5, times: [{time: "10:00", value: "ON"}]}
    - {date: {from: "2026-08-10", to: "2026-08-14"}, priority: 6, times: [{time: "00:00", value: "OFF"}]}
    - {date: {weeknday: ["*", 6, 5]}, priority: 8, times: [{time: "13:00", value: "OFF"}]}  # last Friday
  effective_period: {from: "2026-01-01", to: "2027-12-31"}   # optional, default always
```

| 键 | 默认值 | 说明 |
|---|---|---|
| `weekly` | — | 键为 `mon`..`sun`，或 `weekdays` / `weekend` / `daily`；每个键对应一个 `{time: "HH:MM[:SS]", value}` 的列表 |
| `exceptions` | — | 特殊事件：`date`（形式与 Calendar 的 `dates` 相同：带 `*` 通配符的 `YYYY-MM-DD`、`{from, to}` 范围或 `{weeknday: [...]}`）或 `calendar`（Calendar 对象名称）二选一，加上 `priority` 1–16（1 优先级最高）和 `times` |
| `default` | 0 / `OFF` / 1 | schedule-default；`weekly` / `exceptions` 至少需要一个 |
| `targets` | 无 | 输出或值对象，类型须一致：名称（本设备）或 `{device, object}`；`device` 是模拟设备的名称或 id，`object` 是名称或 `type:instance`（`av:3`、`binary-output:1`）。不在模拟器中的设备 id 需要 `object: type:instance`；它会连同其 `deviceIdentifier` 出现在 `list-of-object-property-references` 中，但会被跳过（启动时记录一次日志），也绝不会通过网络写入 |
| `priority_for_writing` | `16` | 可命令目标使用的 priority-array 槽位 |
| `effective_period` | 始终有效 | `{from, to}`；在此范围之外，Schedule 保持其值且不写入任何内容 |
| `dates`（Calendar） | `[]` | 日期、`{from, to}` 范围，或 `{weeknday: [month, week-of-month, day-of-week]}`（`*` = 任意；月份 13 / 14 = 奇数月 / 偶数月；周 1–5 = 第 1–7 日 … 第 29–31 日，6 = 当月最后 7 天，7–9 = 其之前的 7 天区块；星期 1 = 星期一） |

值类型由目标决定：模拟量 → REAL，二进制 → ENUMERATED（`0/1`、`true/false`、`ON/OFF`、`active/inactive` 或目标自己的文本），多状态 → UNSIGNED 状态号。没有目标时，值为 REAL。时间请加引号（`"18:00"`）：不加引号时，YAML 1.1 会把 `18:00` 读成数字 1080（仍然能被理解，但加引号更清晰）。

Schedule 运行在**仿真时钟**上，因此 `time_scale` 会让它们快进。bacpypes3 自带的 Schedule 解释器使用墙上时钟和 asyncio 定时器，所以模拟器保留了其 Schedule 对象和求值规则，但每个 tick 都根据仿真日期时间重新求值。当值发生变化，或到达 weekly / exception 日程中的某个时间条目时（即使值相同，因此预定动作会覆盖操作员的修改），会设置 Schedule 的 `present-value`，并以 `priority_for_writing` 将该值写入每个目标（不可命令的值对象则直接写入 `present-value`）；在两次预定动作之间不会写入任何内容。因此客户端的 relinquish 可以正常工作；Schedule 会在下一个时间条目再次写入。位于其他模拟设备中的目标会被直接写入该设备的对象。目标所在设备执行 ReinitializeDevice 时会重新下发预定值；COV 订阅会保留。`weekly-schedule`、`exception-schedule` 和 `schedule-default` 可通过 BACnet 写入，并在下一个 tick 生效（类型错误的值会把 `reliability` 设为 `configuration-error`）；exception 条目可使用日期、日期范围、weekNDay 或 Calendar 引用。写入的内容会以 `weekly` / `exceptions` / `default` 保留在配置中（Save / Export；binary 值记为 0 / 1，只改写有变化的键，模板中的 Schedule 以覆盖条目保存）；配置无法表示的内容（类型错误、不是本设备 Calendar 的 Calendar 引用、目标不接受的值）不会保留，配置保持最后一次有效的内容。`exception-schedule` 是数组，因此 Add/RemoveListElement 返回 `property-is-not-a-list`。Calendar 的 `date-list` 同样可写；写入 `list-of-object-property-references` 会改变目标（本设备或其他模拟设备中与 Schedule 同类的输出 / 值对象的 present-value，或模拟器之外的设备；其他引用返回 `value-out-of-range`），两者都会保留在配置中（Save / Export）。客户端对 Schedule 自身 `present-value` 的写入（须使用 Schedule 的数据类型，否则返回 `invalid-data-type`）会以 `priority_for_writing` 转发给所有目标，并保持到下一个预定时间条目；无论是否设置了 `out-of-service`，该写入都会被接受。

不支持：写入模拟器之外设备上的目标（没有网络 WriteProperty）。

`lighting` 模板带有一个切换 `Zone1_Cmd` 的 Schedule（工作日 08:00 开、18:00 关），`split_ac` 模板带有一个控制 `OnOff` 的 Schedule（工作日 09:00–18:00）；可通过模板参数 `schedule: false` 禁用它们。UI 会列出 Schedule 和 Calendar 及其当前值和下一次切换；点击某一行可查看 weekly / exception 表。EDE 导出会把它们列为对象类型 17 / 6；EDE 导入会跳过它们。
