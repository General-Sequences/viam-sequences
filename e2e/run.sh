#!/bin/bash
# e2e/run.sh: the module end to end on a Linux x86_64 machine, no robot - viam-server with Viam's fake arm, camera and
# gripper and this module (run.sh, as a machine runs it), driven through the policy named viam-e2e by e2e/client.py.
#   SEQUENCES_API_KEY / SEQUENCES_BASE_URL: the account the policy is deployed on (the module's environment)
#   PYTHON: a Python with viam-sdk, for the client
set -u
here=$(cd "$(dirname "$0")/.." && pwd)
work=${WORK:-$here/.e2e}
mkdir -p "$work"
server=$work/viam-server
if [ ! -x "$server" ]; then
    curl -fsSL -o "$server" https://storage.googleapis.com/packages.viam.com/apps/viam-server/viam-server-stable-x86_64
    chmod +x "$server"
fi
umask 077
python3 - "$here" "$work/config.json" <<'PY'
import json, os, sys
here, out = sys.argv[1], sys.argv[2]
json.dump({
    "network": {"bind_address": "localhost:8080"},
    "components": [
        {"name": "arm", "api": "rdk:component:arm", "model": "rdk:builtin:fake", "attributes": {"arm-model": "ur5e"}},
        {"name": "cam", "api": "rdk:component:camera", "model": "rdk:builtin:fake",
         "attributes": {"width": 320, "height": 240}},
        {"name": "hand", "api": "rdk:component:gripper", "model": "rdk:builtin:fake"}],
    "services": [
        {"name": "sequences", "api": "rdk:service:generic", "model": "general-sequences:sequences:policy",
         "attributes": {"policy": "viam-e2e", "hz": 10, "replan_at": 5, "arm": "arm", "gripper": "hand",
                        "cameras": {"front": "cam"}}}],
    "modules": [{"type": "local", "name": "sequences", "executable_path": f"{here}/run.sh",
                 "env": {"SEQUENCES_API_KEY": os.environ["SEQUENCES_API_KEY"],
                         "SEQUENCES_BASE_URL": os.environ["SEQUENCES_BASE_URL"]}}],
}, open(out, "w"), indent=1)
PY
"$server" --appimage-extract-and-run -config "$work/config.json" > "$work/server.log" 2>&1 &
pid=$!
trap 'kill $pid 2>/dev/null; wait $pid 2>/dev/null; rm -f "$work/config.json"' EXIT
for _ in $(seq 1 120); do
    grep -q "sequences" "$work/server.log" 2>/dev/null && "${PYTHON:-python3}" -c \
        "import socket; socket.create_connection(('localhost', 8080), 1)" 2>/dev/null && break
    sleep 2
done
"${PYTHON:-python3}" "$here/e2e/client.py" "${WAIT_S:-300}"
