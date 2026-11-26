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
| `replay` | `file column interpolate loop offset` | CSV 時系列の再生（下記） |

**CSV 再生**（`replay`）: CSV の 1 列目がタイムスタンプ（経過時間 `HH:MM:SS` または秒、あるいは ISO 日時）、
残りの列が値の系列です。各ポイントが `file` と `column` を指定するので、1 つの CSV で複数ポイントを駆動できます
（ファイルは 1 回だけ解析）。相対パスは設定ファイルのディレクトリ基準です。再生時刻 0 は先頭行で、シミュレーション
時計に従って進む（`simulation.time_scale` に追従）。`interpolate: linear`（既定）または `step`（直前の行を保持）。
バイナリ / マルチステートは常に step 保持（`active` / `inactive` / `1` / `0`、状態番号）。`offset` で途中から開始
（`"06:00:00"`、秒、ISO CSV なら ISO 日時）、`loop: true` で繰り返し、そうでなければ最終値を保持。空セルは直前の値を
保持します。不正なタイムスタンプ・逆行する行・存在しない列は設定読込時にエラーになります。ポイント行に再生位置
（例 `replay 06:12:30 (26%)`）を表示。例: `configs/replay-example.yaml` と `configs/data/day-profile.csv`:

```csv
time,oat,rh,occupied,mode
00:00:00,13.8,71,inactive,1
08:00:00,17.2,64,active,2
19:00:00,20.2,56,inactive,1
24:00:00,13.8,71,inactive,1
```

```yaml
- {type: ai, name: OutdoorTemp, units: degreesCelsius,
   behavior: {type: replay, file: data/day-profile.csv, column: oat, loop: true, offset: "06:00:00"}}
- {type: bi, name: Occupied,
   behavior: {type: replay, file: data/day-profile.csv, column: occupied, loop: true, offset: "06:00:00"}}
```

CSV は `sme-bacnet-sim record` で実機から（読み取り専用で）記録できます。[クローン](cloning.md)を参照。

式はサンドボックス化された Python の式です。使用できる名前: デバイスのオブジェクト名、`t`（シミュレーション秒）、
`dt`、`hour`（シミュレーション時計、0–24）、他のデバイスを読み取る `pv("Device", "Object")`、および
`sin cos exp log sqrt pi abs min max round clamp random uniform noise gauss`。

**out of service** のオブジェクトは behavior に従わなくなります。これを利用して固定値やフォールトを注入できます。
UI からシミュレートされた入力に書き込むと、自動的に out of service になります。

## テンプレート

`lighting`、`split_ac`、`ahu`、`power_meter`、`env_sensor`、`pv_inverter`、`custom` — 詳細は
[sme_bacnet_sim/templates.py](https://github.com/smartedge-tech-dev/sme-bacnet-sim/blob/main/sme_bacnet_sim/templates.py) を参照してください。独自のテンプレートは約 20 行の関数で追加できます。

### ユーザーデバイステンプレート

ユーザーデバイステンプレートは `--templates-dir`、`$SME_BACNET_SIM_TEMPLATES`、`~/.sme-bacnet-sim/templates/`
のいずれか（先に指定されたもの）に置く YAML ファイルです。**デバイスを追加**ダイアログに組み込みテンプレートと並んで表示されます。
ファイルを編集したら **デバイステンプレート → ユーザーデバイステンプレートを再読込** で再起動なしに反映できます。

設定済みのデバイスから作るには、デバイスを選択してデバイスヘッダーの **デバイステンプレートとして保存** をクリックします。
名前（英数字と `_ . -`、既定値はデバイス名）を入力します。同名のテンプレートが既にある場合は上書きするか確認されます。
デバイスの展開済み設定が `<テンプレートディレクトリ>/<名前>.yaml` に書き込まれ（保存先はトーストに表示）、すぐに
**デバイスを追加** で選べます。HTTP では `POST /api/templates/from-device/{id}` で同じ操作ができます（[HTTP API](http-api.md) 参照）。
