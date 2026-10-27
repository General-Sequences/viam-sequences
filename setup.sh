#!/bin/sh
# The module's Python environment in ./venv, made once and again whenever requirements.txt changes.
cd "$(dirname "$0")" || exit 1
want=$(cksum < requirements.txt)
if [ -x venv/bin/python ] && [ "$(cat venv/.requirements 2>/dev/null)" = "$want" ]; then
    exit 0
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    echo "this module needs Python 3.10 or later; python3 here is: $(python3 -V 2>&1)" >&2
    exit 1
fi
if ! python3 -m venv venv; then
    echo "could not make a Python environment: install python3-venv (Debian/Ubuntu: apt install python3-venv)" >&2
    exit 1
fi
venv/bin/python -m pip install -q --upgrade pip && venv/bin/python -m pip install -q -r requirements.txt || exit 1
echo "$want" > venv/.requirements
