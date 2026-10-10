#!/usr/bin/env bash
# Release check, used by the workflow's test step and after each AI conflict resolution:
#   - no conflict markers in tracked files
#   - every Python file compiles and every top-level module imports
#   - every JavaScript file parses (when Node is available)
#   - every HTML file has balanced tags
set -euo pipefail
shopt -s nullglob
PY="${PYTHON:-python3}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if git grep -nE '^(<{7}|>{7}) ' -- . ; then
  echo "::error::Conflict markers found"
  exit 1
fi

"$PY" -m compileall -q -x '(^|/)\.git/' .
for f in *.py; do
  "$PY" -c "import ${f%.py}" || { echo "::error::Importing $f failed"; exit 1; }
done

if command -v node >/dev/null; then
  for f in $(git ls-files '*.js'); do
    node --check "$f" || { echo "::error file=$f::JavaScript syntax error"; exit 1; }
  done
fi

html_files=$(git ls-files '*.html')
if [ -n "$html_files" ]; then
  "$PY" "$DIR/check_html.py" $html_files
fi
