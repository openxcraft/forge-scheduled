import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

WORK = Path(os.environ.get("FORGE_WORK", "/work"))
AUDIT = WORK / "ledger" / "audit.ndjson"
ENTRIES = WORK / "ledger" / "entries.jsonl"


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today():
    return datetime.now(timezone.utc).date().isoformat()


def as_path(value):
    return value if isinstance(value, Path) else Path(str(value))


def ensure_dir(path):
    path = as_path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path):
    path = as_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_write(path, data):
    path = ensure_parent(path)
    if isinstance(data, (dict, list)):
        raw = dumps(data) + "\n"
    elif isinstance(data, bytes):
        raw = data
    else:
        raw = str(data)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            payload = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return path


def write_json(path, value):
    return atomic_write(path, value)


def read_json(path, default=None):
    path = as_path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def append_line(path, value):
    path = ensure_parent(path)
    line = dumps(value) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return path


def audit(event):
    event.setdefault("time", utcnow())
    append_line(AUDIT, event)
    append_line(ENTRIES, event)


def sha256_bytes(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with as_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_evidence(raw, source=None):
    if isinstance(raw, (dict, list)):
        text = dumps(raw)
    elif isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = str(raw)
    result = {"time": utcnow(), "raw": text, "sha256": sha256_bytes(text)}
    if source is not None:
        result["source"] = str(source)
    return result


def make_decision(question, options, chosen, reason, verified_by=None):
    if chosen not in options:
        raise ValueError("chosen option must be present")
    return {
        "time": utcnow(),
        "question": str(question),
        "options": list(options),
        "chosen": chosen,
        "rejected": [item for item in options if item != chosen],
        "reason": str(reason),
        "verified_by": verified_by or "decision-present",
    }


def split_flow(text):
    parts = []
    start = 0
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def split_key(text):
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0:
            return text[:index].strip(), text[index + 1 :].strip()
    return text.strip(), ""


def parse_scalar(text):
    text = text.strip()
    if text == "":
        return ""
    if text.startswith('"') and text.endswith('"'):
        return json.loads(text)
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    lowered = text.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)", text):
        return float(text)
    return text


def parse_flow(text):
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [] if not inner else [parse_flow(part) for part in split_flow(inner)]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        result = {}
        if inner:
            for part in split_flow(inner):
                key, value = split_key(part)
                result[str(parse_scalar(key))] = parse_flow(value)
        return result
    return parse_scalar(text)


def yaml_lines(text):
    result = []
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.strip() == "" or raw.lstrip().startswith("---"):
            continue
        if raw.startswith("\t"):
            raise ValueError("tabs are not valid indentation at line " + str(number))
        indent = len(raw) - len(raw.lstrip(" "))
        result.append((indent, raw.strip(), number))
    return result


def parse_block(lines, index, indent):
    if index >= len(lines):
        return None, index
    if lines[index][0] < indent:
        return None, index
    if lines[index][1].startswith("- ") or lines[index][1] == "-":
        return parse_list(lines, index, indent)
    return parse_mapping(lines, index, indent)


def parse_mapping(lines, index, indent):
    result = {}
    while index < len(lines):
        current, text, number = lines[index]
        if current < indent:
            break
        if current != indent or text.startswith("- ") or text == "-":
            break
        key, value = split_key(text)
        if not key:
            raise ValueError("empty mapping key at line " + str(number))
        index += 1
        if value:
            result[key] = parse_flow(value)
        elif index < len(lines) and lines[index][0] > current:
            result[key], index = parse_block(lines, index, lines[index][0])
        else:
            result[key] = None
    return result, index


def parse_list(lines, index, indent):
    result = []
    while index < len(lines):
        current, text, number = lines[index]
        if current < indent:
            break
        if current != indent or not (text.startswith("- ") or text == "-"):
            break
        item_text = "" if text == "-" else text[2:].strip()
        index += 1
        if item_text:
            result.append(parse_flow(item_text))
        elif index < len(lines) and lines[index][0] > current:
            value, index = parse_block(lines, index, lines[index][0])
            result.append(value)
        else:
            result.append(None)
    return result, index


def load_yaml_text(text):
    lines = yaml_lines(text)
    if not lines:
        return None
    value, index = parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError("unexpected YAML content at line " + str(lines[index][2]))
    return value


def load_yaml(path):
    with as_path(path).open("r", encoding="utf-8") as handle:
        return load_yaml_text(handle.read())


def schema_type(value, expected):
    if isinstance(expected, list):
        return any(schema_type(value, item) for item in expected)
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, mapping[expected])


def resolve_ref(schema, root):
    reference = schema.get("$ref")
    if not reference:
        return schema
    if reference.startswith(chr(35) + "/definitions/"):
        return root.get("definitions", {}).get(reference.rsplit("/", 1)[-1], {})
    return {}


def validate_schema(value, schema, location="$", root=None):
    root = schema if root is None else root
    schema = resolve_ref(schema, root)
    errors = []
    expected = schema.get("type")
    if expected and not schema_type(value, expected):
        return [location + " expected " + (", ".join(expected) if isinstance(expected, list) else expected)]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(location + " must be one of " + repr(schema["enum"]))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(location + "." + key + " is required")
        properties = schema.get("properties", {})
        for key, child in properties.items():
            if key in value:
                errors.extend(validate_schema(value[key], child, location + "." + key, root))
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            for key in sorted(extra):
                errors.append(location + "." + key + " is not allowed")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], location + "[" + str(index) + "]", root))
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(location + " does not match required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(location + " is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(location + " is above maximum")
    return errors


def rotate_file(path, archive_dir, keep=7):
    path = as_path(path)
    if not path.exists():
        return None
    ensure_dir(archive_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = archive_dir / (path.name + "." + stamp)
    shutil.copy2(path, target)
    atomic_write(path, "")
    archives = sorted(archive_dir.glob(path.name + ".*"))
    for old in archives[:-keep]:
        old.unlink()
    return target


def disk_percent(path):
    usage = shutil.disk_usage(str(path))
    return int(usage.used * 100 / usage.total)


def sleep_seconds(policy, attempt):
    mode = policy.get("backoff", "linear") if isinstance(policy, dict) else "linear"
    base = 1 if mode == "linear" else 2 ** max(0, attempt - 1)
    return min(30, base)


def rotate_ledger():
    archive = WORK / "archive" / "ledger"
    rotate_file(WORK / "ledger" / "entries.jsonl", archive)
    rotate_file(WORK / "ledger" / "audit.ndjson", archive)
    state_path = WORK / "ledger" / "state.json"
    if not state_path.exists():
        write_json(state_path, {"cycle": 0, "last_started": None, "last_finished": None})
    return True


def prune_archives(soft_limit=85, hard_limit=95):
    root = WORK / "archive"
    ensure_dir(root)
    if disk_percent(WORK) < hard_limit:
        return True
    files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.stat().st_mtime)
    for path in files:
        if disk_percent(WORK) < soft_limit:
            break
        path.unlink()
    return disk_percent(WORK) < hard_limit


def validate_schedules():
    schema = read_json(WORK / "schemas" / "schedule.json")
    failed = False
    for path in sorted((WORK / "schedules").glob("*.yaml")):
        try:
            errors = validate_schema(load_yaml(path), schema)
        except Exception as exc:
            errors = [str(exc)]
        print(path.name + ": " + ("ok" if not errors else "; ".join(errors)))
        failed = failed or bool(errors)
    return not failed


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["rotate-ledger"]:
        return 0 if rotate_ledger() else 1
    if len(argv) == 5 and argv[0] == "prune-archives" and argv[1] == "--soft-limit" and argv[3] == "--hard-limit":
        return 0 if prune_archives(int(argv[2]), int(argv[4])) else 1
    if argv == ["validate-schedules"]:
        return 0 if validate_schedules() else 1
    print("usage: state.py rotate-ledger|validate-schedules|prune-archives --soft-limit N --hard-limit N", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
