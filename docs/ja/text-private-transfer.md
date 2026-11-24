# TextMessage、PrivateTransfer、リスト要素サービス

- シミュレートデバイスが受信した **ConfirmedTextMessage / UnconfirmedTextMessage** はイベントログ（種別
  `text-message`：送信元アドレスとデバイス、priority、message class、本文）に記録されます。シミュレートデバイス
  からの送信は `POST /api/devices/{id}/text-message`
  `{"message": "...", "address": "100:2", "priority": "normal", "message_class": 5, "confirmed": false}`
  （`address` の既定はグローバルブロードキャスト `*:*` で、confirmed にはできません。`message_class` は数値または文字列）。
- **ConfirmedPrivateTransfer / UnconfirmedPrivateTransfer** はイベントログ（種別 `private-transfer`）に記録されます。
  confirmed 要求にはデバイスの `private_transfer` リストの宣言どおり応答します。`result: echo`（既定）は
  service parameters をそのまま result block として返し、`null` は result block なし、文字列 / 整数 / 実数 /
  真偽値はその値を返します。該当エントリがない場合は ConfirmedPrivateTransfer-Error `services` /
  `optional-functionality-not-supported` を返します。デバイスはサービス自体をサポートしており、その vendor /
  service number だけが未対応なので、サービス全体の欠如を意味する `unrecognized-service` reject ではなくこの
  エラーを使います。
- **AddListElement / RemoveListElement** は書き込み可能な任意のリスト型プロパティ（例：Notification Class の
  recipient-list、Calendar の date-list、Schedule の list-of-object-property-references、Life Safety Zone の
  zone-members）に対応します。要素は bacpypes3 のプロパティ型でデコードされ、新しいリストはリスト全体の
  WriteProperty とまったく同じように書き込まれます（同じチェックと後処理）。追加時、既存要素は無視します。
  エラー（Add/RemoveListElement-Error）：未知のオブジェクト / プロパティ、`services` / `property-is-not-a-list`
  （リストでない）、`property` / `property-is-not-an-array`（配列インデックス指定）、`write-access-denied`、
  `invalid-data-type`、削除時にリストにない要素は `services` / `list-element-not-found`（最初の該当要素の
  1 始まりの番号付き）。設定への書き戻し：zone-members と recipient-list（通知送信にも即反映）。date-list と
  list-of-object-property-references は WriteProperty と同様に実行中のオブジェクトだけが変わります。

```yaml
  - device_id: 1006
    name: Room-Sensor-101
    private_transfer:
      - {vendor_id: 999, service_number: 1}              # result: echo (default)
      - {vendor_id: 999, service_number: 2, result: 42}  # fixed value
```

非対応：PrivateTransfer パラメータのベンダー固有の意味（デコードしません）、ルーターデバイスでの TextMessage、
上記チェック以外に ASHRAE 135 が個々のプロパティについてのみ定める AddListElement / RemoveListElement の規則。
