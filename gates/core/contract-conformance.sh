#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
FORGE_WORK="$WORK" python3 "$WORK/runtime/contracts.py" verify-conformance
