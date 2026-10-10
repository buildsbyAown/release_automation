#!/usr/bin/env bash
# Release check: every Python file compiles and every top-level module imports.
# Used by the workflow's test step and after each AI conflict resolution.
set -euo pipefail
PY="${PYTHON:-python3}"
"$PY" -m compileall -q -x '(^|/)\.git/' .
for f in *.py; do
  "$PY" -c "import ${f%.py}" || { echo "::error::Importing $f failed"; exit 1; }
done
