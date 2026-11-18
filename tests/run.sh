#!/usr/bin/env bash
set -u
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 1
cd -- "$repo_dir" || exit 1
scripts=(backup-manager.sh client/scheduled-backup.sh tests/run.sh deploy/install-code.sh)
for script in "${scripts[@]}"; do
    bash -n "$script" || exit 1
done
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck "${scripts[@]}" || exit 1
else
    printf 'SKIP: ShellCheck is not installed.\n' >&2
fi
exec python3 -m unittest discover -s tests -v
