# HTTP API

| 方法 | 路径 | |
|---|---|---|
| GET | `/api/version` | `{name, version, common_version}` |
| GET | `/api/state` | 完整快照 |
| WS | `/ws` | 快照 + 数值变化 + 日志事件 |
| POST | `/api/devices/{id}/objects/{type:instance}/write` | `{"value": 1, "priority": 8}` |
| POST | `.../relinquish`, `.../oos` | `{"priority": 8}`, `{"out_of_service": true}` |
| POST | `/api/devices/{id}/objects/{type:instance}/ack` | 确认该对象报警的所有未确认转换 |
| POST | `/api/devices/{id}/dcc` | `{"state": "enable"}`（或 `disable` / `disable-initiation`） |
| POST | `/api/simulation` | `{"running": true, "time_scale": 60, "set_time": "2026-11-23T08:00:00"}`（均可选；不带时区的时间 = 本地时间） |
| GET/PUT | `/api/config` | 整个配置（PUT 接受 YAML 或 JSON 文本） |
| POST | `/api/config/save` | 把运行中的配置写入 `-c` 指定的文件（未带 `-c` 启动时返回 400），返回 `{ok, path}` |
| GET/PUT | `/api/network` | 网络设置与本机 IPv4 网卡（`{network, bind, config_path, interfaces}`）；PUT `{ip, port, network_number, virtual_network, mode, router, foreign_device}` 校验、重新绑定并写回 `network:` 部分 → `{ok, bind, saved, save_error}` |
| POST | `/api/config/import` | multipart 上传：一个 YAML / JSON / Excel（`.xlsx`）文件，或 EDE CSV 文件 / zip（字段 `file`，可重复） |
| GET | `/api/config/export?format=yaml\|json\|ede` | 下载（`ede` = 主 CSV + 状态文本 CSV 的 zip；Excel 用 `GET /api/config/xlsx`） |
| GET | `/api/config/xlsx` | 把运行中的配置下载为 Excel 点表 |
| GET | `/api/config/xlsx-template` | 空白 Excel 点表模板 |
| GET | `/api/templates` | 模板目录 |
| POST | `/api/templates/reload` | 重新加载用户模板，返回 `{dir, loaded, errors, templates}` |
| POST | `/api/templates/from-device/{id}` | `{"name": "my-ahu", "title": ..., "description": ..., "overwrite": false}` 把设备保存为用户模板，返回 `{ok, name, path}`（已存在则 409） |
| POST/PUT/DELETE | `/api/devices`, `/api/devices/{id}/config` | 添加 / 编辑 / 删除设备；不带 `device_id` 的 POST `/api/devices` 取 1001 起第一个空闲 ID，返回 `{ok, name, device}`（ID 已存在则 409）；`GET /api/devices/{id}/config` 以 YAML 返回该设备 |
| POST | `/api/devices/{id}/duplicate` | 复制设备（可选 `{"device_id"}`，否则取下一个空闲 ID；名称 `Name (copy)`），返回 `{ok, name, device}`（`name` = 新设备 ID，`device` = 副本） |
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

错误返回 `{"detail": ..., "error": message}`；导入失败时顶层还带有 `errors` 列表（逐行消息）。
