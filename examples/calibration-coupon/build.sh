#!/bin/sh
# Rebuild the calibration coupon into ./out (run from anywhere).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
py="$root/.venv/bin/python"
[ -x "$py" ] || py=python3
cd "$here"
"$py" -P "$root/scripts/calibration_coupon.py" build --out out
