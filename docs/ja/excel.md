# Excel ポイントリスト

YAML・EDE に加えて、設定を Excel ブック（`.xlsx`）として読み書きできます。手で記入してインポートする
ポイントリストとしても、稼働中のシミュレーターからエクスポート → 編集 → 再インポートする用途にも使えます。

- **ファイル → 空の Excel テンプレートをダウンロード**（`GET /api/config/xlsx-template`）: 全シートと列だけの空ブック。
- **ファイル → エクスポート → Excel ポイントリスト**（`GET /api/config/xlsx`）: 稼働中の設定。
- **ファイル → インポート…** は `.xlsx` ファイル 1 つを受け付けます（`POST /api/config/import`）。

## Workbook layout

各シートの 1 行目は英語の列名（大文字小文字は区別せず、列の並べ替えも可）。その下の行は `#` で始まり、
各列の説明（日本語 / 中国語）です。最初の空でないセルが `#` で始まる行はコメントとして無視され、空行も無視されます。
空セルは「未設定」（既定値）を意味します。

| シート | 1 行 = | 列 |
|---|---|---|
| `Devices` | デバイス | `device_id`*, `name`*, `description`, `template`, `params`, `vendor_id`, `vendor_name`, `model_name`, `location`, `dcc_password`, `reinit_password`, `extra` |
| `Points` | オブジェクト | `device_id`*, `type`*, `instance`, `name`*, `description`, `units`, `value`, `commandable`, `min`, `max`, `cov_increment`, `state_texts`, `inactive_text`, `active_text`, `behavior`, `alarm_class`, `alarm_high_limit`, `alarm_low_limit`, `alarm_deadband`, `alarm_values`, `alarm_time_delay`, `extra` |
| `StateTexts` | 状態テキストの組 | `ref`*, `text_1`, `text_2`, ...（必要なだけ `text_N` 列） |
| `Network`（任意） | 設定項目 | `key`, `value` — 例 `network.ip`, `network.port`, `network.foreign_device.bbmd`, `simulation.time_scale` |

\* 必須。

- `Points.device_id` は `Devices` に存在する必要があります。`type` は BACnet オブジェクトタイプ名（`analog-input`）
  または番号（`0`）。`instance` 空欄 = 自動採番。`units` は BACnet engineering-units 名（`degrees-celsius`）
  または番号（`62`）。`commandable`: `TRUE` / `FALSE`（yes / no、1 / 0 も可）。
- `state_texts` は `StateTexts.ref` を参照します。多状態オブジェクトではテキストが状態 1..N、バイナリでは
  `inactive_text` / `active_text` が未指定なら `text_1` / `text_2` が inactive / active テキストになります。
  エクスポート時、同じテキストのオブジェクトは ref を共有します。
- `alarm_*` はオブジェクトの `alarm:`（intrinsic reporting）になります。`alarm_class` は通知クラスの名前または番号、
  `alarm_values` はバイナリのアラーム値（`active`）または多状態の状態番号のカンマ区切り（`2,3`）。
- `params`・`behavior`・`extra` は YAML の flow マッピングです（例 `{zones: 4}`、
  `{type: sine, min: 20, max: 26, period: 600}`）。`extra` には専用列のない設定をすべて YAML と同じキーで入れます
  （トレンドログ設定、スケジュール、通知クラスの受信者、ループ定数、`{alarm: {notify_type: event}}` などのその他の
  アラーム設定 ...）。列の値が `extra` より優先されます。
- `template` を持つデバイスはそのまま保持され、`Points` の行は YAML の `objects:` と同じくテンプレートオブジェクトへの
  上書き / 追加になります。
- `Network` シートの行は、稼働中の設定のネットワーク・シミュレーション設定をキー単位で上書きします。
  記載のないキーや `value` が空のキーは、稼働中の値を引き継ぎます。

## Import checks

すべての行を検査し、エラーはまとめて報告されます。各エラーにはシート名・行番号・列名が付きます
（例 `Points row 12, column 'instance': not an integer: 'abc'`）。エラーが残っている間は何も適用されません。
数値 / 真偽値 / YAML の形式、オブジェクトタイプと単位コード、`device_id` の参照、デバイス ID・オブジェクト名・
インスタンスの重複、`state_texts` の参照、オブジェクト設定そのものを検査します。
警告（無視された未知の列など）は EDE インポートと同様にイベントログに出力されます。

## Round trip and export warnings

エクスポート → インポートで同等の設定に戻ります。Excel のセルに収まらない値（32,767 文字超）は除外され、
イベントログに警告が出ます。`path` から読み込むファイルオブジェクトはそのパス参照としてエクスポートされ、これも警告になります。
