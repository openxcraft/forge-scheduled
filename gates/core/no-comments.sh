#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
files=$(mktemp)
{
  [ ! -d "$WORK/src" ] || find "$WORK/src" -type f
  [ ! -d "$WORK/tests" ] || find "$WORK/tests" -type f
  [ ! -d "$WORK/runtime" ] || find "$WORK/runtime" -type f \( -name '*.py' -o -name '*.sh' \)
  [ ! -d "$WORK/projects" ] || find "$WORK/projects" -type f \( -path '*/src/*' -o -path '*/tests/*' \)
} > "$files"
matches=$(while IFS= read -r file; do grep -nE '(^|[^:])//|#' "$file" 2>/dev/null | grep -vE '^[0-9]+:#!' | sed "s|^|$file:|"; done < "$files" || true)
rm -f "$files"
if [ -n "$matches" ]; then
  printf '%s\n' "$matches" >&2
  exit 1
fi
