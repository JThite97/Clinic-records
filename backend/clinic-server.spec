# PyInstaller spec for the Clinic Records server (the Tauri sidecar).
#   pyinstaller clinic-server.spec   ->  dist/clinic-server(.exe)
# One-file build so Tauri can ship it as an external binary.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = (
    collect_submodules("clinic")
    + collect_submodules("uvicorn")
    + collect_submodules("sqlcipher3")
    + ["argon2", "pyzipper", "rapidfuzz", "multipart", "python_multipart"]
)
datas = collect_data_files("clinic", includes=["data/*.json", "mobile/*.html"]) + collect_data_files("reportlab")

a = Analysis(
    ["clinic/__main__.py"],
    pathex=["."],
    hiddenimports=hidden,
    datas=datas,
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy", "PIL.ImageQt"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="clinic-server",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
