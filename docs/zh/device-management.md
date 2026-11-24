# 设备管理服务

每个模拟设备还提供以下服务（bacpypes3 0.1.0 在服务端对其中大部分未实现或存在缺陷，因此模拟器在 `sme_bacnet_sim/engine.py` / `sme_bacnet_sim/devmgmt.py` 中自行实现）：

- **COV 增量默认值**（未设置 `cov_increment` 的模拟量对象）：带 `behavior` 的点位（每个 tick 都会变化）取其量程的 1 %（对象的 `min` / `max`，否则取 behavior 的 `min` / `max`），否则取按单位的默认值（°C / kW / kWh / A 为 0.1，% / %RH / V / m³/h 为 0.5，W / Pa 为 1，ppm / lx / W/m² 为 5，Hz 为 0.01；见 `sme_bacnet_sim/engine.py` 中的 `_UNIT_COV`），否则为 `0`；没有 behavior 的点位保持 `0`（= 任何变化都通知）。如需覆盖，请显式设置 `cov_increment`。
- **SubscribeCOV**（confirmed / unconfirmed，带生存期），适用于所有值对象：当 presentValue 的变化至少达到 `covIncrement`（模拟量）时发送通知，无论变化来自 behavior、BACnet 写入还是 UI；任何 status-flags 变化（alarm、fault、out-of-service）时也会发送。**SubscribeCOVProperty** 可用于任意属性，并使用客户端指定的 COV 增量（默认：present-value 取对象的 `covIncrement`）；通知中携带该属性和 status flags。
- **CreateObject / DeleteObject**，适用于值对象（AI/AO/AV/BI/BO/BV/MSI/MSO/MSV、Accumulator、Pulse Converter），可按对象类型（取第一个空闲 instance）或按对象标识符创建，并可带可选的初始值：object-name、present-value、description、units / cov-increment（模拟量）、active-text / inactive-text（二进制）、state-text（多状态，默认 `State 1`、`State 2`）、out-of-service。创建的对象会被追加到运行中配置里该设备的 `objects`（因此 保存 / 导出 会保留它），并立即出现在 UI 中。删除会将其从 `objects` 中移除；如果该对象来自模板，其名称会被加入设备的 `removed` 列表，模板展开时会跳过该列表中的名称（从 `removed` 中删除该名称即可恢复模板对象；创建同名对象也会将其从 `removed` 中移除）。不可删除（`object` / `object-deletion-not-permitted`）：Device 对象、Network Port、Trend Log、Schedule、Calendar、Notification Class，以及被 Trend Log 记录或被 Schedule 写入的值对象。创建失败时使用 CreateObject-Error 并带上出错元素的编号（`dynamic-creation-not-supported`、`object-identifier-already-exists`、`duplicate-name`、其他属性为 `write-access-denied`、`invalid-data-type`）。
- **TimeSynchronization / UTCTimeSynchronization**（发给设备，或发给路由器 / 广播）：移动仿真时钟使其显示收到的时间（UTC 会按主机时区转换）；已流逝的仿真时间继续累计，Schedule 立即重新求值，Trend Log 在新时钟上继续记录。*仿真 → 与电脑时钟同步*（或 `POST /api/simulation {"set_time": ...}`）在 UI 中实现相同效果。
- **DeviceCommunicationControl** 的 enable / disable / disable-initiation，可带以分钟为单位的可选持续时间，按**墙上时钟**计时（标准中该持续时间是现实世界的超时，与仿真速度无关）。禁用期间，设备会忽略除 DeviceCommunicationControl 和 ReinitializeDevice 之外的一切请求，并且不发送任何内容（不发 I-Am、COV 或事件通知）；disable-initiation 仍会应答请求和 Who-Is，但不会主动发起其他任何操作。UI 中的设备标题栏会显示该状态，并带有 *启用通信* 按钮。
- **ReinitializeDevice** warmstart：数值恢复为配置的初始值，priority array 被 relinquish，out-of-service 被清除，behavior 和报警被重置（事件状态为 normal，全部已确认），通信重新启用。Coldstart：同上，并且清空 Trend Log 缓冲区。其他状态返回 `services` / `optional-functionality-not-supported`。

这些服务相关的设备键：

```yaml
  - device_id: 1002
    name: AC-1F-East
    dcc_password: secret      # DeviceCommunicationControl password (default: none = not checked)
    reinit_password: boot     # ReinitializeDevice password (default: none = not checked)
    removed: [FilterAlarm]    # template objects deleted with DeleteObject (written by the simulator)
```

密码错误会返回 `security` / `password-failure`。
