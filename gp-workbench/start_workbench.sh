#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -X utf8 local_app.py "$@"
else
  exec python3 -X utf8 local_app.py "$@"
fi
