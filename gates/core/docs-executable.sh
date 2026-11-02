#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
python3 -m py_compile "$WORK"/runtime/*.py
for gate in "$WORK"/gates/core/*.sh; do sh -n "$gate"; done
python3 - "$WORK" <<'PY'
import re
import sys
from pathlib import Path
root = Path(sys.argv[1])
readme = root / "README.md"
text = readme.read_text(encoding="utf-8") if readme.exists() else ""
required = ["File tree", "Operations", "Monitoring", "License"]
if any(item not in text for item in required):
    raise SystemExit(1)
for path in root.glob("projects/*/docs/*.md"):
    content = path.read_text(encoding="utf-8")
    if "TODO" in content or "placeholder" in content.lower():
        raise SystemExit(1)
PY
