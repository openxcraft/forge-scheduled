import json
import os
import subprocess
import sys
from pathlib import Path

import budget
import state


def local_generate(template, context=None):
    context = context or {}
    now = state.utcnow()
    if "refactor" in template:
        return {
            "id": template,
            "period": "refactor",
            "created_at": now,
            "objectives": ["reduce coupling", "preserve behavior", "increase gate signal"],
            "tasks": [
                {"id": "assess", "title": "assess module boundaries", "status": "ready"},
                {"id": "refactor", "title": "apply smallest safe refactor", "status": "ready"},
                {"id": "verify", "title": "run all gates", "status": "ready"},
            ],
        }
    if template.startswith(("year", "month", "week", "day", "hour")):
        period = template.split("-", 1)[0]
        return {
            "id": template,
            "period": period,
            "created_at": now,
            "objectives": ["advance the active project", "preserve contracts", "keep evidence complete"],
            "tasks": [
                {"id": period + "-inspect", "title": "inspect current project state", "status": "ready"},
                {"id": period + "-build", "title": "complete the highest-value implementation increment", "status": "ready"},
                {"id": period + "-verify", "title": "run tests and gates", "status": "ready"},
            ],
        }
    if template == "worker-task":
        return {
            "status": "completed",
            "summary": "deterministic local worker output",
            "changes": [],
            "tests": [],
            "confidence": 0.75,
            "created_at": now,
            "context": context,
        }
    return {"id": template or "local", "created_at": now, "result": "completed", "context": context}


def command_generate(template, context=None):
    command = os.environ.get("FORGE_LLM_COMMAND", "").strip()
    if not command:
        raise RuntimeError("command provider is not configured")
    payload = state.dumps({"template": template, "context": context or {}, "time": state.utcnow()})
    completed = subprocess.run(
        command,
        input=payload,
        text=True,
        shell=True,
        capture_output=True,
        timeout=int(os.environ.get("FORGE_LLM_TIMEOUT", "120")),
        cwd=str(state.WORK),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "provider failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"text": completed.stdout}


def generate(template, output=None, schema=None, context=None):
    if not budget.available(0.001):
        budget.pause_workers("budget exhausted")
        raise RuntimeError("budget exhausted")
    providers = [item.strip() for item in os.environ.get("FORGE_LLM_PROVIDERS", "local").split(",") if item.strip()]
    errors = []
    result = None
    for provider in providers:
        try:
            if provider == "command":
                result = command_generate(template, context)
            elif provider == "local":
                result = local_generate(template, context)
            else:
                raise RuntimeError("unknown provider " + provider)
            break
        except Exception as exc:
            errors.append(provider + ": " + str(exc))
    if result is None:
        raise RuntimeError("; ".join(errors) or "no provider available")
    schema_path = state.WORK / "schemas" / (schema + ".json") if schema else None
    if schema_path and schema_path.exists():
        errors = state.validate_schema(result, state.read_json(schema_path))
        if errors:
            raise RuntimeError("schema validation failed: " + "; ".join(errors))
    budget.spend(0.001, "llm:" + str(template))
    if output:
        state.atomic_write(output, result)
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "generate":
        print("usage: llm.py generate --template NAME [--output PATH] [--schema NAME]", file=sys.stderr)
        return 2
    template = None
    output = None
    schema = None
    index = 1
    while index < len(argv):
        if argv[index] == "--template" and index + 1 < len(argv):
            template = argv[index + 1]
            index += 2
        elif argv[index] == "--output" and index + 1 < len(argv):
            output = argv[index + 1]
            index += 2
        elif argv[index] == "--schema" and index + 1 < len(argv):
            schema = argv[index + 1]
            index += 2
        else:
            return 2
    generate(template, output, schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
