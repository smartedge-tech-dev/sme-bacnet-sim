# File 与 Program

```yaml
- {type: program, name: AHU-Sequence, instance_of: AHU-Seq-v2, program_state: running}
- type: file
  name: MaintenanceLog
  file_type: text/plain            # File_Type (MIME type)
  access: record                   # stream (default) | record
  content: |-                      # or: path: logs/maintenance.txt (relative to the config file)
    2026-04-01 filter replaced
    2026-10-01 belt tension checked
- {type: file, name: Firmware, file_type: application/octet-stream, path: fw.bin, read_only: true}
```

| 类型 | 键 |
|---|---|
| `file`（File, 10） | `file_type`（默认 `text/plain`）、`access`（`stream` / `record`）、`content`（文本）或 `path`（启动时读入的文件，相对于配置文件）、`read_only`（默认 false） |
| `program`（Program, 16） | `program_state`（初始 `idle` / `running` / `halted`，默认 `idle`）、`instance_of`（默认为对象名）、`program_location` |

文件内容保存在内存中。stream 访问按字节处理；record 访问把每一行作为一条记录（不含换行符）。File_Size 为字节数
（record 访问为各记录长度之和），Record_Count 为记录数。**AtomicReadFile / AtomicWriteFile** 支持两种访问方式：
起始位置 / 记录号 `-1` 表示追加到末尾；起始位置超出末尾返回 `services / invalid-file-start-position`；访问方式不符返回
`invalid-file-access-method`；Read_Only 文件返回 `file-access-denied`；非 File 对象返回 `inconsistent-object-type`；
对象不存在返回 `object / unknown-object`。写入会更新 File_Size / Record_Count 与 Modification_Date（仿真时钟）。
以 `content` 定义的文件，写入内容会同步到配置，**Save** / 导出时一并保存（仅当内容是有效 UTF-8）；以 `path` 定义的文件
只在内存中修改，不会写回磁盘文件。File_Size、Modification_Date、File_Access_Method、Record_Count、Read_Only
对客户端只读（`write-access-denied`）。

Program：写入 Program_Change 立即生效并恢复为 `ready`：`load`、`run`、`restart` → `running`，`halt` → `halted`
（Reason_For_Halt `normal`，Description_Of_Halt "halted by request"），`unload` → `idle`，`ready` → 不变。任何状态下
都接受所有请求。UI 显示状态和 Program_Change 下拉菜单（`POST /api/devices/{id}/program/{instance}/change`）。
Program_State、Reason_For_Halt、Description_Of_Halt、Instance_Of 对客户端只读。

EDE 不携带文件内容、文件类型和访问方式：导入的文件为空的 stream 文件（并给出警告）；Program 只导入名称。

Not supported：过渡状态 `loading`、`waiting`、`unloading`；拒绝当前状态下无效的请求；真实的程序执行或异常
（`normal` 以外的 Reason_For_Halt）；通过写 File_Size 截断文件；Archive 的语义（仅为可写标志）；AtomicWriteFile 中
Record_Count 与实际记录数的一致性检查。这些细节只能依据付费的 ASHRAE 135 原文确定。
