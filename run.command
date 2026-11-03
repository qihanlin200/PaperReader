#!/bin/bash
set -e
cd "$(dirname "$0")"
# Module startup terminates matching previous instances before creating the window.
exec .venv/bin/python -m paperreader
