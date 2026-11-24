# HTTP API

| メソッド | パス | |
|---|---|---|
| GET | `/api/state` | 全体のスナップショット |
| WS | `/ws` | スナップショット + 値の変化 + ログイベント |
| POST | `/api/devices/{id}/objects/{type:instance}/write` | `{"value": 1, "priority": 8}` |
| POST | `.../relinquish`, `.../oos` | `{"priority": 8}`, `{"out_of_service": true}` |
| POST | `/api/devices/{id}/objects/{type:instance}/ack` | オブジェクトのアラームの未確認遷移をすべて acknowledge |
| POST | `/api/devices/{id}/dcc` | `{"state": "enable"}`（または `disable` / `disable-initiation`） |
| POST | `/api/simulation` | `{"running": true, "time_scale": 60, "set_time": "2026-11-23T08:00:00"}`（すべて任意。タイムゾーンなしの時刻 = ローカル） |
| GET/PUT | `/api/config` | 設定全体（PUT は YAML または JSON テキストを受け付けます） |
| GET/PUT | `/api/network` | ネットワーク設定とローカルの IPv4 インターフェース（`{network, bind, config_path, interfaces}`）。PUT `{ip, port, network_number, virtual_network, mode, router, foreign_device}` で検証・再バインドし、`network:` セクションを書き戻します → `{ok, bind, saved, save_error}` |
| POST | `/api/config/import` | multipart アップロード: YAML / JSON / Excel（`.xlsx`）ファイル 1 つ、または EDE の CSV ファイル / zip（フィールド `file`、複数指定可） |
| GET | `/api/config/export?format=yaml\|json\|ede\|xlsx` | ダウンロード（`ede` = メイン CSV + ステートテキスト CSV の zip、`xlsx` = Excel ポイントリスト） |
| GET | `/api/config/xlsx-template` | 空の Excel ポイントリストテンプレート |
| POST/PUT/DELETE | `/api/devices`, `/api/devices/{id}/config` | デバイスの追加 / 編集 / 削除 |
| POST | `/api/devices/{id}/duplicate` | デバイスの複製（次の空き ID、`Name (copy)`）。`{"device_id", "name"}` を返す |
| GET | `/api/devices/{id}/objects/config?keys=analog-value:1,...` | コピー用のオブジェクト設定（テンプレートのオブジェクトも展開） |
| POST | `/api/devices/{id}/objects/paste` | `{"objects": [オブジェクト設定, ...]}` → `{"pasted": [{name, key}], "rejected": [{name, reason}]}` |
| GET | `/api/devices/{id}/objects/{type:instance}/properties` | 全プロパティ（`device:{id}` = デバイスオブジェクト）: `[{id, name, value, datatype, writable, editable, kind}]` |
| PUT | `/api/devices/{id}/objects/{type:instance}/properties/{property}` | `{"value": 21.5, "priority": 8}`（基本型のみ。`null` + priority で解除） |
| GET | `/api/history/{id}/{type:instance}` | トレンドサンプル |
| GET | `/api/devices/{id}/trendlog/{instance}` | Trend Log バッファ `[[timestamp, value], ...]`（シミュレーション時計） |
| POST | `/api/devices/{id}/trendlog/{instance}/enable` | `{"enabled": true}` |
| POST | `/api/devices/{id}/program/{instance}/change` | `{"request": "halt"}`（load / run / halt / restart / unload / ready） |
| POST | `/api/devices/{id}/text-message` | `{"message": "...", "address": "100:2", "priority": "normal", "message_class": 5, "confirmed": false}`（address の既定はグローバルブロードキャスト） |
| POST | `/api/devices/{id}/life-safety/{type:instance}/state` | `{"state": "alarm"}`（Life Safety Point の Tracking_Value） |
