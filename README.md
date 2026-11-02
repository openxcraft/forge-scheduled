# Forge Scheduled

Forge Scheduled is a perpetual, autonomous build scheduler. It reads 24 YAML task definitions, resolves dependencies, executes effects, verifies gates, records evidence and decisions, and resumes from atomic state after interruption.

## File tree

```text
.
├── etc
│   ├── forge
│   │   └── env
│   └── systemd
│       └── system
│           └── forge-runner.service
├── gates
│   └── core
│       ├── commit-signed.sh
│       ├── complexity.sh
│       ├── contract-conformance.sh
│       ├── coverage.sh
│       ├── decision-present.sh
│       ├── docs-executable.sh
│       ├── evidence-present.sh
│       ├── no-comments.sh
│       ├── no-identity.sh
│       ├── no-secrets.sh
│       ├── security.sh
│       └── stop-honored.sh
├── runtime
│   ├── bootstrap.sh
│   ├── budget.py
│   ├── context.py
│   ├── contracts.py
│   ├── executor.py
│   ├── gates.py
│   ├── llm.py
│   ├── runner.py
│   └── state.py
├── schedules
│   ├── archive-prune.yaml
│   ├── bootstrap-once.yaml
│   ├── budget-reset.yaml
│   ├── coherence-check.yaml
│   ├── context-refresh.yaml
│   ├── contract-audit.yaml
│   ├── dependency-graph.yaml
│   ├── dispatch.yaml
│   ├── docs-refresh.yaml
│   ├── gate-audit.yaml
│   ├── health-report.yaml
│   ├── integrate.yaml
│   ├── ledger-rotate.yaml
│   ├── monitor.yaml
│   ├── plan-day.yaml
│   ├── plan-hour.yaml
│   ├── plan-month.yaml
│   ├── plan-week.yaml
│   ├── plan-year.yaml
│   ├── refactor-trigger.yaml
│   ├── worker-1.yaml
│   ├── worker-2.yaml
│   ├── worker-3.yaml
│   └── worker-4.yaml
├── schemas
│   ├── charter.json
│   ├── contract.json
│   ├── decision.json
│   ├── evidence.json
│   ├── plan.json
│   ├── review.json
│   ├── roadmap.json
│   ├── schedule.json
│   └── verdict.json
├── LICENSE
└── README.md
```

## Installation

Run these commands on a host where the repository checkout is the intended `/work` content:

```sh
sudo mkdir -p /work
sudo cp -a . /work/
sudo /work/runtime/bootstrap.sh
sudo systemctl enable --now forge-runner.service
```

The runner checks `/work/STOP` and `/STOP`. Create either file to halt new work; remove it to resume.

## Operations

1. Runner is not active:

```sh
sudo systemctl status forge-runner.service
sudo systemctl restart forge-runner.service
journalctl -u forge-runner.service -n 100 --no-pager
```

2. A schedule is invalid:

```sh
python3 /work/runtime/state.py validate-schedules
sudo systemctl restart forge-runner.service
```

3. The runner is halted by STOP:

```sh
ls -l /work/STOP /STOP 2>/dev/null || true
sudo rm -f /work/STOP /STOP
sudo systemctl restart forge-runner.service
```

4. A worker queue is stuck:

```sh
ls -l /work/runtime/queue
sudo mv /work/runtime/queue/*.task.json /work/archive/ 2>/dev/null || true
sudo rm -f /work/runtime/queue/*.failed /work/runtime/queue/*.done
sudo systemctl restart forge-runner.service
```

5. Disk usage approaches the hard limit:

```sh
df -h /work
python3 /work/runtime/state.py prune-archives --soft-limit 85 --hard-limit 95
sudo systemctl restart forge-runner.service
```

## Monitoring

Daily health inspection:

```sh
tail -n 100 /work/ledger/audit.ndjson
jq -c . /work/ledger/entries.jsonl >/dev/null
cat /work/reports/health.json | jq .
cat /work/reports/coherence.json | jq .
systemctl is-active forge-runner.service
systemctl show forge-runner.service -p ActiveState -p SubState -p NRestarts
python3 /work/runtime/budget.py status
python3 /work/runtime/context.py verify-current
python3 /work/runtime/contracts.py verify-all
python3 /work/runtime/gates.py full-suite
```

Schedule inspection:

```sh
grep -L 'human_gate: none' /work/schedules/*.yaml
python3 - <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, '/work/runtime')
import state
schema = json.loads(Path('/work/schemas/schedule.json').read_text())
for path in sorted(Path('/work/schedules').glob('*.yaml')):
    errors = state.validate_schema(state.load_yaml(path), schema)
    print(path.name, 'ok' if not errors else errors)
PY
```

## License

All generated content is licensed under CC0 1.0. See `LICENSE`.
