#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
python3 - "$WORK" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]) / "decisions"
files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
for path in files[:5]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        options = data.get("options")
        chosen = data.get("chosen")
        rejected = data.get("rejected")
        if isinstance(options, list) and chosen in options and isinstance(rejected, list) and set(rejected) == set(options) - {chosen}:
            raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)
PY
