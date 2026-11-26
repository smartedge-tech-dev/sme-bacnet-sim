# Development

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

The end-to-end test starts the simulator on UDP 47900 and talks to it with a bacpypes3 client through the
router.

## Screenshots

The README and docs screenshots are generated, not taken by hand. After a UI change, regenerate them all
(three languages, plus the animated `live.gif`) into `docs/assets/screenshots/`:

```powershell
.venv\Scripts\pip install playwright pillow
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python scripts\screenshots.py
```
