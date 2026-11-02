#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
git -C "$WORK" rev-parse --verify HEAD >/dev/null 2>&1
signature=$(git -C "$WORK" log -1 --format=%GG)
[ -n "$signature" ]
git -C "$WORK" verify-commit HEAD >/dev/null 2>&1
