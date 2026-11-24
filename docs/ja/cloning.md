# 実機デバイスのクローン

`sme-bacnet-sim clone` は実機の BACnet デバイスを読み取り、シミュレータの設定（YAML）を書き出します。以後のテストは
お客様のネットワークに接続せず、シミュレータに対してオフラインで行えます。

!!! warning "事前にお客様の許可を得てください"
    お客様ネットワーク上のデバイスを読み取るには、お客様の許可が必要です。非稼働時間帯を推奨します。
    ルータ配下の MS/TP は低速で、ローエンドのコントローラは要求の集中で負荷が上がることがあります。
    まず狭い `--who-is` 範囲で試し、`--rate` は既定値のまま使ってください。

## 読み取り専用の保証

クローンのクライアントが送信できるのは **Who-Is、ReadProperty、ReadPropertyMultiple** だけです。これはコードで強制され、
クライアントアプリケーションはそれ以外の APDU をすべて拒否します（`ReadOnlyViolation`）。WriteProperty、SubscribeCOV、
DeviceCommunicationControl、ReinitializeDevice、AtomicReadFile などは送信できません。また受動的で、他のデバイスからの
要求には一切応答しません（I-Am も ReadProperty 応答も返しません）。テストでシミュレータのインスタンスをクローンし、
「実機」側が受信したのがこの 3 サービスだけであることを確認しています。

それ以外の通信はネットワーク層のみです。`--network N` を `--address` なしで使うと、bacpypes3 がルータを探すために
Who-Is-Router-To-Network を送ることがあります。`--foreign-bbmd` を使うと、BVLL のリンク層が Register-Foreign-Device
（終了時は TTL 0）を送り、ブロードキャストを Distribute-Broadcast-To-Network で包みます。中身は許可された APDU だけです。

## ゲートウェイ上での実行（Docker、主な方法）

典型的な構成: お客様の BACnet ネットワーク上の Linux ゲートウェイ（Moxa など）に SSH でログインし、そこでクローンを実行します。
主な方法は Docker で、Docker が動くマシンなら Python なしで実行できます。

イメージは `linux/amd64`、`linux/arm64`、`linux/arm/v7` 向けに公開しています（マルチアーキテクチャの 1 タグで、
`docker pull` が適切なものを選びます）。ゲートウェイの `uname -m` で確認します: `x86_64` = amd64、`aarch64` = arm64、
`armv7l` = arm-v7（Moxa UC シリーズなど）。インターネットに出られないゲートウェイでは、GitHub Release から対応する
オフラインアーカイブ `sme-bacnet-sim-<ver>-linux-amd64.tar.gz`、`-linux-arm64.tar.gz`、`-linux-arm-v7.tar.gz` を
ダウンロードし、FTP / SCP / USB などで転送します。`docker load -i` は `.tar.gz` をそのまま読めます（gunzip 不要）。
ロードしたイメージのタグは `ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>` なので、`docker pull` 後と同じコマンドで動きます。

```sh
# インターネットに出られないゲートウェイ: イメージの tar を（FTP などで）転送してロード
docker load -i sme-bacnet-sim-<ver>-linux-<arch>.tar.gz
# インターネットに出られる場合
docker pull ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>

docker run --rm --network host --user "$(id -u):$(id -g)" -v "$PWD":/out \
  ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver> \
  sme-bacnet-sim clone --who-is 1000-1010 -o /out/site.yaml
```

- armv7 のゲートウェイ（Moxa など）: `docker load -i sme-bacnet-sim-<ver>-linux-arm-v7.tar.gz` のあと同じ `docker run`。
  `docker images` に `ghcr.io/smartedge-tech-dev/sme-bacnet-sim`（タグ `<ver>`）が表示されれば OK です。
- `--network host` は必須です。Who-Is のブロードキャストと I-Am の応答は Docker の bridge ネットワークを越えません。
- `--user` でマウントしたディレクトリにコンテナから書き込めます。`python -m sme_bacnet_sim clone ...` も使えます。
- `site.yaml`（と `site.yaml.log.jsonl`）を持ち帰り、`-c site.yaml` でシミュレータを起動します。

### pip（補助的な方法）

Python 3.10 以上がある場合、チェックアウトまたはソースアーカイブから
`python3 -m venv venv && venv/bin/pip install .`（venv なしなら `pip install --user .`）でインストールし、
`sme-bacnet-sim clone ...` を実行します。リリースの PyInstaller 実行ファイルは x86-64 の Windows 向けだけです。
Linux / macOS / ARM のゲートウェイでは Python または Docker イメージを使ってください。

## 使い方

```text
sme-bacnet-sim clone [--who-is LOW-HIGH | --address IP[:PORT] | --network N] [--devices ID,...]
                     [--ip IP/PREFIX] [--port 47808] [--client-device-id 4194300]
                     [--rate 5] [--timeout 3] [--retries 2] [--no-rpm]
                     [--object-list-file FILE.json] [--no-keep-ids] [--resume] -o OUT.yaml
```

| オプション | 意味 |
|---|---|
| `--who-is LOW-HIGH` | このインスタンス範囲で Who-Is（ローカルブロードキャスト。数値 1 つなら 1 台） |
| `--address IP[:PORT]` | このデバイスへユニキャスト。`--devices` と併用すると Who-Is を一切送りません。併用しない場合はユニキャストの Who-Is、続いて `device,4194303`（ワイルドカードインスタンス）を読み取ります |
| `--network N` | リモートネットワーク: `N:*` へ Who-Is。`--address` と併用するとそのアドレスはネットワーク N への BACnet ルータ |
| `--devices ID,...` | これらのデバイスインスタンスのみ（`--who-is` なしの場合、Who-Is の範囲はその最小..最大） |
| `--foreign-bbmd HOST[:PORT]`、`--foreign-ttl S` | 先にこの BBMD へフォーリンデバイスとして登録（サブネット越え、下記参照。TTL 既定 300 秒） |
| `--ip`, `--port` | クローンクライアントのローカルアドレスと UDP ポート（既定: `--foreign-bbmd` / `--address` へ経路のあるインタフェース、なければ自動 / 47808） |
| `--client-device-id` | クローンクライアント自身のデバイスインスタンス（既定 4194300） |
| `--rate` | 1 秒あたりの最大要求数（既定 5） |
| `--timeout`, `--retries` | 要求ごと（APDU タイムアウトと再送回数）。`--timeout` は Who-Is の待ち時間にも使われます |
| `--no-rpm` | ReadPropertyMultiple を使わない |
| `--object-list-file` | object-list を読めないデバイスのオブジェクト表（後述） |
| `--keep-ids` / `--no-keep-ids` | デバイスインスタンスを保持（既定）するか 1001 から振り直すか |
| `--resume` | 出力ファイルにあるデバイスを残し、それらをスキップ |

`--who-is`、`--address`、`--devices` のいずれかが必須です。既定でネットワーク全体にブロードキャストすることはありません。

読み取り方:

- デバイスを 1 台ずつ、`--rate` で間隔を空けて読み取ります。進捗は stderr に出ます。
- object-list は要素ごとに読み取ります（index 0 = 個数、続いて 1..N）。セグメンテーション非対応のデバイスでも動作します。
  失敗した場合は全体で、それも失敗した場合は `--object-list-file` から取得します。
- 各オブジェクトは ReadPropertyMultiple で読み取ります（セグメンテーション非対応のデバイスにはデバイスの
  max-apdu-length-accepted に応じた小さな要求）。RPM が最初にエラー / reject / abort になった時点で、そのデバイスの残りは
  ReadProperty で読み取ります。デバイスにないプロパティはスキップします。
- YAML はデバイスごとに書き直されます。Ctrl+C で中断しても読み取り済みのデバイスはファイルに残り、`--resume` で続行できます。
- `<out>.log.jsonl` にすべての要求・応答・エラー・警告を記録します（1 行 1 JSON）。

### サブネット越え: `--foreign-bbmd`

Who-Is のブロードキャストと（ブロードキャストの）I-Am 応答は IP ルータを越えません。現地に BBMD（BACnet ルータや
デバイスシミュレータ自身の「Operate as BBMD」など）があれば、フォーリンデバイスとして登録します:

```bash
sme-bacnet-sim clone --foreign-bbmd 192.168.251.8 --who-is 0-4194302 -o site.yaml
```

BBMD がそのサブネットへ Who-Is を配信し、I-Am 応答をクローンクライアントへ転送します。ルータ配下の仮想ネットワーク上の
デバイスも含まれます（`network:mac` で読み取ります）。`--ip` を省略すると BBMD へ経路のあるローカルアドレスにバインドします。
VPN / オーバーレイ経路（Tailscale のサブネットルートなど）では重要で、LAN 側アドレスにバインドすると要求が有効な送信元を
持たずに出て行き、何も返ってきません。BBMD が NAK または無応答ならエラーで終了し、終了時に登録を解除します（TTL 0）。

### オブジェクト表ファイル

object-list を読めないデバイスは、オブジェクトを JSON ファイルで指定します（現場の既存ファイルの形式。`properties` など
他のキーは無視します）:

```json
[{"deviceID": 1011, "objectList": [{"objectType": "analogInput", "objectInstance": 1},
                                   {"objectType": "binaryValue", "objectInstance": 3}]}]
```

`objectType` は bacpypes の camelCase 名（`analogInput`）またはハイフン区切りの BACnet 名（`analog-input`）です。

## クローンされる内容

出力は `devices:` のみです。ネットワーク設定はシミュレータの既定のままなので、デバイスは元のインスタンス番号のまま、
内蔵ルータ配下の仮想ネットワークで提供されます。

- **デバイス**: object-name、description、location、ベンダー名 / ID、モデル名。max-apdu とセグメンテーションはログに記録。
- **シミュレータが対応するすべてのオブジェクトタイプ**。それ以外（独自タイプなど）は警告付きでスキップ。
- **値オブジェクト**（AI/AO/AV、BI/BO/BV、MSI/MSO/MSV）: 名前、description、単位、COV 増分、present value の最小 / 最大、
  active / inactive テキスト、ステートテキスト（state-text がなく number-of-states のみなら `State 1..N`）、
  commandable（priority array の有無）。値は commandable なら relinquish default、それ以外は present value。
- **アラーム**: notification-class、high / low limit、deadband、limit-enable、alarm value(s)、fault values、event-enable、
  notify-type、time-delay（-normal）。Notification Class がクローンされていない場合は警告付きでスキップ。
- **Notification Class**: priority、ack-required、デバイス指定の受信者（アドレス指定の受信者はスキップ）。
- **Schedule / Calendar**: 週間・例外スケジュール、既定値、同一デバイス内のターゲット、書き込み優先度、有効期間。カレンダーの日付。
- **Trend Log**: 記録対象（同一デバイス）、プロパティ、間隔、バッファサイズ、enable、logging type（`triggered` は警告付きで polled）。
- **Accumulator、Pulse Converter、Loop、Program、Event Enrollment**（out-of-range / change-of-state）、
  **Life Safety Point / Zone**: 設定可能なプロパティ。
- **File**: タイプ、アクセス方式、read-only。内容はクローン**しません**（AtomicReadFile を使わないため）。
- 他のデバイスへの参照（Trend Log、スケジュールのターゲット、Event Enrollment）は警告付きで削除されます。

present value はスナップショットで、クローンした設定に behavior はありません。

## ゲートウェイ上の既存 BACnet クライアントとの共存

ゲートウェイではすでに BACnet クライアント（例: host ネットワークで `<ip>:47808` を使う BAC0）が動いていることがあります。

- **ポート**: 47808 が使用中なら、クローンは明確なエラーで停止します。`--port 47809`（または他の空きポート）を使うか、
  先に 47808 を使っているプログラムを停止してください。
- **別ポートでの I-Am**: 多くのデバイスは I-Am を 47808 宛てにブロードキャストするため、47809 のクローンは Who-Is の応答を
  受け取れないことがあります。`--address <デバイス IP>`（ユニキャスト）と `--devices <インスタンス>` を使えば Who-Is は
  一切不要です。`--devices` なしの場合は、そのアドレスの `device,4194303` を読み取ってインスタンスを調べます。
- **デバイスインスタンス**: クローンクライアント自体も BACnet デバイスで、既定のインスタンスは **4194300** です。
  既存クライアントのインスタンスと衝突する場合は `--client-device-id` で変更してください。

## replay 用 CSV の記録

構造をクローンし、値を記録し、オフラインで再生します。`sme-bacnet-sim record` は実機から present-value を（読み取り専用で）
読み取り、`replay` Behavior が再生する CSV に書き出します（[Behavior](behaviors-templates.md)）。

```sh
sme-bacnet-sim record -c site.yaml --address 192.168.1.50 --interval 60 --duration 8h -o data/site.csv
```

- **ポイント**: `-c` の設定から取得します（通常は `clone` が書いた YAML。デバイス / インスタンスを実機と一致させるため keep-ids が必須）。
  `--points NAME,...` で絞り込めます。`-c` なしの場合は `--points [DEVICE/]TYPE:INSTANCE[=COLUMN],...`、例:
  `--points ai:1=OAT,bi:3=Occupied`（列名の既定は `analog-input:1`）。記録できるのは analog / binary / multi-state の
  input / output / value、accumulator、pulse-converter、loop（present-value）。複数デバイスで同じポイント名がある場合、列名は
  `DEVICE/NAME` になります。
- **CSV**: 1 列目は `time`（ISO のローカル日時、秒単位）、以降はポイントごとに 1 列。binary は `active` / `inactive`、
  multi-state は状態番号、analog は有効数字 7 桁。読めなかった値は空セルになり（replay は直前の値を保持。ただし先頭行には値が
  必要で、なければ replay がエラーを報告）、ポイントごとに警告を 1 回出します。
- **読み取り**: present-value を ReadPropertyMultiple で読みます（デバイスごと、`--batch`（既定 20）オブジェクトにつき 1 要求）。
  デバイスが RPM を拒否した場合は ReadProperty にフォールバックし、`--no-rpm` で ReadProperty に固定できます。`--rate`
  （要求数/秒の上限）も有効です。1 回のサンプリングが `--interval` より長くかかった場合、飛ばしたタイミングは警告付きでスキップします。
- **停止**: `--duration`（`90`、`30s`、`15m`、`8h`、`1d`）、`--count N`、または Ctrl-C。1 行ごとにフラッシュするため何も失われません。
  既存ファイルはエラーですが、`--resume` を付けると列が同一の場合に追記します（時間の空きは、analog ポイントでは replay が線形補間します）。
- **Trend Log**（`--trend-log`）: 選択した Trend Log オブジェクトの log-buffer を ReadRange で 1 回だけ（位置指定、50 件ずつ）読み、
  タイムスタンプごとに 1 行を書きます（全ログの和集合。空セルはその時刻の記録なし、先頭の欠けはその列の最初の値で埋めます）。
  `-c` ありの場合は設定内の Trend Log オブジェクトを使い（列名 = Trend Log の名前）、なしの場合は `--points trend-log:1=OAT,...`。
  Status、time-change、failure のレコードはスキップします。
- **接続オプション**は `clone` と同じです: `--address`、`--network`、`--who-is`、`--devices`、`--ip`、`--port`、
  `--foreign-bbmd` / `--foreign-ttl`、`--rate`、`--timeout`、`--retries`、`--client-device-id`。
- **読み取り専用**: `clone` と同じガード付きクライアントです。ポーリングは Who-Is、ReadProperty、ReadPropertyMultiple のみを送信し、
  `--trend-log` はこれに ReadRange（これも読み取りサービス）を加えます。`<out>.log.jsonl` に警告とエラーを記録します（個々の値は記録しません）。

結果は設定で次のように使います:

```yaml
behavior: {type: replay, file: data/site.csv, column: OAT}
```

Docker の例（[ゲートウェイ上での実行](cloning.md)と同様）:

```sh
docker run --rm --network host --user "$(id -u):$(id -g)" -v "$PWD":/out \
  ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver> \
  sme-bacnet-sim record -c /out/site.yaml --address 192.168.1.50 --interval 60 --duration 8h -o /out/site.csv
```

## オフライン: EDE

ゲートウェイで何も実行できない場合は、お客様の BACnet ツールから EDE ファイルをエクスポートし、
[EDE インポート](ede.md) を使ってください。EDE が持つプロパティは少なくなります（アラームの詳細、スケジュール、受信者はなし）。
