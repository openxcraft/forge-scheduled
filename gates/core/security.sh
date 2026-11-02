#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
bash "$WORK/gates/core/no-secrets.sh"
world_writable=$(find "$WORK/runtime" "$WORK/schedules" "$WORK/gates" "$WORK/schemas" "$WORK/projects" -type f -perm -0002 -print 2>/dev/null || true)
if [ -n "$world_writable" ]; then
  printf '%s\n' "$world_writable" >&2
  exit 1
fi
unsafe=$(find "$WORK/keys" -type f -name '*.key' ! -perm 600 -print 2>/dev/null || true)
if [ -n "$unsafe" ]; then
  printf '%s\n' "$unsafe" >&2
  exit 1
fi
