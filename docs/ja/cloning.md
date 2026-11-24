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
Who-Is-Router-To-Network を送ることがあります。

## ゲートウェイ上での実行（Docker、主な方法）

典型的な構成: お客様の BACnet ネットワーク上の Linux ゲートウェイ（Moxa など）に SSH でログインし、そこでクローンを実行します。
主な方法は Docker で、Docker が動くマシンなら Python なしで実行できます。

```sh
# インターネットに出られないゲートウェイ: イメージの tar を（FTP などで）転送してロード
docker load -i sme-bacnet-sim-<ver>-linux-<arch>.tar
# インターネットに出られる場合
docker pull ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>

docker run --rm --network host --user "$(id -u):$(id -g)" -v "$PWD":/out \
  ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver> \
  sme-bacnet-sim clone --who-is 1000-1010 -o /out/site.yaml
```

- `--network host` は必須です。Who-Is のブロードキャストと I-Am の応答は Docker の bridge ネットワークを越えません。
- `--user` でマウントしたディレクトリにコンテナから書き込めます。`python -m sme_bacnet_sim clone ...` も使えます。
- `site.yaml`（と `site.yaml.log.jsonl`）を持ち帰り、`-c site.yaml` でシミュレータを起動します。

### pip（補助的な方法）

Python 3.10 以上がある場合、チェックアウトまたはソースアーカイブから
`python3 -m venv venv && venv/bin/pip install .`（venv なしなら `pip install --user .`）でインストールし、
`sme-bacnet-sim clone ...` を実行します。リリースの PyInstaller 実行ファイルは x86-64 の Windows / Linux / macOS 向けだけで、
ARM のゲートウェイには対応していません。

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
| `--ip`, `--port` | クローンクライアントのローカルアドレスと UDP ポート（既定: 自動 / 47808） |
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

## オフライン: EDE

ゲートウェイで何も実行できない場合は、お客様の BACnet ツールから EDE ファイルをエクスポートし、
[EDE インポート](ede.md) を使ってください。EDE が持つプロパティは少なくなります（アラームの詳細、スケジュール、受信者はなし）。
