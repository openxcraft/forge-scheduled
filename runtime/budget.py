import os
import sys
from pathlib import Path

import state

FILE = state.WORK / "budget" / "state.json"
PAUSE = state.WORK / "budget" / "workers.paused"


def defaults():
    return {
        "date": state.today(),
        "daily_limit_usd": float(os.environ.get("FORGE_DAILY_BUDGET_USD", "25")),
        "spent_daily_usd": 0.0,
        "spent_total_usd": 0.0,
        "workers_paused": False,
        "updated_at": state.utcnow(),
    }


def load():
    data = state.read_json(FILE, None)
    if not isinstance(data, dict):
        data = defaults()
    if data.get("date") != state.today():
        data = reset()
    return data


def save(data):
    data["updated_at"] = state.utcnow()
    state.write_json(FILE, data)
    return data


def reset():
    data = defaults()
    data["spent_daily_usd"] = 0.0
    data["spent_total_usd"] = float(state.read_json(FILE, {}).get("spent_total_usd", 0.0) or 0.0)
    data["workers_paused"] = False
    save(data)
    if PAUSE.exists():
        PAUSE.unlink()
    return data


def available(amount=0.0):
    data = load()
    return float(data.get("spent_daily_usd", 0.0)) + float(amount) <= float(data.get("daily_limit_usd", 0.0))


def spend(amount, reason):
    amount = float(amount)
    data = load()
    if not available(amount):
        pause_workers("budget exhausted")
        raise RuntimeError("budget exhausted")
    data["spent_daily_usd"] = round(float(data.get("spent_daily_usd", 0.0)) + amount, 6)
    data["spent_total_usd"] = round(float(data.get("spent_total_usd", 0.0)) + amount, 6)
    save(data)
    state.append_line(state.WORK / "budget" / "spend.jsonl", {"time": state.utcnow(), "amount": amount, "reason": reason})
    return data


def pause_workers(reason):
    data = load()
    data["workers_paused"] = True
    save(data)
    state.atomic_write(PAUSE, reason + "\n")
    return data


def status():
    return load()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["reset-daily"]:
        reset()
        return 0
    if argv == ["status"]:
        print(state.dumps(status()))
        return 0
    if len(argv) == 3 and argv[0] == "spend":
        spend(float(argv[1]), argv[2])
        return 0
    if len(argv) == 2 and argv[0] == "available":
        return 0 if available(float(argv[1])) else 1
    print("usage: budget.py reset-daily|status|available AMOUNT|spend AMOUNT REASON", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
