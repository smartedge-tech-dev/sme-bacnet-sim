# TextMessage、PrivateTransfer 与列表元素服务

- 模拟设备收到的 **ConfirmedTextMessage / UnconfirmedTextMessage** 写入事件日志（类别 `text-message`：发送方地址
  与设备、priority、message class、正文）。模拟设备可通过 `POST /api/devices/{id}/text-message`
  `{"message": "...", "address": "100:2", "priority": "normal", "message_class": 5, "confirmed": false}` 发送
  （`address` 默认为全局广播 `*:*`，不能 confirmed；`message_class` 为数字或文本）。
- **ConfirmedPrivateTransfer / UnconfirmedPrivateTransfer** 写入事件日志（类别 `private-transfer`）。confirmed 请求按
  设备 `private_transfer` 列表的声明应答：`result: echo`（默认）把 service parameters 原样作为 result block 返回，
  `null` 不带 result block，字符串 / 整数 / 实数 / 布尔值则返回该值。没有匹配项时返回 ConfirmedPrivateTransfer-Error
  `services` / `optional-functionality-not-supported`：设备支持该服务，只是不支持这个 vendor / service number，
  因此不用表示整个服务缺失的 `unrecognized-service` reject。
- **AddListElement / RemoveListElement** 适用于任何可写的列表型属性（如 Notification Class 的 recipient-list、
  Calendar 的 date-list、Schedule 的 list-of-object-property-references、Life Safety Zone 的 zone-members）。元素按
  bacpypes3 属性类型解码，新列表与整表 WriteProperty 完全相同地写入（相同检查与后续处理）。添加时已存在的元素被
  忽略。错误（Add/RemoveListElement-Error）：未知对象 / 属性、`services` / `property-is-not-a-list`（不是列表）、
  `property` / `property-is-not-an-array`（指定了数组下标）、`write-access-denied`、`invalid-data-type`，删除时不在
  列表中的元素返回 `services` / `list-element-not-found`（带第一个此类元素的从 1 开始的序号）。写回配置：zone-members
  与 recipient-list（同时立即用于发送通知）；date-list 与 list-of-object-property-references 与 WriteProperty 一样只改变
  运行中的对象。

```yaml
  - device_id: 1006
    name: Room-Sensor-101
    private_transfer:
      - {vendor_id: 999, service_number: 1}              # result: echo (default)
      - {vendor_id: 999, service_number: 2, result: 42}  # fixed value
```

不支持：PrivateTransfer 参数的厂商自定义含义（不解码）、路由器设备上的 TextMessage、以及除上述检查外 ASHRAE 135
仅针对个别属性规定的 AddListElement / RemoveListElement 规则。
