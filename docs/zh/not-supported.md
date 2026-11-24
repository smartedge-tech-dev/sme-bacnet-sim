# 不支持的功能

## [Foreign device 注册（跨子网）](foreign-device.md)

Not supported：`foreign_device` 与 `mode: bbmd` 同时使用、BBMD 主机名（仅支持 IPv4 地址）、
读写 BBMD 的表（Read-Broadcast-Distribution-Table、Read-Foreign-Device-Table 等）。

## [Accumulator、Pulse Converter 与 Loop](accumulators-loops.md)

Not supported：Prescale 的应用（仅保存其值）；Accumulator 的 Value_Set / Value_Before_Change / Value_Change_Time / Logging_Record / Pulse_Rate 和限值监视；Pulse Converter 的 Adjust_Value 语义（作为普通可写属性处理，不调整 Count 和 Present_Value）、Count_Before_Change / Count_Change_Time / Update_Time 以及 COV_Period 定期通知；这三类对象的 intrinsic reporting（`alarm` 会报错）；引用其他设备或 Present_Value 以外的属性。

## [File 与 Program](files-programs.md)

Not supported：过渡状态 `loading`、`waiting`、`unloading`；拒绝当前状态下无效的请求；真实的程序执行或异常
（`normal` 以外的 Reason_For_Halt）；通过写 File_Size 截断文件；Archive 的语义（仅为可写标志）；AtomicWriteFile 中
Record_Count 与实际记录数的一致性检查。这些细节只能依据付费的 ASHRAE 135 原文确定。

## [Trend Log](trend-logs.md)

不支持：`triggered` 记录类型、记录其他设备的对象（因此也不支持对它们的 COV 订阅 / `cov-resubscription-interval`），以及缓冲区中的 log-status / time-change 记录。

## [Schedule 与 Calendar](schedules-calendars.md)

不支持：写入模拟器之外设备上的目标（没有网络 WriteProperty），以及重新读取由客户端写入的 `list-of-object-property-references`（目标来自配置）。

## [报警（Intrinsic Reporting）](alarms.md)

不支持：确认通知（通知类型 `ack-notification`）。AcknowledgeAlarm 会得到应答并更新 Acked_Transitions，但不会向接收方发送通知。除上述预先校验之外，WritePropertyMultiple 严格的全有或全无语义（回滚已应用的写入）也不支持。SME BACnetSim 免费，且仅基于公开资料构建；只能依据付费的 ASHRAE 135 文本才能确定的行为一律不予实现。

## [事件登记（Event Enrollment，algorithmic reporting）](event-enrollments.md)

Not supported：事件类型 `floating-limit`、`change-of-value` 及其它所有类型（其精确算法仅在 ASHRAE 135 中规定）、
事件登记的故障检测（无 `fault` 状态 / change-of-reliability）、监视其它设备的对象或 present-value 以外的属性、
通过 BACnet 写入修改 `event-type` / `object-property-reference`、用 CreateObject / DeleteObject 创建 / 删除事件登记。
被事件登记监视的值对象不能删除。

## [Life Safety Point 与 Life Safety Zone](life-safety.md)

不支持：change-of-life-safety 事件报告（不评估 alarm-values、life-safety-alarm-values、fault-values 及事件属性）、
状态的严重程度顺序与依赖模式的状态转换、maintenance-required / direct-reading / setting 的行为、用
CreateObject / DeleteObject 创建 / 删除 Life Safety 对象。

## [TextMessage、PrivateTransfer 与列表元素服务](text-private-transfer.md)

不支持：PrivateTransfer 参数的厂商自定义含义（不解码）、路由器设备上的 TextMessage、以及除上述检查外 ASHRAE 135
仅针对个别属性规定的 AddListElement / RemoveListElement 规则。
