# Development

```powershell
.venv\Scripts\pip install pytest
.venv\Scripts\python -m pytest -q
```

The end-to-end test starts the simulator on UDP 47900 and talks to it with a bacpypes3 client through the
router.
