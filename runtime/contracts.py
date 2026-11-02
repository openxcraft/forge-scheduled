import os
import re
import subprocess
import sys
from pathlib import Path

import state

PROJECTS = state.WORK / "projects"
GRAPH = PROJECTS / "graph.json"
REPORT = state.WORK / "reports" / "contracts.json"


def registry():
    return state.read_json(PROJECTS / "registry.json", {"projects": {}}) or {"projects": {}}


def project_names():
    names = sorted(registry().get("projects", {}).keys())
    if not names:
        names = sorted(path.name for path in PROJECTS.iterdir() if path.is_dir()) if PROJECTS.exists() else []
    return names


def contract_files():
    files = []
    for name in project_names():
        directory = PROJECTS / name / "contracts"
        if directory.exists():
            files.extend(sorted(directory.glob("*.contract.json")))
    return files


def check_invariant(item, base):
    kind = item.get("kind")
    if kind == "exists":
        return (base / item["path"]).exists()
    if kind == "absent":
        return not (base / item["path"]).exists()
    if kind == "equals":
        path = base / item["path"]
        return path.exists() and path.read_text(encoding="utf-8") == item.get("text", "")
    if kind == "matches":
        path = base / item["path"]
        return path.exists() and re.search(item.get("pattern", ".*"), path.read_text(encoding="utf-8")) is not None
    if kind == "command":
        completed = subprocess.run(item.get("cmd", "false"), shell=True, cwd=str(base), capture_output=True, timeout=120)
        return completed.returncode == 0
    return False


def verify_contract(path):
    data = state.read_json(path)
    schema_path = state.WORK / "schemas" / "contract.json"
    errors = state.validate_schema(data, state.read_json(schema_path)) if schema_path.exists() else []
    base = path.parent.parent
    artifacts = []
    for item in data.get("artifacts", []):
        target = base / item["path"]
        ok = target.exists()
        actual = state.sha256_file(target) if ok and target.is_file() else None
        if ok and item.get("sha256"):
            ok = actual == item["sha256"]
        artifacts.append({"path": item["path"], "ok": ok, "sha256": actual})
    invariants = [{"invariant": item, "ok": check_invariant(item, base)} for item in data.get("invariants", [])]
    ok = not errors and all(item["ok"] for item in artifacts) and all(item["ok"] for item in invariants)
    return {"path": str(path), "id": data.get("id"), "ok": ok, "errors": errors, "artifacts": artifacts, "invariants": invariants}


def verify_all():
    results = [verify_contract(path) for path in contract_files()]
    ok = all(item["ok"] for item in results)
    state.write_json(REPORT, {"time": state.utcnow(), "ok": ok, "contracts": results})
    return ok, results


def freeze_stable():
    ok, results = verify_all()
    if not ok:
        return False
    for path in contract_files():
        data = state.read_json(path)
        data["frozen"] = True
        state.write_json(path, data)
    return True


def dependencies():
    edges = {}
    for path in contract_files():
        data = state.read_json(path)
        name = path.parent.parent.name
        edges[name] = sorted(set(edges.get(name, [])) | set(data.get("dependencies", [])))
    for name in project_names():
        edges.setdefault(name, [])
    return edges


def find_cycles(edges):
    visiting = set()
    visited = set()
    stack = []
    cycles = []

    def visit(node):
        if node in visited:
            return
        if node in visiting:
            cycles.append(stack[stack.index(node) :] + [node])
            return
        visiting.add(node)
        stack.append(node)
        for child in edges.get(node, []):
            if child in edges:
                visit(child)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)
    return cycles


def rebuild_graph():
    edges = dependencies()
    cycles = find_cycles(edges)
    state.write_json(GRAPH, {"time": state.utcnow(), "nodes": sorted(edges), "edges": edges, "cycles": cycles})
    return edges


def detect_cycles():
    data = state.read_json(GRAPH, None) or rebuild_graph()
    cycles = data.get("cycles", []) if isinstance(data, dict) else find_cycles(data)
    return cycles


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: contracts.py verify-all|freeze-stable|verify-conformance|rebuild-graph|detect-cycles", file=sys.stderr)
        return 2
    command = argv[0]
    if command == "verify-all":
        return 0 if verify_all()[0] else 1
    if command == "freeze-stable":
        return 0 if freeze_stable() else 1
    if command == "verify-conformance":
        return 0 if verify_all()[0] else 1
    if command == "rebuild-graph":
        rebuild_graph()
        return 0
    if command == "detect-cycles":
        return 1 if detect_cycles() else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
