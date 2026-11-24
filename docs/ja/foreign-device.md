# Foreign Device 登録（サブネット越え）

別サブネットのクライアントから使う場合、ルーターのポートを既存の BBMD に Foreign Device として登録できます：
`network.foreign_device: {bbmd: "<ipv4>[:port]", ttl: <秒>}` または `--foreign-bbmd` / `--foreign-ttl`
（コマンドラインが優先。TTL の既定は 300 秒、ポートは 47808）。登録は bacpypes3 の foreign リンク層を使い、
TTL ごとに更新、応答がない間は再試行し、停止・再読み込み時に解除（TTL 0）します。結果（登録済み / NAK /
10 秒以内に応答なし / 期限切れ）はイベントログに記録され、ステータスバーに `FD → <bbmd> (…)` と表示されます。
スナップショット API では `network.foreign_device` で取得できます。

Not supported：`foreign_device` と `mode: bbmd` の併用、BBMD のホスト名指定（IPv4 アドレスのみ）、
BBMD のテーブルの読み書き（Read-Broadcast-Distribution-Table、Read-Foreign-Device-Table など）。
