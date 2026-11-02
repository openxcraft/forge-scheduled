#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
patterns='BEGIN (RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY|api[_-]?key[[:space:]]*[=:][[:space:]]*[A-Za-z0-9_./+=-]{12,}|secret[_-]?key[[:space:]]*[=:]|password[[:space:]]*[=:][^[:space:]]+|token[[:space:]]*[=:][[:space:]]*[A-Za-z0-9_./+=-]{16,}'
matches=$(grep -RInE "$patterns" "$WORK" --exclude-dir=.git --exclude-dir=keys --exclude-dir=archive 2>/dev/null || true)
if [ -n "$matches" ]; then
  printf '%s\n' "$matches" >&2
  exit 1
fi
