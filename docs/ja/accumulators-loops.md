# Accumulator、Pulse Converter、Loop

```yaml
- {type: acc, name: EnergyPulses, units: kilowatt-hours, scale: 0.01, max: 99999999,
   behavior: {type: pulse, rate: "ActivePower * 100 / 3600"}}
- {type: pc, name: EnergyFromPulses, input_object: EnergyPulses, scale_factor: 0.01, units: kilowatt-hours}
- type: loop
  name: SupplyTempLoop
  controlled_object: SupplyTemp      # controlled-variable-reference (present-value)
  manipulated_object: CoolValve      # manipulated-variable-reference (present-value)
  setpoint_object: SupplyTempSP      # or a fixed setpoint: 16
  proportional_constant: 8
  integral_constant: 0.2
  min: 0                             # minimum-output
  max: 100                           # maximum-output
  units: percent                     # output-units
  priority_for_writing: 10
```

| タイプ | キー |
|---|---|
| `acc`（Accumulator、23） | `value`（unsigned のカウント）、`units`、`scale`（Scale、float scale、既定 1）、`max`（Max_Pres_Value、既定 4294967295。超えるとカウントは 0 に戻る）、`prescale`（`[multiplier, modulo_divide]`） |
| `pc`（Pulse Converter、24） | `value`、`units`、`scale_factor`（既定 1）、`input_object`（同一デバイスの Accumulator → Input_Reference）、`cov_increment` |
| `loop`（Loop、12） | `controlled_object`、`manipulated_object`、`setpoint` または `setpoint_object`、`proportional_constant`（既定 1）、`integral_constant`（1/s、既定 0）、`derivative_constant`（s、既定 0）、`bias`（既定 0）、`action`（`direct` / `reverse`、既定 `direct`）、`update_interval`（シミュレーション秒、既定 1。Update_Interval プロパティは ms）、`min` / `max`（出力上下限、既定 0 / 100）、`units`（Output_Units）、`priority_for_writing`（既定 16）、`cov_increment` |

- **Accumulator**: 任意の behavior で駆動できます。`pulse` behavior は毎秒 `rate` パルスを加算します。
- **Pulse Converter**（`input_object` あり）: 毎 tick、Accumulator のカウント増分（回り込みを考慮）×
  Scale_Factor を Present_Value に加算し、Count に Accumulator のカウントを表示します。`input_object` が
  なければ通常の Real 値オブジェクトです（behavior が使えます）。
- **Loop**（教科書的な PID、シミュレーション時計で Update_Interval ごと）: `e = PV − setpoint`（direct）
  または `setpoint − PV`（reverse）、`output = bias + Kp·e + Ki·∫e dt + Kd·de/dt` を Minimum_Output ..
  Maximum_Output に制限し、出力飽和中は積分を止めます（anti-windup）。出力は Loop の Present_Value と操作量
  オブジェクト（コマンド可能なら Priority_For_Writing の priority array、そうでなければ present value）に
  書き込まれます。定数、setpoint、action、上下限、更新周期、書き込み優先度は WriteProperty で変更できます。
  `setpoint_object` がある場合、Setpoint はそのオブジェクトの値に追従します。Out of service 中は演算も出力
  書き込みも行いません。UI には出力と PV / SP が表示されます。
- **COV**: bacpypes3 の定義どおり、Pulse Converter は COV increment 基準、Loop は汎用基準
  （present-value / status-flags）を使います。bacpypes3 には Accumulator の COV 基準がないため、
  Accumulator への SubscribeCOV は利用できません（SubscribeCOVProperty は使えます）。
- **CreateObject** で Accumulator と Pulse Converter（input reference なし）を作成できます。Loop は設定
  ファイルでのみ宣言できます。**DeleteObject** は Pulse Converter や Loop から参照されているオブジェクトを
  拒否します。
- **EDE**: Accumulator と Pulse Converter はエクスポート（単位コード。Accumulator の `max` 列は
  Max_Pres_Value）/ インポートされます。Loop はエクスポートされますが、インポート時は警告付きでスキップされます
  （EDE は参照や PID 定数を持たないため）。

Not supported: Prescale の適用（値を保持するのみ）、Accumulator の Value_Set / Value_Before_Change /
Value_Change_Time / Logging_Record / Pulse_Rate とリミット監視、Pulse Converter の Adjust_Value の意味論
（通常の書き込み可能プロパティとして扱い、Count と Present_Value は調整しません）、Count_Before_Change /
Count_Change_Time / Update_Time、COV_Period による定期通知、これら 3 タイプの intrinsic reporting
（`alarm` はエラー）、他デバイスや Present_Value 以外のプロパティへの参照。
