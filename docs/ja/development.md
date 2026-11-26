# 開発

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

エンドツーエンドテストは UDP 47900 でシミュレータを起動し、bacpypes3 クライアントからルータ経由で
通信します。

## スクリーンショット

README とドキュメントのスクリーンショットは手作業ではなくスクリプトで生成しています。UI を変更したら、
3 言語分（アニメーション `live.gif` を含む）を `docs/assets/screenshots/` に再生成してください。

```powershell
.venv\Scripts\pip install playwright pillow
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python scripts\screenshots.py
```
