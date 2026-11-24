# EDE 导入 / 导出

SME BACnetSim 可以读写 EDE 文件（B.I.G.-EU Engineering Data Exchange，布局 2.3），这是大多数 BACnet 工具和集成商之间交换的 CSV 点表。

- **导出**：`EDE` 按钮（`GET /api/config/export?format=ede`）下载一个 zip，其中包含主文件 `sme-bacnet-sim-ede.csv`（每个对象一行，另有一行 object-type 为 8 的设备行；使用数字形式的对象类型和单位代码；模板已展开）以及状态文本文件 `sme-bacnet-sim-ede-statetexts.csv`（二进制对象：Text 1 = inactive，Text 2 = active；多状态对象：状态 1..N）。
- **导入**：选择主 CSV，可同时选择状态文本 CSV（或导出的 zip）。状态文本文件通过其表头识别。接受分号或逗号分隔符、UTF-8（带或不带 BOM）以及 cp1252。行按设备 instance 分组为一个设备（名称取自设备行，否则为 `Device-<id>`）；AV/BV/MSV 上的 `settable = Y` 会使对象可命令。模拟器不支持的对象类型会被跳过，并在事件日志中以警告形式报告。运行中配置的网络和仿真设置保持不变；导入的对象是静态的（无 behavior）。
- **Trend Log**（对象类型 20）：导出时把 Trend Log 设置以 `key=value` 对（用 `|` 分隔）写入 `vendor-specific-address` 列（例如 `log_object=RoomTemp|log_interval=60|logging_type=cov`；键与 YAML 中相同），因此导出的文件重新导入时会带回其 Trend Log。来自其他工具的文件不带被记录对象的引用；此时导入会为名为 `<name>_Log` 的 Trend Log 记录 `<name>`（若该对象存在），否则记录设备的第一个模拟量 / 二进制 / 多状态对象（轮询，60 秒），并给出警告。
- **Accumulator / Pulse Converter / Loop**（对象类型 23 / 24 / 12）：见上文“对象”。
- **hi-limit / low-limit** 映射到模拟量对象的 `alarm.high_limit` / `alarm.low_limit`。导入时，报警使用设备的第一个 Notification Class；若文件中没有，则创建 `NC-1`（instance 1，无接收方）。Notification Class 以默认优先级且无接收方的方式导入（EDE 中没有对应的列）。其他报警设置（deadband、time delay、二进制 / 多状态报警值）不会被 EDE 携带。
