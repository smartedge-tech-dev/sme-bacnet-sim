# File と Program

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

| 種別 | キー |
|---|---|
| `file`（File, 10） | `file_type`（既定 `text/plain`）、`access`（`stream` / `record`）、`content`（テキスト）または `path`（起動時に読み込むファイル、設定ファイルからの相対パス）、`read_only`（既定 false） |
| `program`（Program, 16） | `program_state`（初期値 `idle` / `running` / `halted`、既定 `idle`）、`instance_of`（既定はオブジェクト名）、`program_location` |

ファイル内容はメモリ上に保持します。stream アクセスはバイト列、record アクセスは 1 行を 1 レコード（改行は含まない）
として扱います。File_Size はバイト数（record アクセスではレコード長の合計）、Record_Count はレコード数です。
**AtomicReadFile / AtomicWriteFile** は両アクセス方式に対応します。開始位置 / レコード `-1` は末尾への追記、末尾を
超える開始位置は `services / invalid-file-start-position`、アクセス方式の不一致は `invalid-file-access-method`、
Read_Only のファイルは `file-access-denied`、File 以外のオブジェクトは `inconsistent-object-type`、存在しない
オブジェクトは `object / unknown-object` を返します。書き込みで File_Size / Record_Count と Modification_Date
（シミュレーション時計）を更新します。`content` で定義したファイルへの書き込み内容は設定に反映されるため、**Save** /
エクスポートで保存されます（UTF-8 として有効な場合のみ）。`path` のファイルはメモリ上でのみ変更され、ディスク上の
ファイルには書き込みません。File_Size、Modification_Date、File_Access_Method、Record_Count、Read_Only は
クライアントから書き込めません（`write-access-denied`）。

Program：Program_Change への書き込みは即座に適用され、`ready` に戻ります。`load`・`run`・`restart` → `running`、
`halt` → `halted`（Reason_For_Halt `normal`、Description_Of_Halt "halted by request"）、`unload` → `idle`、
`ready` → 変化なし。どの状態でもすべての要求を受け付けます。UI には状態と Program_Change メニュー
（`POST /api/devices/{id}/program/{instance}/change`）を表示します。Program_State、Reason_For_Halt、
Description_Of_Halt、Instance_Of はクライアントから書き込めません。

EDE はファイル内容・ファイル種別・アクセス方式を持たないため、インポートしたファイルは空の stream ファイルになります
（警告あり）。Program は名前のみインポートします。

Not supported：過渡状態 `loading`・`waiting`・`unloading`、現在の状態で無効な要求の拒否、実際のプログラム実行や
異常（`normal` 以外の Reason_For_Halt）、File_Size 書き込みによる切り詰め、Archive の意味づけ（単なる書き込み可能
フラグ）、AtomicWriteFile の Record_Count と送信レコード数の整合チェック。これらの厳密な規定は有償の ASHRAE 135
原文にしかありません。
