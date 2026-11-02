#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
[ ! -e "$WORK/STOP" ]
[ ! -e /STOP ]
