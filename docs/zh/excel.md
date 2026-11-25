# Excel 点表

除 YAML 和 EDE 外，配置还可以以 Excel 工作簿（`.xlsx`）读写：既可以手工填写后导入，也可以从运行中的模拟器
导出、编辑后再导入。

- **文件 → 下载空白 Excel 模板**（`GET /api/config/xlsx-template`）：只含全部工作表和列的空工作簿。
- **文件 → 导出 → Excel 点表**（`GET /api/config/xlsx`）：当前运行的配置。
- **文件 → 导入…** 接受单个 `.xlsx` 文件（`POST /api/config/import`）。

## Workbook layout

每个工作表第 1 行是英文列名（不区分大小写，列顺序可调整）。下一行以 `#` 开头，是各列的日文 / 中文说明。
首个非空单元格以 `#` 开头的行视为注释并忽略，空行也忽略。空单元格表示“未设置”（使用默认值）。

| 工作表 | 每行 = | 列 |
|---|---|---|
| `Devices` | 设备 | `device_id`*, `name`*, `description`, `template`, `params`, `vendor_id`, `vendor_name`, `model_name`, `location`, `dcc_password`, `reinit_password`, `extra` |
| `Points` | 对象 | `device_id`*, `type`*, `instance`, `name`*, `description`, `units`, `value`, `commandable`, `min`, `max`, `cov_increment`, `state_texts`, `inactive_text`, `active_text`, `behavior`, `alarm_class`, `alarm_high_limit`, `alarm_low_limit`, `alarm_deadband`, `alarm_values`, `alarm_time_delay`, `extra` |
| `StateTexts` | 一组状态文本 | `ref`*, `text_1`, `text_2`, ...（按需增加 `text_N` 列） |
| `Network`（可选） | 设置项 | `key`, `value` — 例如 `network.ip`, `network.port`, `network.foreign_device.bbmd`, `simulation.time_scale` |

\* 必填。

- `Points.device_id` 必须出现在 `Devices` 中。`type` 为 BACnet 对象类型名（`analog-input`）或编号（`0`）。
  `instance` 为空 = 自动分配。`units` 为 BACnet engineering-units 名（`degrees-celsius`）或编号（`62`）。
  `commandable`：`TRUE` / `FALSE`（也可 yes / no、1 / 0）。
- `state_texts` 引用 `StateTexts.ref`；多态对象的文本为状态 1..N，二值对象在未填 `inactive_text` / `active_text`
  时以 `text_1` / `text_2` 作为 inactive / active 文本。导出时文本相同的对象共用同一个 ref。
- `alarm_*` 组成对象的 `alarm:`（intrinsic reporting）：`alarm_class` 为通知类名称或编号，`alarm_values`
  为二值报警值（`active`）或逗号分隔的多态状态号（`2,3`）。
- `params`、`behavior`、`extra` 为 YAML flow 映射，如 `{zones: 4}`、`{type: sine, min: 20, max: 26, period: 600}`。
  `extra` 用与 YAML 相同的键存放所有没有专用列的设置（趋势日志设置、日程、通知类接收者、回路常数、
  `{alarm: {notify_type: event}}` 等其他报警设置 ...）。列的值优先于 `extra`。
- 带 `template` 的设备保持模板不展开，其 `Points` 行与 YAML 的 `objects:` 一样，是对模板对象的覆盖 / 追加。
- `Network` 工作表的各行按键逐项覆盖当前运行配置的网络与模拟设置；未列出或 `value` 为空的键沿用运行中的值。

## Import checks

逐行检查，所有错误一并报告，每条错误都带工作表名、行号和列名（例如
`Points row 12, column 'instance': not an integer: 'abc'`）。只要还有错误就不会应用任何内容。
检查项包括数字 / 布尔 / YAML 格式、对象类型与单位编码、`device_id` 引用、设备 ID / 对象名 / 实例号重复、
`state_texts` 引用以及对象设置本身。警告（如被忽略的未知列）与 EDE 导入一样写入事件日志。

## Round trip and export warnings

导出 → 导入可还原为等价的配置。超出 Excel 单元格上限（32,767 字符）的值会被略去，并在事件日志中给出警告；
从 `path` 加载内容的文件对象按路径引用导出，同样给出警告。
