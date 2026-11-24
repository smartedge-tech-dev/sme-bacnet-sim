# SME BACnetSim

[English](README.md) | **日本語** | [简体中文](README.zh-CN.md)

ライブ Web UI を備えた BACnet/IP デバイスシミュレータです。照明コントローラ、エアコン、AHU、
電力メータ、センサ、PV インバータ、あるいは YAML で記述した任意のデバイスをシミュレートし、実際の BACnet クライアント
（Yabe、Niagara、自作の EMS など）が読み取り・操作している間、その値の変化をブラウザ上で確認できます。

- **1 つのポートで多数のデバイス。** 内蔵の BACnet ルータが UDP 47808 を占有し、シミュレートされる各デバイスは
  その背後の仮想ネットワーク（デフォルトはネットワーク 100）に配置されます。クライアントは 1 回の Who-Is ですべてを検出できます。
- **リアルな挙動。** エアコンが ON のとき室温は設定温度に追従し、電力量は電力を積算し、
  照明はフィードバックと電力を報告し、PV 出力は日変化カーブに従って出力抑制の上限を守ります。
- **本物の BACnet セマンティクス。** 16 レベルの Priority Array と relinquish を備えたコマンド可能な出力、
  out-of-service による上書き、COV increment、Device / Network Port オブジェクトに対応します。
- **設定可能。** YAML / JSON のインポート・エクスポート、ブラウザ上での任意デバイスの YAML 編集、
  テンプレートからのデバイス追加、設定ファイルへの保存が行えます。
- **ライブ UI。** 値は WebSocket でストリーミングされ、ポイントごとのトレンドグラフと、BACnet および UI からの書き込みのイベントログを備えています。
- **英語、日本語、簡体字中国語。** UI はブラウザの言語に従います。表示 → 言語 で切り替えられます。

[bacpypes3](https://github.com/JoelBender/BACpypes3)（asyncio ベースの BACnet スタックで、BACnet/IP、
IPv6、BACnet/SC をサポート）と FastAPI の上に構築されています。フロントエンドのビルド手順は不要です。

SME BACnetSim は無償の MIT ライセンスで、[smart-edge (智届科技)](https://smartedge-tech.com) が開発しています —
カスタム開発も承っています。[商用サポートとカスタム開発](#商用サポートとカスタム開発) をご覧ください。

## クイックスタート

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m sme_bacnet_sim --config configs/demo-building.yaml
```

http://127.0.0.1:8080/ を開きます。オプション:

| オプション | 意味 |
|---|---|
| `-c, --config FILE` | YAML/JSON 設定ファイル（デフォルトは `configs/demo-building.yaml`） |
| `--ip 192.168.1.10/24` | BACnet/IP 用の NIC アドレス（デフォルト: 自動検出、/24） |
| `--bacnet-port 47808` | BACnet/IP の UDP ポート |
| `--foreign-bbmd 192.168.2.1[:47808]` | この BBMD に Foreign Device として登録（設定ファイルより優先） |
| `--foreign-ttl 300` | Foreign Device の Time-to-Live（秒、設定ファイルより優先） |
| `--host 0.0.0.0 --port 8080` | Web UI のバインドアドレス（デフォルトは localhost のみ） |

### BACnet クライアントの接続

クライアントからは、ルータ（`device 4194000`）が `<ip>:47808` に、シミュレートされたデバイスがそのルータ経由の
`100:1`、`100:2`（ネットワーク 100、MAC 1、2…）といったアドレスに見えます。Yabe では
*Add device → BACnet/IP over UDP* を選び、続けて *Who-Is* を実行します。

> **同一 PC での注意:** Windows では、同じマシン上のクライアントがブロードキャスト応答
> （Who-Is/I-Am）を受信できないことがあります（ユニキャストは動作します）。クライアントを別のマシンで実行するか、シミュレータをクライアントとは別の NIC
> にバインドするか、`network.mode: bbmd` を設定してクライアントを Foreign Device として登録してください。

### Foreign Device 登録（サブネット越え）

別サブネットのクライアントから使う場合、ルーターのポートを既存の BBMD に Foreign Device として登録できます：
`network.foreign_device: {bbmd: "<ipv4>[:port]", ttl: <秒>}` または `--foreign-bbmd` / `--foreign-ttl`
（コマンドラインが優先。TTL の既定は 300 秒、ポートは 47808）。登録は bacpypes3 の foreign リンク層を使い、
TTL ごとに更新、応答がない間は再試行し、停止・再読み込み時に解除（TTL 0）します。結果（登録済み / NAK /
10 秒以内に応答なし / 期限切れ）はイベントログに記録され、ステータスバーに `FD → <bbmd> (…)` と表示されます。
スナップショット API では `network.foreign_device` で取得できます。

Not supported：`foreign_device` と `mode: bbmd` の併用、BBMD のホスト名指定（IPv4 アドレスのみ）、
BBMD のテーブルの読み書き（Read-Broadcast-Distribution-Table、Read-Foreign-Device-Table など）。

## 設定

```yaml
network:
  ip: auto                # or "192.168.1.10/24"
  port: 47808
  network_number: 1       # IP-side network number
  virtual_network: 100    # network number of the simulated devices
  mode: normal            # or bbmd
  # foreign_device: {bbmd: "192.168.2.1:47808", ttl: 300}   # register with an external BBMD
  router: {device_id: 4194000, name: SME-BACnetSim-Router}

simulation:
  tick_seconds: 1.0
  time_scale: 1.0         # 60 = 1 simulated minute per second
  history_size: 600       # trend samples kept per point

devices:
  - device_id: 1002
    name: AC-1F-East
    template: split_ac             # optional
    params: {rated_kw: 2.8}        # template parameters
    objects:                       # add objects, or override template objects by name
      - {name: SetPoint, type: av, value: 24.0, commandable: true}
```

### オブジェクト

| キー | 備考 |
|---|---|
| `type` | `ai ao av bi bo bv msi mso msv acc pc loop file prog tl sch cal nc ee`（または `analog-input`、`trend-log`、`schedule`、`calendar`、`notification-class`、`event-enrollment` などの正式名） |
| `instance` | 任意。タイプごとに自動採番 |
| `name`, `description` | `name` は式の中の変数名にもなります |
| `units` | BACnet の engineering units（例: `degrees-celsius`、`kilowatts`、`percent`） |
| `value` | 初期値（バイナリ: 0/1、マルチステート: 1 始まりのインデックス） |
| `states` | マルチステートのテキスト |
| `active_text`, `inactive_text` | バイナリのテキスト（`"ON"`/`"OFF"` は引用符で囲んでください — YAML では真偽値として解釈されます） |
| `commandable` | `av/bv/msv` 用。出力オブジェクトは常にコマンド可能です |
| `min`, `max`, `cov_increment` | アナログの上下限と COV increment |
| `behavior` | 値のシミュレーション方法（後述） |
| `log_object`, `log_property`, `log_interval`, `logging_type`, `client_cov_increment`, `buffer_size`, `enabled` | Trend Log 専用（後述） |
| `weekly`, `exceptions`, `default`, `targets`, `priority_for_writing`, `effective_period` | Schedule 専用（後述） |
| `dates` | Calendar 専用（後述） |
| `scale`, `prescale` | Accumulator 専用（後述） |
| `scale_factor`, `input_object` | Pulse Converter 専用（後述） |
| `controlled_object`, `manipulated_object`, `setpoint`, `setpoint_object`, `proportional_constant`, `integral_constant`, `derivative_constant`, `bias`, `action`, `update_interval` | Loop 専用（後述） |
| `file_type`, `access`, `content`, `path`, `read_only`, `program_state`, `instance_of`, `program_location` | File / Program 専用（後述） |
| `monitored_object`, `event_type`, `event_parameters`, `notification_class`, `event_enable`, `notify_type`, `time_delay`, `time_delay_normal` | Event Enrollment 専用（後述） |

#### Accumulator、Pulse Converter、Loop

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

#### File と Program

```yaml
- {type: program, name: AHU-Sequence, instance_of: AHU-Seq-v2, program_state: running}
- type: file
  name: MaintenanceLog
  file_type: text/plain            # File_Type (MIME type)
  access: record                   # stream (default) | record
  content: |-                      # or: path: logs/maintenance.txt (relative to the config file)
    2026-04-01 filter replaced
    2026-10-01 belt tension checked
- {type: file, name: Firmware, file_type: application/octet-stream, path: fw.bin, read_only: true}
```

| 種別 | キー |
|---|---|
| `file`（File, 10） | `file_type`（既定 `text/plain`）、`access`（`stream` / `record`）、`content`（テキスト）または `path`（起動時に読み込むファイル、設定ファイルからの相対パス）、`read_only`（既定 false） |
| `program`（Program, 16） | `program_state`（初期値 `idle` / `running` / `halted`、既定 `idle`）、`instance_of`（既定はオブジェクト名）、`program_location` |

ファイル内容はメモリ上に保持します。stream アクセスはバイト列、record アクセスは 1 行を 1 レコード（改行は含まない）
として扱います。File_Size はバイト数（record アクセスではレコード長の合計）、Record_Count はレコード数です。
**AtomicReadFile / AtomicWriteFile** は両アクセス方式に対応します。開始位置 / レコード `-1` は末尾への追記、末尾を
超える開始位置は `services / invalid-file-start-position`、アクセス方式の不一致は `invalid-file-access-method`、
Read_Only のファイルは `file-access-denied`、File 以外のオブジェクトは `inconsistent-object-type`、存在しない
オブジェクトは `object / unknown-object` を返します。書き込みで File_Size / Record_Count と Modification_Date
（シミュレーション時計）を更新します。`content` で定義したファイルへの書き込み内容は設定に反映されるため、**Save** /
エクスポートで保存されます（UTF-8 として有効な場合のみ）。`path` のファイルはメモリ上でのみ変更され、ディスク上の
ファイルには書き込みません。File_Size、Modification_Date、File_Access_Method、Record_Count、Read_Only は
クライアントから書き込めません（`write-access-denied`）。

Program：Program_Change への書き込みは即座に適用され、`ready` に戻ります。`load`・`run`・`restart` → `running`、
`halt` → `halted`（Reason_For_Halt `normal`、Description_Of_Halt "halted by request"）、`unload` → `idle`、
`ready` → 変化なし。どの状態でもすべての要求を受け付けます。UI には状態と Program_Change メニュー
（`POST /api/devices/{id}/program/{instance}/change`）を表示します。Program_State、Reason_For_Halt、
Description_Of_Halt、Instance_Of はクライアントから書き込めません。

EDE はファイル内容・ファイル種別・アクセス方式を持たないため、インポートしたファイルは空の stream ファイルになります
（警告あり）。Program は名前のみインポートします。

Not supported：過渡状態 `loading`・`waiting`・`unloading`、現在の状態で無効な要求の拒否、実際のプログラム実行や
異常（`normal` 以外の Reason_For_Halt）、File_Size 書き込みによる切り詰め、Archive の意味づけ（単なる書き込み可能
フラグ）、AtomicWriteFile の Record_Count と送信レコード数の整合チェック。これらの厳密な規定は有償の ASHRAE 135
原文にしかありません。

#### Trend Log

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

#### Schedule と Calendar

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

#### アラーム（intrinsic reporting）

`type: nc`（または `notification-class`）は Notification Class オブジェクトを作成します。その `instance` が
通知クラス番号です。Web UI はデバイスのオブジェクト一覧に通知クラスを表示します（読み取り専用:
優先度、ack-required フラグ、受信先。編集は設定ファイルで行います）。

| キー | 意味 |
|---|---|
| `priority` | `[to-offnormal, to-fault, to-normal]`、デフォルトは `[100, 100, 200]` |
| `ack_required` | 3 つのフラグ、デフォルトは `[true, true, false]` |
| `recipients` | `{device: <id>` および/または `address: "<net>:<mac>" \| "<ip>:<port>", process_id, confirmed, transitions: [3 flags], from_time, to_time, days}` のリスト |

`device` のみで指定された受信先は Who-Is で解決されます（他のシミュレートされたデバイスなら直接。それ以外の場合、
Who-Is はルータ経由で送出されるため、受信先はシミュレータの UDP ポートで待ち受けている必要があり、通常は
別ホスト上の BMS です）。`address`（`"<ip>:<port>"` は BACnet/IP 側のステーションを意味します）を指定すると検索は省略されます。

任意の値オブジェクトに、intrinsic reporting を有効にする `alarm` ブロックを持たせることができます:

```yaml
- type: ai
  name: RoomTemp
  alarm: {notification_class: NC1, high_limit: 30, low_limit: 15, deadband: 0.5, time_delay: 60}
- {type: bi, name: FilterAlarm, alarm: {notification_class: 1, alarm_value: active}}
- {type: msi, name: Status, states: [Stopped, Running, Fault], alarm: {notification_class: 1, fault_values: [Fault]}}
```

| キー | 意味 |
|---|---|
| `notification_class` | 同一デバイス内の notification-class オブジェクトの名前またはインスタンス |
| `high_limit`, `low_limit`, `deadband`, `limit_enable` | アナログ（OUT_OF_RANGE）。`limit_enable` `[low, high]` のデフォルトは設定されている上下限 |
| `alarm_value` | バイナリ（CHANGE_OF_STATE）: `active` / `inactive` |
| `alarm_values`, `fault_values` | マルチステート: 状態番号またはテキスト。fault 値になるとオブジェクトは `fault` になります |
| `time_delay`, `time_delay_normal` | **シミュレーション時間**の秒（デフォルトは 0 / `time_delay`） |
| `event_enable` | `[to-offnormal, to-fault, to-normal]`、デフォルトはすべて true |
| `notify_type` | `alarm`（デフォルト）または `event` |

イベント状態はシミュレーション時計で評価されます（時間遅延は速度に従い、一時停止中は止まります。
書き込みは即座に評価されます）。遷移は Event_State、Event_Time_Stamps、Acked_Transitions、
および in-alarm ステータスフラグを更新し、受信先へ Confirmed / UnconfirmedEventNotification として送信され、イベントログにも
表示されます。シミュレータは AcknowledgeAlarm、GetEventInformation、GetAlarmSummary、
GetEnrollmentSummary に応答します（オブジェクトの通知クラスの受信先 + プロセス識別子による enrollment フィルタを含むすべてのフィルタ）。Web UI には行ごとのアラームバッジ、
**確認** ボタン、ヘッダーのアクティブアラーム数、および 表示 → アラーム が用意されています。`split_ac`、`ahu`、
`power_meter` テンプレートは `NC1`（受信先なし）といくつかのアラームを追加します。除外するにはテンプレートパラメータ
`alarms: false` を設定してください。`split_ac` の RoomTemp の上限（テンプレートパラメータ `high_limit`、
デフォルト 35 °C）は、テンプレートの外気温ピーク（33 °C）を上回るオーバーヒートアラームであるため、エアコンがスケジュールに従っている間、デモはアラームなしで起動・動作します。
アラームを確認するには、クライアントから `high-limit`（例: 28）を書き込んでください。

`event-enable`、`limit-enable`、`high-limit`、
`low-limit`、`deadband`、`time-delay`、`time-delay-normal`、`notification-class`（デバイスの notification-class
オブジェクトである必要があります）、`alarm-value` / `alarm-values` への BACnet 書き込み（WriteProperty / WritePropertyMultiple）は
反映され、設定にも書き込まれるため、
保存 / エクスポートでも維持されます。`acked-transitions` は読み取り専用です（WriteProperty は `write-access-denied` を返します）。

WritePropertyMultiple はまずすべての項目を検証し（オブジェクトの存在、プロパティの存在、配列インデックス、データ型、上記の
アラームプロパティのルール、コマンド可能なオブジェクトの Priority_Array）、1 つでも失敗した場合は何も書き込みません。
エラーは最初に失敗したオブジェクト / プロパティを示します。オブジェクト自身の書き込みフック内でのみ行われる値チェック
（例: Trend Log / Schedule の範囲チェック）は書き込み中に実行されるため、そのような失敗では、リクエストの先行する
項目が適用されたままになることがあります。

bacpypes3 0.1.0 は、リストが空の GetAlarmSummary / GetEnrollmentSummary ACK（何にも一致しないフィルタ）をデコードできず、
`invalid-tag` として報告します。シミュレータ自身は空の ACK を正しくエンコードし、
同一プロセス内で動作する bacpypes3 クライアント向けにデコーダへパッチを当てます（`sme_bacnet_sim/alarm.py`）。
他の bacpypes3 0.1.0 クライアントは、同じ修正を適用するまで同じエラーになります。
すでに `offnormal` のマルチステートオブジェクトが別のアラーム値に変化すると、`time_delay` の後に新しい
`offnormal -> offnormal` 遷移（および通知）が発生します。

制限事項: bacpypes3 自身の intrinsic reporting アルゴリズムは実時計で動作するため、シミュレータは
独自のものを使用します（`sme_bacnet_sim/alarm.py` を参照）。

サポートしていません: acknowledgment notification（通知タイプ `ack-notification`）。AcknowledgeAlarm には応答し、
Acked_Transitions も更新しますが、受信先への通知は送信されません。また、上記の事前検証を超える WritePropertyMultiple の厳密な all-or-nothing セマンティクス（適用済みの書き込みのロールバック）にも対応していません。SME BACnetSim は無償で、
公開情報のみから構築されています。有償の ASHRAE 135 の本文からしか仕様を確定できない挙動は対象外としています。

#### イベントエンロールメント（algorithmic reporting）

`type: ee`（または `event-enrollment`）は Event Enrollment オブジェクトを作成します。同じデバイスの別の値オブジェクトの
present-value を監視し、Notification Class 経由で通知するため、`alarm` ブロックを持たないポイント（テンプレートの温度など）でも
アラームを出せます：

```yaml
- type: ee
  name: RoomTempWatch
  monitored_object: Temperature
  event_type: out-of-range
  event_parameters: {low_limit: 18, high_limit: 28, deadband: 0.5}
  notification_class: RoomAlarms
  time_delay: 60
- {type: ee, name: ModeWatch, monitored_object: OperationMode, event_type: change-of-state,
   event_parameters: {alarm_values: [Maintenance]}, notification_class: 1, notify_type: event}
```

| キー | 意味 |
|---|---|
| `monitored_object` | 同じデバイスの値オブジェクト名（Object_Property_Reference = その present-value） |
| `event_type` | `out-of-range`（アナログ、Accumulator を除く）または `change-of-state`（バイナリ / マルチステート） |
| `event_parameters` | out-of-range：`low_limit`、`high_limit`（両方必須・常に有効）、`deadband`；change-of-state：`alarm_values`（状態番号またはテキスト、バイナリは `active` / `inactive`） |
| `notification_class` | 同じデバイスの notification-class オブジェクトの名前またはインスタンス |
| `time_delay`、`time_delay_normal` | **シミュレーション**秒（既定 0 / `time_delay`）；`time_delay` は Event_Parameters の Time_Delay |
| `event_enable` | `[to-offnormal, to-fault, to-normal]`、既定はすべて true |
| `notify_type` | `alarm`（既定）または `event` |

イベントエンロールメントは intrinsic reporting と同じイベント状態遷移、通知、AcknowledgeAlarm、
GetEventInformation / GetAlarmSummary / GetEnrollmentSummary、Web UI（バッジと **確認** ボタン付きの行、表示 → アラーム）を使います。
`event-parameters`（同じイベントタイプ）、`event-enable`、`notify-type`、`time-delay-normal`、`notification-class` への
BACnet 書き込みは反映され、設定にも書き戻されます。`acked-transitions` は読み取り専用です。デモ設定の `Room-Sensor-101` に
1 つあります。EDE エクスポートにはイベントエンロールメント（オブジェクトタイプ 9）が出力されます。EDE インポートでは
警告付きでスキップします（EDE は監視対象やパラメータを持たないため）。

Not supported：イベントタイプ `floating-limit`、`change-of-value` およびその他すべて（正確なアルゴリズムは ASHRAE 135 にのみ
規定）、イベントエンロールメントの故障検出（`fault` 状態 / change-of-reliability なし）、他デバイスのオブジェクトや
present-value 以外のプロパティの監視、BACnet 書き込みによる `event-type` / `object-property-reference` の変更、
CreateObject / DeleteObject によるイベントエンロールメントの作成 / 削除。イベントエンロールメントが監視している値オブジェクトは
削除できません。

#### Life Safety Point と Life Safety Zone

```yaml
      - {type: lsp, name: Smoke-101, description: Smoke detector}   # life-safety-point (object type 21)
      - type: lsp
        name: Heat-101
        value: quiet               # initial state (BACnetLifeSafetyState: quiet, pre-alarm, alarm, fault, ...)
        mode: "on"                 # BACnetLifeSafetyMode (default on; quote on / off in YAML)
        accepted_modes: ["on", "off", test]   # default [off, on, test]
        operation_expected: none   # BACnetLifeSafetyOperation, read-only (default none)
        silenced: unsilenced       # initial BACnetSilencedState
        behavior: {type: random_alarm, probability: 0.001, state: alarm}  # optional, per sim second
      - {type: lsz, name: Zone-101, zone_members: [Smoke-101, Heat-101]}  # life-safety-zone (object type 22)
```

完全な状態遷移は ASHRAE 135 にしか規定されていないため、シミュレーターは簡略化したモデルを使います。

- **Tracking_Value** は検知器の現在状態です。UI（行の検知状態メニュー、
  `POST /api/devices/{id}/life-safety/{type:instance}/state`）または任意の `random_alarm` behavior（ランダムに
  `state` になり、次の tick で `quiet` に戻る）で設定します。BACnet クライアントからは読み取り専用です。
- **Present_Value** は Tracking_Value が `quiet` 以外の間それに追従し、`quiet` に戻っても reset まで
  **ラッチ**されます。present-value への BACnet 書き込みは out-of-service 中のみ受け付けます。
- **Zone** の Tracking_Value は、Zone_Members の順で最初に `quiet` でないメンバーの present value
  （全員 `quiet` なら `quiet`）です。これは簡略化で、状態間の重大度の順序は適用しません。
- **LifeSafetyOperation**：`silence` / `silence-audible` / `silence-visual` は Silenced の audible / visible
  部分をセットし、`unsilence*` はクリアします。`reset` / `reset-alarm` / `reset-fault`（ここではすべて同じ）は
  Tracking_Value を Present_Value にコピーして unsilence します。`none` は何もしません。Zone への操作は
  メンバーにも適用され、object identifier なしの場合はデバイスの全 Life Safety オブジェクトに適用されます。
  ベンダー固有の操作は `services` / `optional-functionality-not-supported`、他のオブジェクト種別は `object` /
  `unsupported-object-type` を返します。すべての操作はイベントログに記録されます。
- **mode** は書き込み可能ですが accepted-modes のいずれかである必要があります（違反時 `property` /
  `value-out-of-range`）。**zone-members** は書き込み可能（WriteProperty、AddListElement / RemoveListElement）で、
  メンバー名として設定に書き戻されます（他デバイスへの参照は無視）。
- ReinitializeDevice で設定どおりの状態に戻ります。EDE エクスポートに含まれ（object type 21 / 22、値は状態番号）、
  EDE インポートでは種別・名前・状態を保持します。

非対応：change-of-life-safety イベント通知（alarm-values、life-safety-alarm-values、fault-values とイベント
プロパティは評価しません）、状態の重大度順序とモード依存の遷移、maintenance-required / direct-reading /
setting の動作、CreateObject / DeleteObject による Life Safety オブジェクトの作成 / 削除。

### デバイス管理サービス

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

### TextMessage、PrivateTransfer、リスト要素サービス

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
  1 始まりの番号付き）。設定への書き戻し（WriteProperty と同様。テンプレート由来のオブジェクトは上書きエントリとして保持）：
  zone-members、recipient-list（通知送信にも即反映）、date-list、list-of-object-property-references（Schedule は新しい対象へ書き込みます）。

```yaml
  - device_id: 1006
    name: Room-Sensor-101
    private_transfer:
      - {vendor_id: 999, service_number: 1}              # result: echo (default)
      - {vendor_id: 999, service_number: 2, result: 42}  # fixed value
```

非対応：PrivateTransfer パラメータのベンダー固有の意味（デコードしません）、ルーターデバイスでの TextMessage、
上記チェック以外に ASHRAE 135 が個々のプロパティについてのみ定める AddListElement / RemoveListElement の規則。

### Behavior

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

### テンプレート

`lighting`、`split_ac`、`ahu`、`power_meter`、`env_sensor`、`pv_inverter`、`custom` — 詳細は
[sme_bacnet_sim/templates.py](sme_bacnet_sim/templates.py) を参照してください。独自のテンプレートは約 20 行の関数で追加できます。

### EDE のインポート / エクスポート

SME BACnetSim は EDE ファイル（B.I.G.-EU Engineering Data Exchange、レイアウト 2.3）を読み書きできます。これは
多くの BACnet ツールやインテグレータがやり取りする CSV 形式のポイントリストです。

- **エクスポート**: `EDE` ボタン（`GET /api/config/export?format=ede`）で、メインファイル
  `sme-bacnet-sim-ede.csv`（オブジェクトごとに 1 行、加えてオブジェクトタイプ 8 のデバイス行 1 行。オブジェクトタイプと
  単位は数値コード。テンプレートは展開済み）と、ステートテキストファイル `sme-bacnet-sim-ede-statetexts.csv`
  （バイナリオブジェクト: Text 1 = inactive、Text 2 = active。マルチステートオブジェクト: 状態 1..N）を含む zip をダウンロードします。
- **インポート**: メイン CSV を選択します。必要に応じてステートテキスト CSV（またはエクスポートした zip）も一緒に選択します。
  ステートテキストファイルはヘッダーで識別されます。区切り文字はセミコロンまたはカンマ、UTF-8（BOM の有無を問わない）と
  cp1252 が受け付けられます。行はデバイスインスタンスごとに 1 つのデバイスにグループ化されます（名前はデバイス行から取得、
  なければ `Device-<id>`）。AV/BV/MSV で `settable = Y` の場合、そのオブジェクトはコマンド可能になります。シミュレータが
  サポートしていないオブジェクトタイプはスキップされ、イベントログに警告として報告されます。実行中の設定のネットワーク設定と
  シミュレーション設定は維持されます。インポートされたオブジェクトは静的です（behavior なし）。
- **Trend Log**（オブジェクトタイプ 20）: エクスポートでは、Trend Log の設定が `vendor-specific-address`
  列に `|` で区切った `key=value` のペアとして書き込まれます（例: `log_object=RoomTemp|log_interval=60|logging_type=cov`。
  キーは YAML と同じ）。そのため、エクスポートしたファイルは Trend Log ごと再インポートできます。他のツールのファイルにはログ対象
  オブジェクトの参照がないため、インポート時には、`<name>_Log` という名前の Trend Log に対して `<name>` が存在すればそれをログ対象とし、
  存在しなければデバイスの最初のアナログ / バイナリ / マルチステートオブジェクトをログ対象にして（ポーリング、60 秒）、警告を出します。
- **Accumulator / Pulse Converter / Loop**（オブジェクトタイプ 23 / 24 / 12）: 上の「オブジェクト」を参照してください。
- **hi-limit / low-limit** は、アナログオブジェクトの `alarm.high_limit` / `alarm.low_limit` にマップされます。インポート時、アラームは
  デバイスの最初の Notification Class を使用します。ファイルにない場合は `NC-1`（インスタンス 1、受信先なし）が
  作成されます。Notification Class はデフォルトの優先度・受信先なしでインポートされます（EDE にはそのための列がありません）。
  その他のアラーム設定（deadband、time delay、バイナリ / マルチステートのアラーム値）は EDE では引き継がれません。

### コピー / 貼り付けとプロパティグリッド

- **デバイス**: デバイスヘッダーの「コピー」（または一覧のデバイスを右クリック、ポイント未選択時の Ctrl+C）の後、
  「貼り付け」（ヘッダーのボタン、「編集 → 貼り付け」、Ctrl+V）で複製を追加します。デバイス ID はコピー元の次の空き番号、
  名前は `Name (copy)` です。「デバイスを追加」と同様に設定へ反映されます。
- **ポイント**: Ctrl / Shift クリックで行を選択して Ctrl+C（または「編集 → コピー」）、デバイス（同じでも別でも可）を
  選択して Ctrl+V。貼り付けたオブジェクトは型ごとの次の空きインスタンス番号を使い、名前が重なると `(copy)` を付けます。
  参照（`log_object`、スケジュールの `targets` / 例外の `calendar`、`input_object`、ループの `*_object`、
  `monitored_object`、`notification_class`、`alarm.notification_class`）は名前のまま保持し、同じ貼り付けに含まれる
  オブジェクトへの参照は名前を変えたコピーを指します。参照先の名前が貼り付け先デバイスに無いオブジェクトは貼り付けず、
  理由を表示してイベントログに記録します。Ctrl+C / Ctrl+V はテキスト入力やダイアログにフォーカスが無いときだけ働きます。
  クリップボードはページ内メモリです。
- **プロパティ**: 行の ⚙ ボタン（デバイスオブジェクトはヘッダーの「プロパティ」）で BACnet オブジェクトの全プロパティを
  プロパティ識別子順に、値・データ型・書き込み可否とともに表示します。書き込みは BACnet WriteProperty 要求と同じ経路を
  通ります（同じチェック、アラームプロパティの設定への書き戻し）。コマンダブルな Present_Value は優先度を選んで書き込み、
  または解除できます。編集できるのは基本型（real、double、unsigned、integer、boolean、enumerated、character string）
  のみで、構造型（配列・リスト・シーケンス）は JSON で表示し UI からは読み取り専用です。Object_Identifier・Object_Type・
  Property_List は UI から書き込みません。

## HTTP API

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
| POST | `/api/config/import` | multipart アップロード: YAML / JSON ファイル 1 つ、または EDE の CSV ファイル / zip（フィールド `file`、複数指定可） |
| GET | `/api/config/export?format=yaml\|json\|ede` | ダウンロード（`ede` = メイン CSV + ステートテキスト CSV の zip） |
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

## 開発

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

エンドツーエンドテストは UDP 47900 でシミュレータを起動し、bacpypes3 クライアントからルータ経由で
通信します。

## 商用サポートとカスタム開発

SME BACnetSim は **smart-edge** — 南京智届科技有限公司（Nanjing Smart-Edge Technology Co., Ltd.、智届科技）が開発しています。
同社は 2023 年の創業以来、太陽光、蓄電池、EV などの分散型エネルギーリソース向けに、機器制御から
クラウド、電力市場までのエンドツーエンドのソフトウェアを開発してきました。製品には、
AERIS RA プラットフォーム（リソースアグリゲーター向け）と、日本の電力市場向けの AC システム（アグリゲーションコーディネーター）が
あります。チームは日本語でプロジェクトをサポートしており、要件定義から
設計、実装、運用・保守まで対応します。

サービス:

- エネルギーマネジメントシステム（EMS）、クラウドおよびオンサイト
- 電力市場向けの RA / AC システム（JEPX、EPRX、OCCTO）
- エッジ IoT および機器制御ソフトウェア
- 機器連携: Modbus、MQTT、BACnet、ECHONET Lite、OpenADR 2.0b
- エネルギー予測とデータ分析
- クラウドインフラの設計・構築・運用

SME BACnetSim への機能追加や、お使いのデバイスまたは EMS との連携支援が必要ですか？ お気軽にお問い合わせください:

- Web サイト: <https://smartedge-tech.com>
- お問い合わせページ: <https://smartedge-tech.com/contact/>
- E-mail: [business@smartedge-tech.com](mailto:business@smartedge-tech.com)

## ライセンス

[MIT](LICENSE)
