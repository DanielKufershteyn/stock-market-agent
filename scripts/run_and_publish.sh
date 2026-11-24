#!/usr/bin/env bash
# usage: run_and_publish.sh <python module> <owned file> [<owned file> ...]
set -euo pipefail
MODULE="$1"; shift
bash scripts/restore.sh
python -m "$MODULE"
bash scripts/publish.sh "$@"
