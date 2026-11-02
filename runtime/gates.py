import os
import subprocess
import sys
from pathlib import Path

import state

CORE = state.WORK / "gates" / "core"
GATES = [
    "no-comments",
    "no-identity",
    "no-secrets",
    "evidence-present",
    "decision-present",
    "commit-signed",
    "stop-honored",
    "contract-conformance",
    "coverage",
    "complexity",
    "security",
    "docs-executable",
]


def gate_path(gate_id):
    path = CORE / (gate_id + ".sh")
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path


def run_gate(gate_id, timeout=120):
    path = gate_path(gate_id)
    env = os.environ.copy()
    env["FORGE_WORK"] = str(state.WORK)
    completed = subprocess.run(["bash", str(path)], cwd=str(state.WORK), env=env, text=True, capture_output=True, timeout=timeout)
    return {"gate": gate_id, "ok": completed.returncode == 0, "stdout": completed.stdout, "stderr": completed.stderr, "code": completed.returncode}


def full_suite():
    results = [run_gate(item) for item in GATES if item != "stop-honored"]
    ok = all(item["ok"] for item in results)
    state.write_json(state.WORK / "reports" / "gates.json", {"time": state.utcnow(), "ok": ok, "results": results})
    return ok


def audit_no_stubs():
    bad = []
    for path in sorted(CORE.glob("*.sh")):
        text = path.read_text(encoding="utf-8")
        if len(text.strip()) < 20 or text.strip() == "exit 0":
            bad.append(str(path))
    if bad:
        raise RuntimeError("stub gates: " + ", ".join(bad))
    return True


def audit_real_tools():
    missing = []
    for tool in ("grep", "find", "git", "python3", "sha256sum"):
        completed = subprocess.run(["sh", "-c", "command -v " + tool], capture_output=True)
        if completed.returncode != 0:
            missing.append(tool)
    if missing:
        raise RuntimeError("missing tools: " + ", ".join(missing))
    return True


def dependency_graph():
    import contracts

    contracts.rebuild_graph()
    return not contracts.detect_cycles()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: gates.py GATE_ID|full-suite|docs-executable|dependency-graph|audit-no-stubs|audit-real-tools", file=sys.stderr)
        return 2
    command = argv[0]
    try:
        if command == "full-suite":
            return 0 if full_suite() else 1
        if command == "docs-executable":
            return 0 if run_gate("docs-executable")["ok"] else 1
        if command == "dependency-graph":
            return 0 if dependency_graph() else 1
        if command == "audit-no-stubs":
            audit_no_stubs()
            return 0
        if command == "audit-real-tools":
            audit_real_tools()
            return 0
        result = run_gate(command)
        if result["stdout"]:
            print(result["stdout"], end="")
        if result["stderr"]:
            print(result["stderr"], end="", file=sys.stderr)
        return 0 if result["ok"] else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
