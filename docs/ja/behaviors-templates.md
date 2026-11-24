# Behavior

| `type` | パラメータ | 例 |
|---|---|---|
| `sine` | `min max period phase noise` | 日周期や周期的な変動 |
| `random` | `min max` | 一様ノイズ |
| `random_walk` | `min max step` | ドリフトするセンサ |
| `expr` | `expr` | `"Zone1_Cmd"`、`"1.732 * Voltage * Current * PowerFactor / 1000"` |
| `follow` | `target tau noise` | 目標値への一次遅れ: `"SetPoint if OnOff else 30"` |
| `counter` | `rate` | 単位/秒を積算: `"Power / 3600"` → kWh |
| `pulse` | `rate` | Accumulator のパルス数/秒（端数は繰り越し）: `"ActivePower * 100 / 3600"` |

式はサンドボックス化された Python の式です。使用できる名前: デバイスのオブジェクト名、`t`（シミュレーション秒）、
`dt`、`hour`（シミュレーション時計、0–24）、他のデバイスを読み取る `pv("Device", "Object")`、および
`sin cos exp log sqrt pi abs min max round clamp random uniform noise gauss`。

**out of service** のオブジェクトは behavior に従わなくなります。これを利用して固定値やフォールトを注入できます。
UI からシミュレートされた入力に書き込むと、自動的に out of service になります。

## テンプレート

`lighting`、`split_ac`、`ahu`、`power_meter`、`env_sensor`、`pv_inverter`、`custom` — 詳細は
[sme_bacnet_sim/templates.py](https://github.com/smartedge-tech-dev/sme-bacnet-sim/blob/main/sme_bacnet_sim/templates.py) を参照してください。独自のテンプレートは約 20 行の関数で追加できます。
