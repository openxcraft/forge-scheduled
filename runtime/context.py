import json
import os
import sys
from pathlib import Path

import state

PROJECTS = state.WORK / "projects"
RUNTIME = state.WORK / "runtime"
QUEUE = RUNTIME / "queue"
CONTEXT = RUNTIME / "context"


def registry():
    return state.read_json(PROJECTS / "registry.json", {"active": "default", "projects": {"default": {}}}) or {"active": "default", "projects": {"default": {}}}


def active_project():
    data = registry()
    active = data.get("active")
    if active in data.get("projects", {}):
        return active
    names = sorted(data.get("projects", {}))
    return names[0] if names else "default"


def project_path(name=None):
    return PROJECTS / (name or active_project())


def ensure_project(name=None):
    base = project_path(name)
    for item in ("roadmap", "contracts", "context", "src", "tests", "docs", "evidence", "decisions"):
        state.ensure_dir(base / item)
    for filename, value in {
        "charter.json": {"id": base.name, "status": "active", "created_at": state.utcnow()},
        "state.json": {"status": "ready", "updated_at": state.utcnow()},
    }.items():
        path = base / filename
        if not path.exists():
            state.write_json(path, value)
    return base


def roadmap_file(period, name=None):
    return project_path(name) / "roadmap" / (period + ".json")


def load_roadmap(period, name=None):
    path = roadmap_file(period, name)
    data = state.read_json(path, None)
    if isinstance(data, dict):
        return data
    return {"id": period + "-plan", "period": period, "created_at": state.utcnow(), "objectives": [], "tasks": []}


def write_roadmap_digest(name=None):
    base = ensure_project(name)
    digest = {period: load_roadmap(period, base.name) for period in ("year", "month", "week", "day", "hour")}
    state.atomic_write(base / "context" / "roadmap-digest.md", roadmap_markdown(digest))
    return digest


def roadmap_markdown(data):
    lines = ["Roadmap digest", ""]
    for period in ("year", "month", "week", "day", "hour"):
        item = data.get(period, {})
        lines.append(period.upper())
        for objective in item.get("objectives", []):
            lines.append("- " + str(objective))
        for task in item.get("tasks", []):
            if isinstance(task, dict):
                lines.append("- " + str(task.get("id", "task")) + ": " + str(task.get("title", "untitled")) + " [" + str(task.get("status", "ready")) + "]")
            else:
                lines.append("- " + str(task))
        lines.append("")
    return "\n".join(lines)


def module_summaries(name=None):
    base = project_path(name)
    result = []
    src = base / "src"
    if src.exists():
        for path in sorted(src.rglob("*")):
            if path.is_file():
                result.append({"path": str(path.relative_to(base)), "bytes": path.stat().st_size, "sha256": state.sha256_file(path)})
    return result


def regenerate_all_module_summaries(name=None):
    base = ensure_project(name)
    summaries = module_summaries(base.name)
    state.write_json(base / "context" / "modules.json", {"time": state.utcnow(), "modules": summaries})
    return summaries


def regenerate_architecture(name=None):
    base = ensure_project(name)
    modules = regenerate_all_module_summaries(base.name)
    lines = ["Architecture", "", "Modules: " + str(len(modules)), ""]
    for item in modules:
        lines.append("- " + item["path"] + " (" + str(item["bytes"]) + " bytes)")
    state.atomic_write(base / "context" / "architecture.md", "\n".join(lines) + "\n")
    return lines


def regenerate_roadmap_digest(name=None):
    return write_roadmap_digest(name)


def ready_tasks(name=None):
    tasks = []
    for period in ("hour", "day", "week", "month", "year"):
        data = load_roadmap(period, name)
        for index, task in enumerate(data.get("tasks", [])):
            if isinstance(task, dict):
                status = task.get("status", "ready")
                item = {"id": str(task.get("id", period + "-" + str(index))), "title": str(task.get("title", "untitled")), "source": period, "status": status}
            else:
                item = {"id": period + "-" + str(index), "title": str(task), "source": period, "status": "ready"}
            if item["status"] == "ready":
                tasks.append(item)
    return tasks


def dispatch_ready_tasks():
    tasks = ready_tasks()
    if not tasks:
        tasks = [{"id": "inspect-state", "title": "inspect workspace state and refresh context", "source": "system", "status": "ready"}]
    state.write_json(QUEUE / "dispatch.json", {"time": state.utcnow(), "tasks": tasks})
    return tasks


def write_worker_queues(count=4):
    state.ensure_dir(QUEUE)
    tasks = dispatch_ready_tasks()
    for worker in range(1, count + 1):
        task = tasks[(worker - 1) % len(tasks)].copy()
        task["worker"] = worker
        task["queued_at"] = state.utcnow()
        state.write_json(QUEUE / ("worker-" + str(worker) + ".task.json"), task)
    return count


def load_module_context(worker):
    task_path = QUEUE / ("worker-" + str(worker) + ".task.json")
    task = state.read_json(task_path, {"id": "none", "title": "no queued task"})
    regenerate_all_module_summaries()
    write_roadmap_digest()
    payload = {"time": state.utcnow(), "worker": worker, "task": task, "project": active_project()}
    state.write_json(QUEUE / ("worker-" + str(worker) + ".context.json"), payload)
    return payload


def rebuild():
    ensure_project()
    regenerate_all_module_summaries()
    regenerate_architecture()
    regenerate_roadmap_digest()
    return True


def verify_current():
    base = project_path()
    required = [base / "context" / "modules.json", base / "context" / "architecture.md", base / "context" / "roadmap-digest.md"]
    return all(path.exists() and path.stat().st_size > 0 for path in required)


def load_year_inputs():
    return rebuild()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: context.py COMMAND [--worker N]", file=sys.stderr)
        return 2
    command = argv[0]
    worker = None
    if "--worker" in argv:
        index = argv.index("--worker")
        if index + 1 < len(argv):
            worker = int(argv[index + 1])
    if command == "load-year-inputs":
        load_year_inputs()
        return 0
    if command == "dispatch-ready-tasks":
        dispatch_ready_tasks()
        return 0
    if command == "write-worker-queues":
        write_worker_queues()
        return 0
    if command == "load-module-context":
        load_module_context(worker or 1)
        return 0
    if command == "rebuild":
        return 0 if rebuild() else 1
    if command == "regenerate-all-module-summaries":
        regenerate_all_module_summaries()
        return 0
    if command == "regenerate-architecture":
        regenerate_architecture()
        return 0
    if command == "regenerate-roadmap-digest":
        regenerate_roadmap_digest()
        return 0
    if command == "verify-current":
        return 0 if verify_current() else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
