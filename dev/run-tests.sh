#!/usr/bin/env bash
# Run the test suite in a clean Python 3.13 container (Home Assistant needs Linux + 3.13).
# Usage: bash dev/run-tests.sh [pytest args]
set -e
cd "$(dirname "$0")/.."
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W 2>/dev/null || pwd):/src:ro" python:3.13-slim bash -c '
  cp -r /src /work && cd /work && rm -rf .venv
  (apt-get update -qq && apt-get install -y -qq gcc) >/dev/null 2>&1 || true
  pip install -q -r requirements_test.txt 2>&1 | grep -v notice || true
  python -c "import homeassistant.const as c; print(\"Home Assistant\", c.__version__)"
  pytest -p no:cacheprovider "$@"
' _ "$@"
