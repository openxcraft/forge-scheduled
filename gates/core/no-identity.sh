#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
targets="$WORK/runtime $WORK/schedules $WORK/gates $WORK/schemas"
patterns='Signed-off-'
patterns=$patterns'by|Co-'
patterns=$patterns'authored-by|copyright[[:space:]]+[0-9]{4}|@gmail\.|@outlook\.|@hotmail\.|@example\.'
matches=$(grep -RInE "$patterns" $targets 2>/dev/null || true)
if [ -n "$matches" ]; then
  printf '%s\n' "$matches" >&2
  exit 1
fi
