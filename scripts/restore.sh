#!/usr/bin/env bash
# Pull the latest state from the `data` branch into ./data
set -euo pipefail
mkdir -p data
if git ls-remote --exit-code --heads origin data >/dev/null 2>&1; then
  git fetch -q --depth=1 origin data
  git archive FETCH_HEAD | tar -x -C data
fi
