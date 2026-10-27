#!/bin/sh
# dist/archive.tar.gz, what `viam module upload` takes: the source and the scripts that set it up on the machine - the
# same archive for every platform, pip choosing each machine's wheels on its first run.
cd "$(dirname "$0")" || exit 1
mkdir -p dist
COPYFILE_DISABLE=1 tar --no-xattrs -czf dist/archive.tar.gz --exclude __pycache__ meta.json run.sh setup.sh requirements.txt README.md src
