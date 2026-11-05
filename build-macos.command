#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python -m pip check
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"
export MPLCONFIGDIR="$PWD/build/matplotlib-cache"
.venv/bin/python -m PyInstaller --noconfirm PaperReader.spec
/usr/bin/ditto -c -k --sequesterRsrc --keepParent dist/PaperReader.app dist/PaperReader-macOS-arm64.zip
printf '\n构建完成：dist/PaperReader.app 和 dist/PaperReader-macOS-arm64.zip\n'
