# クイックスタート

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

## BACnet クライアントの接続

クライアントからは、ルータ（`device 4194000`）が `<ip>:47808` に、シミュレートされたデバイスがそのルータ経由の
`100:1`、`100:2`（ネットワーク 100、MAC 1、2…）といったアドレスに見えます。Yabe では
*Add device → BACnet/IP over UDP* を選び、続けて *Who-Is* を実行します。

> **同一 PC での注意:** Windows では、同じマシン上のクライアントがブロードキャスト応答
> （Who-Is/I-Am）を受信できないことがあります（ユニキャストは動作します）。クライアントを別のマシンで実行するか、シミュレータをクライアントとは別の NIC
> にバインドするか、`network.mode: bbmd` を設定してクライアントを Foreign Device として登録してください。
