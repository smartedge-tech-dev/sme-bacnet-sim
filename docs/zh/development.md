# 开发

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

端到端测试会在 UDP 47900 上启动模拟器，并通过路由器用 bacpypes3 客户端与之通信。

## 截图

README 和文档里的截图由脚本生成，不手工截取。修改 UI 之后，重新生成三种语言的全部截图（含动图 `live.gif`）到 `docs/assets/screenshots/`：

```powershell
.venv\Scripts\pip install playwright pillow
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python scripts\screenshots.py
```
