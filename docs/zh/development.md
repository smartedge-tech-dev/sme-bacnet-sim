# 开发

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

端到端测试会在 UDP 47900 上启动模拟器，并通过路由器用 bacpypes3 客户端与之通信。
