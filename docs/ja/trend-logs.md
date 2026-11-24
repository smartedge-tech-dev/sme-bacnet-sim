# Trend Log

`type: tl`（または `trend-log`）は、**同一デバイス**内の別オブジェクトをログ記録する（ポーリングまたは変化時）BACnet Trend Log オブジェクトを作成し、
サンプルをリングバッファに保持します（最も古いレコードから破棄され、
`stop-when-full` は false です）:

```yaml
- {type: tl, name: RoomTemp_Log, log_object: RoomTemp, log_interval: 60, buffer_size: 1000}
- {type: tl, name: RoomTemp_Cov, log_object: RoomTemp, logging_type: cov, client_cov_increment: 0.5}
```

| キー | デフォルト | 備考 |
|---|---|---|
| `log_object` | （必須） | ログ対象オブジェクトの名前。デバイス内に存在する必要があります |
| `log_property` | `present-value` | 対象の任意の数値 / 列挙 / ブール型プロパティ |
| `log_interval` | `60` | **シミュレーション時間**の秒（BACnet の `log-interval` は 1/100 秒単位で報告されます）。ポーリングモードのみ |
| `logging_type` | `polled` | `polled` または `cov`（BACnet の `logging-type`） |
| `client_cov_increment` | 対象の `cov-increment` | `cov` モードのみ。ログ記録される実数値の最小変化量 |
| `buffer_size` | `1000` | リングバッファのサイズ |
| `enabled` | `true` | `enable` プロパティの初期値（BACnet 経由および UI からも書き込み可能） |

サンプルはシミュレーション時計で取得され、シミュレーションの日時のタイムスタンプが付与されるため、
`time_scale: 3600` なら実時間 1 時間で、設定した間隔の 1 日分の履歴が得られます。1 回の tick
が `log_interval` より長い場合、取りこぼした間隔は 1 つのサンプルにまとめられます。バッファは
**ReadRange**（位置指定、シーケンス番号指定、時刻指定、または範囲なしでレスポンスに収まる全件）で読み取ります。`log-buffer` は ReadProperty では読み取れません。
`record-count` に `0` を書き込むとログがクリアされます。
`split_ac` と `power_meter` のテンプレートにはそれぞれ Trend Log が 1 つ含まれています。EDE のエクスポート / インポートは Trend Log を引き継ぎます
（後述の EDE を参照）。

**COV ログ**（`logging_type: cov`）: 一定間隔でサンプリングする代わりに、ログ対象の値が前回のレコードから
increment 以上変化したとき（`client_cov_increment` が設定されていればそれ（読み戻しは `client-cov-increment`）、なければ present value をログする場合は対象の `cov-increment`、
それもなければ任意の変化。ブール / 列挙 / 整数値は任意の変化でログされます）、
または対象の status flags が変化したときにレコードが追加されます。最初のレコードは、バッファが空の状態でログが有効化されると直ちに（クリア後も同様に）取得されます。
変化はシミュレーションの tick ごとに 1 回検出され、シミュレーション時計でタイムスタンプが付与されます。`log-interval` は 0 と読み取れます。
サポートしていません: `triggered` ロギングタイプ、他デバイスのオブジェクトのログ記録（したがって
それらへの COV サブスクリプション / `cov-resubscription-interval` も）、およびバッファ内の log-status / time-change レコード。
