# Build on 64-bit Windows using: py -m PyInstaller --noconfirm PaperReader-windows.spec
from pathlib import Path

root = Path(SPECPATH)
assets = root / 'paperreader' / 'assets'

a = Analysis(
    [str(root / 'paperreader' / '__main__.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(assets), 'paperreader/assets'),
        (str(root / 'paperreader' / 'themes'), 'paperreader/themes'),
    ],
    hiddenimports=['keyring', 'keyring.backends.Windows', 'fitz', 'httpx'],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'tkinter'],
    hookspath=[],
    hooksconfig={'matplotlib': {'backends': ['Agg']}},
    runtime_hooks=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='PaperReader',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, icon=str(assets / 'PaperReader.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PaperReader')
