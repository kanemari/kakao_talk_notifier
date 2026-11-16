#!/usr/bin/env bash
# Run the test suite on the oldest supported and the newest Home Assistant.
# Usage: bash dev/run-tests-matrix.sh
set -e
cd "$(dirname "$0")/.."
SRC="$(pwd -W 2>/dev/null || pwd)"
run() {  # image, extra pip args
  MSYS_NO_PATHCONV=1 docker run --rm -v "$SRC:/src:ro" "$1" bash -c '
    cp -r /src /work && cd /work && rm -rf .venv
    (apt-get update -qq && apt-get install -y -qq gcc g++) >/dev/null 2>&1 || true
    pip install -q pytest-homeassistant-custom-component '"$2"' 2>&1 | grep -iE "^error|conflict" | head -3
    pip list 2>/dev/null | grep -iE "^homeassistant "
    pytest -q -p no:cacheprovider 2>&1 | tail -3'
}
echo "== oldest supported (2025.7) =="; run python:3.13-slim '"homeassistant==2025.7.4" "pycares<4.10"'
echo "== newest =="; run python:3.14-slim ''
