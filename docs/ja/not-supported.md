# 非対応事項

## [Foreign Device 登録（サブネット越え）](foreign-device.md)

Not supported：`foreign_device` と `mode: bbmd` の併用、BBMD のホスト名指定（IPv4 アドレスのみ）、
BBMD のテーブルの読み書き（Read-Broadcast-Distribution-Table、Read-Foreign-Device-Table など）。

## [Accumulator、Pulse Converter、Loop](accumulators-loops.md)

Not supported: Prescale の適用（値を保持するのみ）、Accumulator の Value_Set / Value_Before_Change /
Value_Change_Time / Logging_Record / Pulse_Rate とリミット監視、Pulse Converter の Adjust_Value の意味論
（通常の書き込み可能プロパティとして扱い、Count と Present_Value は調整しません）、Count_Before_Change /
Count_Change_Time / Update_Time、COV_Period による定期通知、これら 3 タイプの intrinsic reporting
（`alarm` はエラー）、他デバイスや Present_Value 以外のプロパティへの参照。

## [File と Program](files-programs.md)

Not supported：過渡状態 `loading`・`waiting`・`unloading`、現在の状態で無効な要求の拒否、実際のプログラム実行や
異常（`normal` 以外の Reason_For_Halt）、File_Size 書き込みによる切り詰め、Archive の意味づけ（単なる書き込み可能
フラグ）、AtomicWriteFile の Record_Count と送信レコード数の整合チェック。これらの厳密な規定は有償の ASHRAE 135
原文にしかありません。

## [Trend Log](trend-logs.md)

サポートしていません: `triggered` ロギングタイプ、他デバイスのオブジェクトのログ記録（したがって
それらへの COV サブスクリプション / `cov-resubscription-interval` も）、およびバッファ内の log-status / time-change レコード。

## [Schedule と Calendar](schedules-calendars.md)

サポートしていません: シミュレータ外のデバイス上の対象への書き込み（ネットワーク WriteProperty なし）、および
クライアントが書き込んだ `list-of-object-property-references` の再読み取り（対象は設定ファイルから取得されます）。

## [アラーム（intrinsic reporting）](alarms.md)

サポートしていません: acknowledgment notification（通知タイプ `ack-notification`）。AcknowledgeAlarm には応答し、
Acked_Transitions も更新しますが、受信先への通知は送信されません。また、上記の事前検証を超える WritePropertyMultiple の厳密な all-or-nothing セマンティクス（適用済みの書き込みのロールバック）にも対応していません。SME BACnetSim は無償で、
公開情報のみから構築されています。有償の ASHRAE 135 の本文からしか仕様を確定できない挙動は対象外としています。

## [イベントエンロールメント（algorithmic reporting）](event-enrollments.md)

Not supported：イベントタイプ `floating-limit`、`change-of-value` およびその他すべて（正確なアルゴリズムは ASHRAE 135 にのみ
規定）、イベントエンロールメントの故障検出（`fault` 状態 / change-of-reliability なし）、他デバイスのオブジェクトや
present-value 以外のプロパティの監視、BACnet 書き込みによる `event-type` / `object-property-reference` の変更、
CreateObject / DeleteObject によるイベントエンロールメントの作成 / 削除。イベントエンロールメントが監視している値オブジェクトは
削除できません。

## [Life Safety Point と Life Safety Zone](life-safety.md)

非対応：change-of-life-safety イベント通知（alarm-values、life-safety-alarm-values、fault-values とイベント
プロパティは評価しません）、状態の重大度順序とモード依存の遷移、maintenance-required / direct-reading /
setting の動作、CreateObject / DeleteObject による Life Safety オブジェクトの作成 / 削除。

## [TextMessage、PrivateTransfer、リスト要素サービス](text-private-transfer.md)

非対応：PrivateTransfer パラメータのベンダー固有の意味（デコードしません）、ルーターデバイスでの TextMessage、
上記チェック以外に ASHRAE 135 が個々のプロパティについてのみ定める AddListElement / RemoveListElement の規則。
