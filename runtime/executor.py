import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import budget
import context
import contracts
import gates
import llm
import state

QUEUE = state.WORK / "runtime" / "queue"


def expand(value, cycle):
    active = context.active_project()
    if isinstance(value, str):
        return value.replace("<n>", str(cycle)).replace("<active>", active)
    if isinstance(value, list):
        return [expand(item, cycle) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, cycle) for key, item in value.items()}
    return value


def condition_ok(item, cycle):
    item = expand(item, cycle)
    kind = item.get("kind")
    if kind == "exists":
        return Path(item.get("path", "")).exists()
    if kind == "absent":
        return not Path(item.get("path", "")).exists()
    if kind == "equals":
        path = Path(item.get("path", ""))
        if not path.exists():
            return False
        expected = item.get("text", item.get("content"))
        if expected is not None:
            return path.read_text(encoding="utf-8") == str(expected)
        return state.read_json(path, None) == item.get("value")
    if kind == "matches":
        path = Path(item.get("path", ""))
        return path.exists() and re.search(str(item.get("pattern", ".*")), path.read_text(encoding="utf-8")) is not None
    if kind == "command":
        completed = subprocess.run(str(item.get("cmd", "false")), shell=True, cwd=str(state.WORK), capture_output=True, timeout=int(item.get("timeout", 120)))
        return completed.returncode == 0
    if kind == "gate":
        return gates.run_gate(str(item.get("gate_id")))["ok"]
    return False


def run_command(command, timeout):
    env = os.environ.copy()
    env["FORGE_WORK"] = str(state.WORK)
    completed = subprocess.run(command, shell=True, cwd=str(state.WORK), env=env, text=True, capture_output=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "command failed").strip())
    return {"stdout": completed.stdout, "stderr": completed.stderr}


def apply_effect(effect, cycle, timeout):
    effect = expand(effect, cycle)
    kind = effect.get("kind")
    if kind == "write":
        path = Path(effect["path"])
        if "json" in effect:
            state.write_json(path, effect["json"])
        else:
            state.atomic_write(path, str(effect.get("content", effect.get("text", ""))))
        return {"path": str(path)}
    if kind == "append":
        path = state.ensure_parent(Path(effect["path"]))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(str(effect.get("content", effect.get("text", ""))) + "\n")
        return {"path": str(path)}
    if kind == "run":
        return run_command(str(effect.get("cmd", "false")), timeout)
    if kind == "delete":
        path = Path(effect["path"])
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        return {"path": str(path)}
    if kind == "move":
        source = Path(effect["source"])
        target = state.ensure_parent(Path(effect["target"]))
        os.replace(source, target)
        return {"source": str(source), "target": str(target)}
    if kind == "evidence":
        raw = effect.get("raw", {"effect": effect, "cycle": cycle})
        payload = state.make_evidence(raw, effect.get("source"))
        state.write_json(effect["path"], payload)
        return {"path": effect["path"], "sha256": payload["sha256"]}
    if kind == "decide":
        payload = state.make_decision(effect.get("question", "effect decision"), effect.get("options", ["accept", "reject"]), effect.get("chosen", "accept"), effect.get("reason", "policy selected this option"), effect.get("verified_by"))
        state.write_json(effect["path"], payload)
        return {"path": effect["path"], "chosen": payload["chosen"]}
    if kind == "llm":
        result = llm.generate(str(effect.get("prompt_template", "local")), effect.get("output"), effect.get("schema"), {"cycle": cycle, "effect": effect})
        return {"output": effect.get("output"), "keys": sorted(result) if isinstance(result, dict) else []}
    raise RuntimeError("unsupported effect kind " + str(kind))


def artifact_paths(task_id, cycle, index):
    token = uuid.uuid4().hex[:12]
    base = "effect-" + task_id + "-" + str(cycle) + "-" + str(index) + "-" + token
    return state.WORK / "evidence" / (base + ".json"), state.WORK / "decisions" / (base + ".json")


def record_effect_artifacts(task_id, cycle, index, effect, result):
    evidence_path, decision_path = artifact_paths(task_id, cycle, index)
    state.write_json(evidence_path, state.make_evidence({"effect": effect, "result": result}, "executor"))
    decision = state.make_decision("apply effect " + str(effect.get("kind")), ["apply", "skip"], "apply", "effect completed and was recorded", "decision-present")
    state.write_json(decision_path, decision)


def attempts(retry):
    retry = retry if isinstance(retry, dict) else {}
    try:
        return max(1, int(retry.get("max", 0)) + 1)
    except Exception:
        return 1


def rollback(actions, cycle):
    results = []
    for action in actions or []:
        try:
            results.append({"action": action, "result": apply_effect(action, cycle, 60), "ok": True})
        except Exception as exc:
            results.append({"action": action, "error": str(exc), "ok": False})
    return results


def load_task(task_id, task_file=None):
    if task_file:
        data = state.read_json(task_file, None)
        if data is not None:
            return data
        return state.load_yaml(task_file)
    path = state.WORK / "schedules" / (task_id + ".yaml")
    return state.load_yaml(path)


def next_cycle():
    path = state.WORK / "ledger" / "state.json"
    data = state.read_json(path, {"cycle": 0}) or {"cycle": 0}
    data["cycle"] = int(data.get("cycle", 0)) + 1
    data["last_started"] = state.utcnow()
    state.write_json(path, data)
    return data["cycle"]


def finish_cycle(cycle, status):
    path = state.WORK / "ledger" / "state.json"
    data = state.read_json(path, {"cycle": cycle}) or {"cycle": cycle}
    data["cycle"] = cycle
    data["last_finished"] = state.utcnow()
    data["last_status"] = status
    state.write_json(path, data)


def run_task(task_id, task_file=None):
    task = load_task(task_id, task_file)
    cycle = next_cycle()
    status = "failed"
    error = None
    try:
        for item in task.get("preconditions", []) or []:
            if not condition_ok(item, cycle):
                raise RuntimeError("precondition failed: " + state.dumps(item))
        timeout = int(task.get("policy", {}).get("budget_minutes", 5)) * 60
        for index, effect in enumerate(task.get("effects", []) or [], 1):
            last = None
            for attempt in range(1, attempts(task.get("retry", {})) + 1):
                try:
                    result = apply_effect(effect, cycle, timeout)
                    record_effect_artifacts(task_id, cycle, index, effect, result)
                    last = None
                    break
                except Exception as exc:
                    last = exc
                    if attempt < attempts(task.get("retry", {})):
                        time.sleep(state.sleep_seconds(task.get("retry", {}), attempt))
            if last is not None:
                raise last
        for item in task.get("postconditions", []) or []:
            ok = False
            for attempt in range(1, attempts(task.get("retry", {})) + 1):
                if condition_ok(item, cycle):
                    ok = True
                    break
                if attempt < attempts(task.get("retry", {})):
                    time.sleep(state.sleep_seconds(task.get("retry", {}), attempt))
            if not ok:
                raise RuntimeError("postcondition failed: " + state.dumps(item))
        status = "passed"
        return 0
    except Exception as exc:
        error = str(exc)
        rollback(task.get("rollback", []), cycle)
        policy = task.get("policy", {})
        if policy.get("on_fail") == "halt":
            state.atomic_write(state.WORK / "STOP", "halt requested by policy\n")
        return 1
    finally:
        finish_cycle(cycle, status)
        state.audit({"type": "task", "task": task_id, "cycle": cycle, "status": status, "error": error})


def worker_paths(worker):
    return {
        "task": QUEUE / (worker + ".task.json"),
        "output": QUEUE / (worker + ".output.json"),
        "done": QUEUE / (worker + ".done"),
        "failed": QUEUE / (worker + ".failed"),
        "backup": QUEUE / (worker + ".backup.json"),
    }


def worker_claim(worker):
    if (state.WORK / "budget" / "workers.paused").exists():
        raise RuntimeError("workers paused by budget")
    paths = worker_paths(worker)
    task = state.read_json(paths["task"], None)
    if not task:
        raise RuntimeError("task missing")
    task["claimed_at"] = state.utcnow()
    state.write_json(paths["task"], task)
    state.write_json(paths["backup"], {"operations": []})
    return task


def backup_file(path, backups):
    item = {"path": str(path), "existed": path.exists()}
    if path.exists() and path.is_file():
        item["content"] = path.read_text(encoding="utf-8")
    backups.append(item)


def worker_apply(worker):
    paths = worker_paths(worker)
    output = state.read_json(paths["output"], {"changes": []}) or {"changes": []}
    backups = []
    for change in output.get("changes", output.get("operations", [])):
        action = expand(change, 0)
        kind = action.get("kind")
        if kind in ("write", "append", "delete"):
            backup_file(Path(action["path"]), backups)
        apply_effect(action, 0, 300)
    state.write_json(paths["backup"], {"operations": backups})
    return True


def worker_rollback(worker):
    paths = worker_paths(worker)
    backup = state.read_json(paths["backup"], {"operations": []}) or {"operations": []}
    for item in reversed(backup.get("operations", [])):
        path = Path(item["path"])
        if item.get("existed"):
            state.atomic_write(path, item.get("content", ""))
        elif path.exists():
            path.unlink()
    return True


def worker_local_gates(worker):
    names = ["no-comments", "no-identity", "no-secrets", "complexity", "security"]
    results = [gates.run_gate(name) for name in names]
    ok = all(item["ok"] for item in results)
    paths = worker_paths(worker)
    target = paths["done"] if ok else paths["failed"]
    state.write_json(target, {"time": state.utcnow(), "worker": worker, "results": results})
    other = paths["failed"] if ok else paths["done"]
    if other.exists():
        other.unlink()
    return ok


def integrator_drain():
    drained = []
    for path in sorted(QUEUE.glob("*.done")):
        drained.append(path.name)
        state.append_line(state.WORK / "ledger" / "integrated.jsonl", {"time": state.utcnow(), "worker_result": path.name})
        stem = path.with_suffix("")
        for suffix in (".task.json", ".output.json", ".context.json", ".backup.json", ".done", ".failed"):
            item = QUEUE / (stem.name + suffix)
            if item.exists():
                item.unlink()
    return drained


def audit_lines(limit=100):
    path = state.WORK / "ledger" / "audit.ndjson"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    result = []
    for line in lines:
        try:
            result.append(__import__("json").loads(line))
        except Exception:
            pass
    return result


def monitor_trends():
    rows = audit_lines()
    passed = sum(1 for row in rows if row.get("status") == "passed")
    failed = sum(1 for row in rows if row.get("status") == "failed")
    data = {"time": state.utcnow(), "sample": len(rows), "passed": passed, "failed": failed, "success_rate": (passed / len(rows) if rows else 1.0)}
    state.write_json(state.WORK / "reports" / "trends.json", data)
    return data


def monitor_coherence():
    data = {"time": state.utcnow(), "contracts_ok": contracts.verify_all()[0], "context_current": context.verify_current(), "graph_cycles": len(contracts.detect_cycles())}
    data["score"] = (int(data["contracts_ok"]) + int(data["context_current"]) + int(data["graph_cycles"] == 0)) / 3
    state.write_json(state.WORK / "reports" / "coherence.json", data)
    return data


def health_build():
    data = {"time": state.utcnow(), "ledger_exists": (state.WORK / "ledger" / "state.json").exists(), "budget": budget.status(), "trends": monitor_trends(), "coherence": monitor_coherence()}
    state.write_json(state.WORK / "reports" / "health.json", data)
    return data


def metrics_emit():
    health = health_build()
    lines = [
        "forge_audit_sample " + str(health["trends"]["sample"]),
        "forge_success_rate " + str(health["trends"]["success_rate"]),
        "forge_budget_spent_usd " + str(health["budget"].get("spent_daily_usd", 0)),
        "forge_coherence_score " + str(health["coherence"]["score"]),
    ]
    state.atomic_write(state.WORK / "reports" / "metrics.prom", "\n".join(lines) + "\n")
    return lines


def docs_regenerate_all():
    base = context.ensure_project()
    regenerate = ["Documentation", "", "Generated: " + state.utcnow(), "", "Project: " + base.name, ""]
    state.atomic_write(base / "docs" / "index.md", "\n".join(regenerate))
    return True


def refactor_assess():
    coherence = monitor_coherence()
    result = {"time": state.utcnow(), "coherence": coherence, "recommended": coherence["score"] < 0.8}
    state.write_json(state.WORK / "reports" / "refactor-assessment.json", result)
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: executor.py run TASK [--task-file PATH] | ...", file=sys.stderr)
        return 2
    try:
        if argv[0] == "run" and len(argv) >= 2:
            task_file = None
            if "--task-file" in argv:
                index = argv.index("--task-file")
                if index + 1 < len(argv):
                    task_file = argv[index + 1]
            return run_task(argv[1], task_file)
        if len(argv) == 2 and argv[0].startswith("worker-"):
            worker = argv[0]
            if argv[1] in ("claim", "apply", "local-gates", "rollback"):
                action = argv[1]
                if action == "claim":
                    worker_claim(worker)
                    return 0
                if action == "apply":
                    worker_apply(worker)
                    return 0
                if action == "local-gates":
                    return 0 if worker_local_gates(worker) else 1
                worker_rollback(worker)
                return 0
        if argv[:2] == ["integrator", "drain"]:
            integrator_drain()
            return 0
        if argv[:2] == ["monitor", "trends"]:
            monitor_trends()
            return 0
        if argv[:2] == ["monitor", "coherence"]:
            monitor_coherence()
            return 0
        if argv[:2] == ["monitor", "budget"]:
            budget.status()
            return 0
        if argv[:2] == ["coherence", "measure"] or argv[:2] == ["coherence", "record"]:
            monitor_coherence()
            return 0
        if argv[:2] == ["docs", "regenerate-all"]:
            docs_regenerate_all()
            return 0
        if argv[:2] == ["health", "build"]:
            health_build()
            return 0
        if argv[:2] == ["metrics", "emit"]:
            metrics_emit()
            return 0
        if argv[:2] == ["refactor", "assess"]:
            refactor_assess()
            return 0
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
