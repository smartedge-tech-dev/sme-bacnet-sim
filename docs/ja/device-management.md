# デバイス管理サービス

各シミュレートデバイスは以下も提供します（bacpypes3 0.1.0 はこれらの多くをサーバ側で未実装または不完全なままにしているため、
シミュレータが `sme_bacnet_sim/engine.py` / `sme_bacnet_sim/devmgmt.py` で実装しています）:

- **COV increment のデフォルト**（`cov_increment` のないアナログオブジェクト）: `behavior` を持つポイント（毎 tick 変化する）には、
  そのスパンの 1 %（オブジェクトの `min` / `max`、なければ behavior の `min` / `max`）が設定され、それ以外は
  単位ごとのデフォルト（°C / kW / kWh / A は 0.1、% / %RH / V / m³/h は 0.5、W / Pa は 1、ppm / lx / W/m² は 5、
  Hz は 0.01。`sme_bacnet_sim/engine.py` の `_UNIT_COV` を参照）、それもなければ `0` になります。behavior のないポイントは `0`（= 任意の変化）のままです。
  上書きするには `cov_increment` を明示的に設定してください。
- **SubscribeCOV**（confirmed / unconfirmed、lifetime 付き）をすべての値オブジェクトで: presentValue が
  `covIncrement`（アナログ）以上変化したときに通知されます（behavior、BACnet 書き込み、UI のいずれによる変化でも）。また status flags
  （alarm、fault、out-of-service）が変化したときにも通知されます。**SubscribeCOVProperty** は任意のプロパティに対して、クライアントの COV increment
  （デフォルト: present-value ではオブジェクトの `covIncrement`）で動作し、通知にはプロパティと
  status flags が含まれます。
- 値オブジェクト（AI/AO/AV/BI/BO/BV/MSI/MSO/MSV、Accumulator、Pulse Converter）に対する **CreateObject / DeleteObject**: オブジェクトタイプ（最初の空き
  インスタンス）またはオブジェクト識別子で指定でき、任意の初期値を指定できます: object-name、present-value、description、
  units / cov-increment（アナログ）、active-text / inactive-text（バイナリ）、state-text（マルチステート、デフォルトは
  `State 1`、`State 2`）、out-of-service。作成されたオブジェクトは実行中の設定のデバイスの `objects` に追加され
  （保存 / エクスポートでも維持されます）、UI にも即座に表示されます。削除すると `objects` から取り除かれます。
  オブジェクトがテンプレート由来の場合、その名前はデバイスの `removed` リストに追加され、テンプレート展開時にスキップされます
  （テンプレートのオブジェクトを戻すには `removed` から名前を削除します。同名のオブジェクトを作成した場合も
  `removed` から外れます）。削除できないもの（`object` / `object-deletion-not-permitted`）:
  Device オブジェクト、Network Port、Trend Log、Schedule、Calendar、Notification Class、および
  Trend Log にログ記録されている、または Schedule から書き込まれている値オブジェクト。作成時のエラーは、失敗した
  要素番号付きの CreateObject-Error を使用します（`dynamic-creation-not-supported`、`object-identifier-already-exists`、`duplicate-name`、
  その他のプロパティには `write-access-denied`、`invalid-data-type`）。
- **TimeSynchronization / UTCTimeSynchronization**（デバイス宛て、またはルータ / ブロードキャスト宛て）: シミュレーション時計を
  受信した時刻を示すように移動します（UTC はホストのタイムゾーンで変換されます）。経過したシミュレーション時間は進み続け、Schedule は即座に再評価され、
  Trend Log は新しい時計で継続します。*シミュレーション → PC の時計に合わせる*（または `POST /api/simulation {"set_time": ...}`）は、UI から同じ操作を行います。
- **DeviceCommunicationControl** の enable / disable / disable-initiation（分単位の任意の継続時間付き）。継続時間は**実時計**で
  計測されます（標準では継続時間は実世界のタイムアウトであり、シミュレーション速度とは無関係です）。disable 中は、
  デバイスは DeviceCommunicationControl と ReinitializeDevice 以外をすべて無視し、何も送信しません（I-Am、COV、イベント通知なし）。
  disable-initiation はリクエストと Who-Is には応答しますが、それ以外の送信は行いません。UI のデバイスヘッダーには
  *通信を有効にする* ボタン付きで状態が表示されます。
- **ReinitializeDevice** の warmstart: 値は設定された初期値に戻り、priority array は
  relinquish され、out-of-service は解除され、behavior とアラームはリセットされ（イベント状態は normal、すべて acknowledge 済み）、
  通信は再有効化されます。Coldstart: 同じ処理に加えて Trend Log のバッファがクリアされます。その他の状態は
  `services` / `optional-functionality-not-supported` を返します。

これらのサービス用のデバイスキー:

```yaml
  - device_id: 1002
    name: AC-1F-East
    dcc_password: secret      # DeviceCommunicationControl password (default: none = not checked)
    reinit_password: boot     # ReinitializeDevice password (default: none = not checked)
    removed: [FilterAlarm]    # template objects deleted with DeleteObject (written by the simulator)
```

パスワードが誤っている場合は `security` / `password-failure` が返されます。
