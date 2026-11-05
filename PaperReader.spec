# Build on macOS using: python -m PyInstaller --noconfirm PaperReader.spec
from pathlib import Path
root = Path(SPECPATH)
a = Analysis([str(root / 'paperreader' / '__main__.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root/'paperreader'/'assets'), 'paperreader/assets'),
                        (str(root/'paperreader'/'themes'), 'paperreader/themes')],
    hiddenimports=['keyring', 'keyring.backends.macOS', 'fitz', 'httpx'],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'tkinter'],
    hookspath=[], hooksconfig={'matplotlib': {'backends': ['Agg']}}, runtime_hooks=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PaperReader', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    target_arch='arm64', codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PaperReader')
app = BUNDLE(coll, name='PaperReader.app', icon=str(root/'paperreader/assets/PaperReader.icns'),
    bundle_identifier='com.paperreader.desktop', info_plist={
        'CFBundleDisplayName':'PaperReader', 'CFBundleShortVersionString':'0.1.0',
        'CFBundleVersion':'1', 'NSHighResolutionCapable':True,
        'LSMinimumSystemVersion':'13.0', 'NSPrincipalClass':'NSApplication'})
