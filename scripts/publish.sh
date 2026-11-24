#!/usr/bin/env bash
# usage: publish.sh file1 file2 ...
# Publishes ONLY the named files from ./data onto the latest `data` branch (single orphan commit,
# so the repo never grows). Several workflows can run at the same time without clobbering each other.
set -euo pipefail
REMOTE="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
for attempt in 1 2 3 4 5; do
  rm -rf /tmp/pub && mkdir /tmp/pub
  LEASE=""
  if git ls-remote --exit-code --heads origin data >/dev/null 2>&1; then
    git fetch -q --depth=1 origin data
    git archive FETCH_HEAD | tar -x -C /tmp/pub
    LEASE="--force-with-lease=data:$(git rev-parse FETCH_HEAD)"
  fi
  for f in "$@"; do [ -f "data/$f" ] && cp "data/$f" "/tmp/pub/$f"; done
  if (cd /tmp/pub && git init -q -b data && git config user.name agent-bot \
      && git config user.email agent-bot@users.noreply.github.com && git add -A \
      && git commit -q -m "data $(date -u +%FT%TZ)" && git push -q $LEASE "$REMOTE" data); then
    exit 0
  fi
  sleep $((RANDOM % 5 + 2))
done
echo "publish failed after retries" >&2; exit 1
