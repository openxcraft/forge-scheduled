#!/bin/sh
set -eu
WORK=${FORGE_WORK:-/work}
python3 - "$WORK" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]) / "projects"
source_files = []
coverage = []
if root.exists():
    for project in root.iterdir():
        if not project.is_dir():
            continue
        source_files.extend(path for path in (project / "src").rglob("*") if path.is_file()) if (project / "src").exists() else None
        for name in ("coverage.json", ".coverage.json"):
            path = project / name
            if path.exists():
                coverage.append(path)
if source_files and not coverage:
    raise SystemExit(1)
for path in coverage:
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("coverage", data.get("percent_covered", data.get("line_rate")))
    if isinstance(value, (int, float)):
        value = value * 100 if value <= 1 else value
        if value < 70:
            raise SystemExit(1)
        continue
    raise SystemExit(1)
PY
