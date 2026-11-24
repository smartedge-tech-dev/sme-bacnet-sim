# 事件登记（Event Enrollment，algorithmic reporting）

`type: ee`（或 `event-enrollment`）创建 Event Enrollment 对象：监视同一设备中另一个值对象的 present-value，
并通过 Notification Class 发送通知，因此没有 `alarm` 块的点（例如模板里的温度）也能产生报警：

```yaml
- type: ee
  name: RoomTempWatch
  monitored_object: Temperature
  event_type: out-of-range
  event_parameters: {low_limit: 18, high_limit: 28, deadband: 0.5}
  notification_class: RoomAlarms
  time_delay: 60
- {type: ee, name: ModeWatch, monitored_object: OperationMode, event_type: change-of-state,
   event_parameters: {alarm_values: [Maintenance]}, notification_class: 1, notify_type: event}
```

| 键 | 含义 |
|---|---|
| `monitored_object` | 同一设备中值对象的名称（Object_Property_Reference = 其 present-value） |
| `event_type` | `out-of-range`（模拟量，不含 Accumulator）或 `change-of-state`（二进制 / 多态） |
| `event_parameters` | out-of-range：`low_limit`、`high_limit`（均必填、始终启用）、`deadband`；change-of-state：`alarm_values`（状态编号或文本，二进制用 `active` / `inactive`） |
| `notification_class` | 同一设备中 notification-class 对象的名称或实例号 |
| `time_delay`、`time_delay_normal` | **模拟**秒（默认 0 / `time_delay`）；`time_delay` 即 Event_Parameters 中的 Time_Delay |
| `event_enable` | `[to-offnormal, to-fault, to-normal]`，默认全部 true |
| `notify_type` | `alarm`（默认）或 `event` |

事件登记与 intrinsic reporting 共用同一套事件状态机、通知、AcknowledgeAlarm、
GetEventInformation / GetAlarmSummary / GetEnrollmentSummary 以及 Web UI（带徽标和 **确认** 按钮的行、*视图 → 报警*）。
对 `event-parameters`（同一事件类型）、`event-enable`、`notify-type`、`time-delay-normal`、`notification-class`、`event-enrollment` 的
BACnet 写入会生效并写回配置；`acked-transitions` 只读。演示配置的 `Room-Sensor-101` 中有一个示例。EDE 导出包含事件登记
（对象类型 9）；EDE 导入会跳过并给出警告（EDE 不含监视对象和参数）。

Not supported：事件类型 `floating-limit`、`change-of-value` 及其它所有类型（其精确算法仅在 ASHRAE 135 中规定）、
事件登记的故障检测（无 `fault` 状态 / change-of-reliability）、监视其它设备的对象或 present-value 以外的属性、
通过 BACnet 写入修改 `event-type` / `object-property-reference`、用 CreateObject / DeleteObject 创建 / 删除事件登记。
被事件登记监视的值对象不能删除。
