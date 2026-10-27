#!/bin/sh
# The module's entrypoint: its own Python environment on the first run (setup.sh), then the module itself.
cd "$(dirname "$0")" || exit 1
./setup.sh >&2 || exit 1
exec ./venv/bin/python src/main.py "$@"
