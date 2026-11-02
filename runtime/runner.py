import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import state

RUNTIME = state.WORK / "runtime"
QUEUE = RUNTIME / "queue"
STATE_FILE = RUNTIME / "runner-state.json"
STOP = False


def handle_term(signum, frame):
    global STOP
    STOP = True


def stop_paths():
    paths = [state.WORK / "STOP"]
    for parent in state.WORK.parents:
        paths.append(parent / "STOP")
    return paths


def stop_present():
    return any(path.exists() for path in stop_paths())


def field_values(text, low, high, dow=False):
    values = set()
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            start, end = [int(item) for item in part.split("-", 1)]
        else:
            start = end = int(part)
        for value in range(start, end + 1, step):
            if dow and value == 7:
                value = 0
            if low <= value <= high:
                values.add(value)
    return values


def cron_due(expression, moment):
    if expression == "@reboot":
        return True
    fields = str(expression).split()
    if len(fields) != 5:
        return False
    minute = field_values(fields[0], 0, 59)
    hour = field_values(fields[1], 0, 23)
    day = field_values(fields[2], 1, 31)
    month = field_values(fields[3], 1, 12)
    weekday = field_values(fields[4], 0, 7, True)
    cron_weekday = (moment.weekday() + 1) % 7
    return moment.minute in minute and moment.hour in hour and moment.day in day and moment.month in month and cron_weekday in weekday


def load_schedules():
    result = {}
    schema_path = state.WORK / "schemas" / "schedule.json"
    schema = state.read_json(schema_path, None) if schema_path.exists() else None
    for path in sorted((state.WORK / "schedules").glob("*.yaml")):
        try:
            data = state.load_yaml(path)
            if schema:
                errors = state.validate_schema(data, schema)
                if errors:
                    raise RuntimeError("; ".join(errors))
            result[data["id"]] = data
        except Exception as exc:
            state.audit({"type": "schedule-error", "path": str(path), "error": str(exc), "status": "failed"})
    return result


def due_tasks(schedules, moment, run_state):
    due = {}
    minute_key = moment.strftime("%Y-%m-%dT%H:%MZ")
    for task_id, task in schedules.items():
        cron = task.get("cron", "")
        if cron == "@reboot":
            key = "reboot:" + str(os.getpid())
            if run_state.get("last", {}).get(task_id) != key:
                due[task_id] = task
                run_state.setdefault("next", {})[task_id] = key
        elif cron_due(cron, moment):
            if run_state.get("last", {}).get(task_id) != minute_key:
                due[task_id] = task
                run_state.setdefault("next", {})[task_id] = minute_key
    return order_due(due)


def order_due(due):
    ordered = []
    temporary = set()
    permanent = set()

    def visit(task_id):
        if task_id in permanent or task_id not in due:
            return
        if task_id in temporary:
            raise RuntimeError("dependency cycle at " + task_id)
        temporary.add(task_id)
        for dependency in due[task_id].get("depends_on", []) or []:
            visit(dependency)
        temporary.remove(task_id)
        permanent.add(task_id)
        ordered.append(task_id)

    for task_id in sorted(due):
        visit(task_id)
    return [due[task_id] for task_id in ordered]


def write_task_file(task):
    state.ensure_dir(QUEUE)
    path = QUEUE / ("runner-" + task["id"] + ".json")
    state.write_json(path, task)
    return path


def invoke(task):
    task_file = write_task_file(task)
    env = os.environ.copy()
    env["FORGE_WORK"] = str(state.WORK)
    command = [sys.executable, str(RUNTIME / "executor.py"), "run", task["id"], "--task-file", str(task_file)]
    started = state.utcnow()
    try:
        completed = subprocess.run(command, cwd=str(state.WORK), env=env, text=True, capture_output=True, timeout=int(task.get("policy", {}).get("budget_minutes", 5)) * 60 + 30)
        status = "passed" if completed.returncode == 0 else "failed"
        error = completed.stderr.strip() if completed.returncode else None
    except Exception as exc:
        status = "failed"
        error = str(exc)
    state.audit({"type": "runner-attempt", "task": task["id"], "started": started, "status": status, "error": error})
    return status == "passed"


def interruptible_sleep(seconds):
    end = time.monotonic() + seconds
    while not STOP and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def halt_sleep():
    state.audit({"type": "runner-halt", "reason": "stop file present", "status": "halted"})
    while not STOP and stop_present():
        time.sleep(10)
    state.audit({"type": "runner-resume", "reason": "stop file absent", "status": "running"})


def cycle(schedules, loaded_at, run_state):
    now = time.monotonic()
    if now - loaded_at >= 60:
        schedules = load_schedules()
        loaded_at = now
    moment = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    due = due_tasks(schedules, moment, run_state)
    for task in due:
        if STOP:
            return schedules, loaded_at
        if stop_present():
            halt_sleep()
            continue
        invoke(task)
        run_state.setdefault("last", {})[task["id"]] = run_state.get("next", {}).get(task["id"])
        state.write_json(STATE_FILE, run_state)
    interruptible_sleep(30)
    return schedules, loaded_at


def main():
    signal.signal(signal.SIGTERM, handle_term)
    state.ensure_dir(QUEUE)
    state.ensure_dir(state.WORK / "ledger")
    run_state = state.read_json(STATE_FILE, {"last": {}, "next": {}}) or {"last": {}, "next": {}}
    schedules = {}
    loaded_at = 0
    while not STOP:
        try:
            schedules, loaded_at = cycle(schedules, loaded_at, run_state)
        except Exception as exc:
            state.audit({"type": "runner-exception", "error": str(exc), "status": "restarting"})
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
