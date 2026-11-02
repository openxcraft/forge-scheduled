#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=${FORGE_WORK:-/work}
mkdir -p "$WORK/schedules" "$WORK/runtime/queue" "$WORK/gates/core" "$WORK/gates/project" "$WORK/schemas" "$WORK/evidence" "$WORK/decisions" "$WORK/projects/default/roadmap" "$WORK/projects/default/contracts" "$WORK/projects/default/context" "$WORK/projects/default/src" "$WORK/projects/default/tests" "$WORK/projects/default/docs" "$WORK/projects/default/evidence" "$WORK/projects/default/decisions" "$WORK/ledger" "$WORK/budget" "$WORK/reports" "$WORK/keys" "$WORK/archive"
if [ "$ROOT" != "$WORK" ]; then
  cp -a "$ROOT/schedules/." "$WORK/schedules/"
  cp -a "$ROOT/runtime/." "$WORK/runtime/"
  cp -a "$ROOT/gates/." "$WORK/gates/"
  cp -a "$ROOT/schemas/." "$WORK/schemas/"
  cp "$ROOT/README.md" "$ROOT/LICENSE" "$WORK/"
fi
if [ ! -d "$WORK/.git" ]; then git init -q "$WORK"; fi
git -C "$WORK" config user.name forge-system
git -C "$WORK" config user.email forge@system.invalid
git -C "$WORK" config commit.gpgsign true
git -C "$WORK" config gpg.format ssh
if [ ! -f "$WORK/keys/current.key" ]; then
  openssl genpkey -algorithm ED25519 -out "$WORK/keys/current.key"
  chmod 600 "$WORK/keys/current.key"
fi
if [ ! -f "$WORK/keys/current.pub" ]; then openssl pkey -in "$WORK/keys/current.key" -pubout -out "$WORK/keys/current.pub"; fi
if [ ! -f "$WORK/keys/git-ed25519" ]; then
  ssh-keygen -q -t ed25519 -N "" -f "$WORK/keys/git-ed25519"
  chmod 600 "$WORK/keys/git-ed25519"
fi
git -C "$WORK" config user.signingkey "$WORK/keys/git-ed25519"
printf 'forge-system ' > "$WORK/keys/allowed_signers"
cat "$WORK/keys/git-ed25519.pub" >> "$WORK/keys/allowed_signers"
git -C "$WORK" config gpg.ssh.allowedSignersFile "$WORK/keys/allowed_signers"
if [ ! -f "$WORK/ledger/state.json" ]; then printf '{"cycle":0,"last_started":null,"last_finished":null}\n' > "$WORK/ledger/state.json"; fi
if [ ! -f "$WORK/projects/registry.json" ]; then printf '{"active":"default","projects":{"default":{"status":"active"}}}\n' > "$WORK/projects/registry.json"; fi
if [ ! -f "$WORK/budget/state.json" ]; then printf '{"date":"1970-01-01","daily_limit_usd":25,"spent_daily_usd":0,"spent_total_usd":0,"workers_paused":false}\n' > "$WORK/budget/state.json"; fi
if [ ! -f "$WORK/projects/default/charter.json" ]; then printf '{"id":"default","status":"active","objectives":["build useful software continuously"]}\n' > "$WORK/projects/default/charter.json"; fi
if [ ! -f "$WORK/projects/default/state.json" ]; then printf '{"status":"ready"}\n' > "$WORK/projects/default/state.json"; fi
if [ ! -f "$WORK/projects/default/roadmap/year.json" ]; then printf '{"id":"year-plan","period":"year","objectives":["build useful software continuously"],"tasks":[{"id":"foundation","title":"establish project foundation","status":"ready"}]}\n' > "$WORK/projects/default/roadmap/year.json"; fi
if [ ! -f "$WORK/projects/default/contracts/foundation.contract.json" ]; then printf '{"id":"foundation","project":"default","artifacts":[],"invariants":[{"kind":"exists","path":"state.json"}],"dependencies":[],"frozen":false}\n' > "$WORK/projects/default/contracts/foundation.contract.json"; fi
touch "$WORK/ledger/audit.ndjson" "$WORK/ledger/entries.jsonl"
chmod +x "$WORK/gates/core/"*.sh "$WORK/runtime/bootstrap.sh"
if [ -d "$ROOT/etc" ] && [ -w /etc ]; then
  mkdir -p /etc/systemd/system /etc/forge
  cp "$ROOT/etc/systemd/system/forge-runner.service" /etc/systemd/system/forge-runner.service
  cp "$ROOT/etc/forge/env" /etc/forge/env
  chmod 600 /etc/forge/env
  if command -v systemctl >/dev/null 2>&1; then systemctl daemon-reload || true; fi
fi
touch "$WORK/READY"
