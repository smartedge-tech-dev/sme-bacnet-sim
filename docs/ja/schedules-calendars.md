# Schedule と Calendar

`type: sch`（または `schedule`）は、同一デバイスまたは**他のシミュレートされたデバイス**のオブジェクトに値を書き込む BACnet Schedule オブジェクトを作成します。
`type: cal`（または `calendar`）は、列挙した日付で `present-value` が true になる Calendar オブジェクトを作成します。

```yaml
- {type: cal, name: Holidays, dates: ["2026-12-25", {from: "2026-12-29", to: "2027-01-03"}, "*-01-01"]}
- type: sch
  name: Light_Sch
  targets:                      # written via list-of-object-property-references
    - Zone1_Cmd                 # object of this device
    - {device: AHU-1, object: Fan_Cmd}            # object of another simulated device (name or device id)
    - {device: 300100, object: "binary-value:4"}  # device outside the simulator: listed, never written
  priority_for_writing: 16
  default: "OFF"                # schedule-default
  weekly:
    weekdays: [{time: "08:00", value: "ON"}, {time: "18:00", value: "OFF"}]
    sat: [{time: "09:00", value: "ON"}, {time: "12:00", value: null}]   # null = back to default
  exceptions:
    - {calendar: Holidays, priority: 10, times: [{time: "00:00", value: "OFF"}]}
    - {date: "2026-11-03", priority: 5, times: [{time: "10:00", value: "ON"}]}
    - {date: {from: "2026-08-10", to: "2026-08-14"}, priority: 6, times: [{time: "00:00", value: "OFF"}]}
    - {date: {weeknday: ["*", 6, 5]}, priority: 8, times: [{time: "13:00", value: "OFF"}]}  # last Friday
  effective_period: {from: "2026-01-01", to: "2027-12-31"}   # optional, default always
```

| キー | デフォルト | 備考 |
|---|---|---|
| `weekly` | — | キーは `mon`..`sun`、または `weekdays` / `weekend` / `daily`。それぞれ `{time: "HH:MM[:SS]", value}` のリスト |
| `exceptions` | — | 特殊イベント: `date`（Calendar の `dates` と同じ形式: `*` ワイルドカード付きの `YYYY-MM-DD`、`{from, to}` 範囲、または `{weeknday: [...]}`）か `calendar`（Calendar オブジェクト名）のいずれか 1 つ、`priority` 1–16（1 が優先）、`times` |
| `default` | 0 / `OFF` / 1 | schedule-default。`weekly` / `exceptions` の少なくとも一方が必要です |
| `targets` | なし | 出力または値オブジェクト（すべて同種）: 名前（このデバイス）または `{device, object}`。`device` はシミュレートされたデバイスの名前または ID、`object` は名前または `type:instance`（`av:3`、`binary-output:1`）。シミュレータにない device ID には `object: type:instance` が必要です。`list-of-object-property-references` には `deviceIdentifier` 付きで現れますが、スキップされ（起動時に 1 回ログ出力）、ネットワーク経由では書き込まれません |
| `priority_for_writing` | `16` | コマンド可能な対象に使用する priority-array のスロット |
| `effective_period` | 常時 | `{from, to}`。期間外では Schedule は値を保持したまま何も書き込みません |
| `dates`（Calendar） | `[]` | 日付、`{from, to}` 範囲、または `{weeknday: [month, week-of-month, day-of-week]}`（`*` = 任意。month 13 / 14 = 奇数月 / 偶数月。week 1–5 = 1–7 日 … 29–31 日、6 = 月の最後の 7 日間、7–9 = それより前の 7 日ブロック。day 1 = 月曜日） |

値の型は対象に従います。アナログ → REAL、バイナリ → ENUMERATED（`0/1`、`true/false`、`ON/OFF`、
`active/inactive`、または対象のテキスト）、マルチステート → UNSIGNED の状態番号。対象がない場合、
値は REAL になります。時刻は引用符で囲んでください（`"18:00"`）。引用符がないと YAML 1.1 は `18:00` を数値 1080 として解釈します
（それでも理解はされますが、引用符を付けた方が明確です）。

Schedule は**シミュレーション時計**で動作するため、`time_scale` で早送りできます。bacpypes3 自身の Schedule
インタプリタは実時計と asyncio タイマーを使うため、シミュレータは Schedule オブジェクトと
評価ルールを維持しつつ、シミュレーションの日時から tick ごとに再評価します。値が変化したとき、または
weekly / exception スケジュールの時刻エントリに達したとき（値が同じでも。これによりスケジュールされた動作がオペレータの変更を上書きします）、
Schedule の `present-value` が設定され、その値が各対象に
`priority_for_writing` で書き込まれます（コマンド不可の値オブジェクトには `present-value` を直接設定）。スケジュールされた
動作の間には何も書き込まれません。したがって、クライアントからの relinquish は通常どおり動作し、Schedule は
次の時刻エントリで再び書き込みます。他のシミュレートされたデバイス内の対象には、そのデバイスのオブジェクトへ直接書き込まれます。
対象のデバイスの ReinitializeDevice は、スケジュールされた値を再コマンドします。COV サブスクリプションは維持されます。`weekly-schedule`、`exception-schedule`、
`schedule-default` は BACnet 経由で書き込み可能で、次の tick で反映されます（型が誤った値は
`reliability` を `configuration-error` にします）。例外エントリには日付、日付範囲、weekNDay、
Calendar 参照を使用できます。Calendar の `date-list` も書き込み可能です。`list-of-object-property-references` を書き込むと対象が変わります（このデバイスまたは他のシミュレートされたデバイスにある Schedule と同種の出力 / 値オブジェクトの present-value、またはシミュレータ外のデバイス。それ以外は `value-out-of-range`）。どちらも設定に保持されます（Save / Export）。Schedule 自身の
`present-value` へのクライアント書き込み（Schedule のデータ型であること。そうでなければ `invalid-data-type`）は、すべての対象へ
`priority_for_writing` で転送され、次のスケジュール時刻エントリまで保持されます。`out-of-service` の設定有無にかかわらず受け付けられます。

サポートしていません: シミュレータ外のデバイス上の対象への書き込み（ネットワーク WriteProperty なし）。

`lighting` テンプレートには `Zone1_Cmd` を切り替える Schedule（平日 08:00 ON、18:00 OFF）があり、
`split_ac` テンプレートには `OnOff` 用の Schedule（平日 09:00–18:00）があります。テンプレートパラメータ
`schedule: false` で無効にできます。UI では Schedule と Calendar が現在値と次の遷移とともに一覧表示され、
行をクリックすると weekly / exception の表が表示されます。EDE エクスポートではオブジェクトタイプ 17 / 6 として出力され、EDE インポートでは
スキップされます。
