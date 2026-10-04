# PyInstaller spec for VX7 KHATA PRO (one-folder build, windowed).
# Build from the project root:  pyinstaller packaging/vx7_khata_pro.spec --noconfirm
from pathlib import Path

root = Path(SPECPATH).parent  # SPECPATH is provided by PyInstaller

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    datas=[(str(root / "vx7khata" / "assets"), "vx7khata/assets")],  # bundled fonts used by PDF export
    hiddenimports=[],
    excludes=["tkinter", "unittest", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VX7 KHATA PRO",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VX7 KHATA PRO")
