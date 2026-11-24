# 复制 / 粘贴与属性面板

- **设备**：在设备头部点「复制」（或在列表中右键点击设备、未选中点位时按 Ctrl+C），再点「粘贴」（头部按钮、
  「编辑 → 粘贴」或 Ctrl+V）即添加一个副本：设备 ID 为源设备之后第一个空闲号，名称为 `Name (copy)`，
  与「添加设备」一样写入配置。
- **点位**：Ctrl / Shift 点击选择多行，按 Ctrl+C（或「编辑 → 复制」），选中一个设备（同一个或另一个）后按 Ctrl+V。
  粘贴的对象使用该类型下一个空闲 instance，名称冲突时加 `(copy)` 后缀。引用（`log_object`、schedule 的 `targets` /
  例外中的 `calendar`、`input_object`、loop 的 `*_object`、`monitored_object`、`notification_class`、
  `alarm.notification_class`）按名称保留；引用同一批粘贴中的对象时指向改名后的副本。被引用的名称在目标设备中不存在时，
  该对象不粘贴，原因会提示并写入事件日志。Ctrl+C / Ctrl+V 仅在焦点不在输入框或对话框时生效；剪贴板为页面内存。
- **属性**：点位行上的 ⚙ 按钮（设备对象用头部的「属性」）按属性标识符顺序列出 BACnet 对象的全部属性，显示值、数据类型
  及是否可写。写入走与 BACnet WriteProperty 请求相同的路径（相同校验、报警属性写回配置）；可命令的 Present_Value 可选择
  优先级写入或释放。仅基本类型（real、double、unsigned、integer、boolean、enumerated、character string）可编辑；构造类型
  （数组、列表、序列）以 JSON 显示，在 UI 中只读。Object_Identifier、Object_Type、Property_List 不从 UI 写入。
