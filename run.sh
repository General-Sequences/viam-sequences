#!/bin/sh
# The module's entrypoint: its Python environment checked (setup.sh - made once, at install as first_run, or here on a
# machine that ran no first run), then the module itself.
cd "$(dirname "$0")" || exit 1
./setup.sh || exit 1
exec ./venv/bin/python src/main.py "$@"
