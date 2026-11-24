# PyInstaller spec (onefile). Build from the repo root:
#   pyinstaller packaging/sme-bacnet-sim.spec --noconfirm
# SPECPATH is the directory of this spec file (packaging/).
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

root = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(root, "sme_bacnet_sim", "static"), "sme_bacnet_sim/static"),
    # __main__ resolves configs/ relative to the package's parent directory
    (os.path.join(root, "configs", "demo-building.yaml"), "configs"),
]
datas += collect_data_files("bacpypes3")

hiddenimports = (
    collect_submodules("bacpypes3")
    + collect_submodules("uvicorn")
    + ["multipart", "yaml", "h11", "websockets", "httptools"]
)

a = Analysis(
    [os.path.join(root, "sme_bacnet_sim", "__main__.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sme-bacnet-sim",
    console=True,
    upx=False,
)
