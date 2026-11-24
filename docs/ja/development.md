# 開発

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

エンドツーエンドテストは UDP 47900 でシミュレータを起動し、bacpypes3 クライアントからルータ経由で
通信します。
