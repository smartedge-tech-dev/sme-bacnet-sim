# Files and programs

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

| Type | Keys |
|---|---|
| `file` (File, 10) | `file_type` (default `text/plain`), `access` (`stream` / `record`), `content` (text) or `path` (file loaded at start, relative to the config file), `read_only` (default false) |
| `program` (Program, 16) | `program_state` (initial `idle` / `running` / `halted`, default `idle`), `instance_of` (default the object name), `program_location` |

File content is held in memory. Stream access works on the bytes; record access makes every line one record
(without the line terminator). File_Size is the byte count (record access: the sum of the record lengths) and
Record_Count the number of records. **AtomicReadFile / AtomicWriteFile** support both access methods: a start
position / record `-1` appends, a start beyond the end answers `services / invalid-file-start-position`, the
wrong access method `invalid-file-access-method`, a Read_Only file `file-access-denied`, a non-File object
`inconsistent-object-type` and a missing object `object / unknown-object`. A write updates File_Size /
Record_Count and Modification_Date (simulated clock). Written content of a `content` file is kept in the config,
so **Save** / Export store it (only when it is valid UTF-8); a `path` file is changed in memory only, the file
on disk is never written. File_Size, Modification_Date, File_Access_Method, Record_Count and Read_Only are
read-only for clients (`write-access-denied`).

Program: writing Program_Change applies the request at once and sets it back to `ready`: `load`, `run` and
`restart` -> `running`, `halt` -> `halted` (Reason_For_Halt `normal`, Description_Of_Halt "halted by request"),
`unload` -> `idle`, `ready` -> no change. Every request is accepted in every state. The UI shows the state and
a Program_Change menu (`POST /api/devices/{id}/program/{instance}/change`). Program_State, Reason_For_Halt,
Description_Of_Halt and Instance_Of are read-only for clients.

EDE carries no file content, file type or access method: imported files are empty stream files (with a
warning); programs are imported with their name.

Not supported: the transitional states `loading`, `waiting` and `unloading`, rejecting requests that are not
valid in the current state, any real program execution or failure (Reason_For_Halt other than `normal`),
writing File_Size to truncate a file, the Archive semantics (plain writable flag) and a consistency check of
the request's Record_Count against the records sent; the exact rules exist only in the paid ASHRAE 135 text.
