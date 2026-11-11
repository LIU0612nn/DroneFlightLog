#!/usr/bin/env bash
# Run as root on the existing Alibaba Cloud host. Keeps untracked data in place.
set -Eeuo pipefail

repo=/opt/drone-flight-report
branch=codex/report-hub-2026-11-11
service=drone-report

if [[ $(id -u) -ne 0 ]]; then
    echo "Run this script as root (sudo -i)." >&2
    exit 1
fi
cd "$repo"
old_head=$(git rev-parse HEAD)
backup_dir="/root/drone-report-backup/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
printf '%s\n' "$old_head" > "$backup_dir/previous-head.txt"
git status --short > "$backup_dir/status-before.txt"
cp -a app.py "$backup_dir/app.py"
if [[ -f data/contact_messages.jsonl ]]; then
    cp -a data/contact_messages.jsonl "$backup_dir/contact_messages.jsonl"
fi

previous_stash=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
git stash push -m "pre-report-hub-$(date -u +%Y%m%dT%H%M%SZ)"
new_stash=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
stashed=0
if [[ -n "$new_stash" && "$new_stash" != "$previous_stash" ]]; then
    stashed=1
    printf '%s\n' "$new_stash" > "$backup_dir/stash-commit.txt"
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Tracked changes remain after stash. Stop here; backup: $backup_dir" >&2
    if [[ "$stashed" == 1 ]]; then
        git stash apply "$new_stash" || true
    fi
    exit 1
fi

switched=0
rollback() {
    echo "Update failed. Restoring previous commit $old_head" >&2
    if [[ "$switched" == 1 ]]; then
        git switch --detach "$old_head" || true
    fi
    if [[ "$stashed" == 1 ]]; then
        git stash apply "$new_stash" || true
    fi
    if [[ "$switched" == 1 ]]; then
        systemctl restart "$service" || true
    fi
    echo "Backups and previous status: $backup_dir" >&2
}
trap rollback ERR

git fetch origin "$branch"
target=$(git rev-parse FETCH_HEAD)
git switch --detach "$target"
switched=1
./.venv/bin/python -m py_compile app.py
systemctl restart "$service"

healthy=0
for attempt in $(seq 1 20); do
    if curl --fail --silent http://127.0.0.1:8080/health > /dev/null; then
        healthy=1
        break
    fi
    sleep 2
done
if [[ "$healthy" != 1 ]]; then
    echo "Service did not become healthy." >&2
    false
fi
for path in /start/performance /start/incident /start/wind /start/team; do
    curl --fail --silent --output /dev/null "http://127.0.0.1:8080$path"
done

trap - ERR
echo "Deployed commit: $target"
echo "Service: $(systemctl is-active "$service")"
echo "Backup: $backup_dir"
echo "Server-only tracked changes, if any, remain in the recorded Git stash."
