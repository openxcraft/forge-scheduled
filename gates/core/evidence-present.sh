#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
python3 - "$WORK" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]) / "evidence"
files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
for path in files[:5]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("raw")
        digest = data.get("sha256")
        import hashlib
        if isinstance(raw, str) and hashlib.sha256(raw.encode()).hexdigest() == digest:
            raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)
PY
