# HTTP API

| 方法 | 路径 | |
|---|---|---|
| GET | `/api/state` | 完整快照 |
| WS | `/ws` | 快照 + 数值变化 + 日志事件 |
| POST | `/api/devices/{id}/objects/{type:instance}/write` | `{"value": 1, "priority": 8}` |
| POST | `.../relinquish`, `.../oos` | `{"priority": 8}`, `{"out_of_service": true}` |
| POST | `/api/devices/{id}/objects/{type:instance}/ack` | 确认该对象报警的所有未确认转换 |
| POST | `/api/devices/{id}/dcc` | `{"state": "enable"}`（或 `disable` / `disable-initiation`） |
| POST | `/api/simulation` | `{"running": true, "time_scale": 60, "set_time": "2026-11-23T08:00:00"}`（均可选；不带时区的时间 = 本地时间） |
| GET/PUT | `/api/config` | 整个配置（PUT 接受 YAML 或 JSON 文本） |
| POST | `/api/config/import` | multipart 上传：一个 YAML / JSON / Excel（`.xlsx`）文件，或 EDE CSV 文件 / zip（字段 `file`，可重复） |
| GET | `/api/config/export?format=yaml\|json\|ede\|xlsx` | 下载（`ede` = 主 CSV + 状态文本 CSV 的 zip，`xlsx` = Excel 点表） |
| GET | `/api/config/xlsx-template` | 空白 Excel 点表模板 |
| POST/PUT/DELETE | `/api/devices`, `/api/devices/{id}/config` | 添加 / 编辑 / 删除设备 |
| POST | `/api/devices/{id}/duplicate` | 复制设备（下一个空闲 ID、`Name (copy)`），返回 `{"device_id", "name"}` |
| GET | `/api/devices/{id}/objects/config?keys=analog-value:1,...` | 用于复制的对象配置（模板对象已展开） |
| POST | `/api/devices/{id}/objects/paste` | `{"objects": [对象配置, ...]}` → `{"pasted": [{name, key}], "rejected": [{name, reason}]}` |
| GET | `/api/devices/{id}/objects/{type:instance}/properties` | 全部属性（`device:{id}` = 设备对象）：`[{id, name, value, datatype, writable, editable, kind}]` |
| PUT | `/api/devices/{id}/objects/{type:instance}/properties/{property}` | `{"value": 21.5, "priority": 8}`（仅基本类型；`null` + priority 为释放） |
| GET | `/api/history/{id}/{type:instance}` | 趋势采样 |
| GET | `/api/devices/{id}/trendlog/{instance}` | Trend Log 缓冲区 `[[timestamp, value], ...]`（仿真时钟） |
| POST | `/api/devices/{id}/trendlog/{instance}/enable` | `{"enabled": true}` |
| POST | `/api/devices/{id}/program/{instance}/change` | `{"request": "halt"}`（load / run / halt / restart / unload / ready） |
| POST | `/api/devices/{id}/text-message` | `{"message": "...", "address": "100:2", "priority": "normal", "message_class": 5, "confirmed": false}`（address 默认为全局广播） |
| POST | `/api/devices/{id}/life-safety/{type:instance}/state` | `{"state": "alarm"}`（Life Safety Point 的 Tracking_Value） |
