#!/usr/bin/env bash
set -u
if [[ $# -ne 1 ]]; then
    printf 'Usage: %s /absolute/path/backup.conf\n' "$0" >&2
    exit 2
fi
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
bash "$script_dir/../backup-manager.sh" --config "$1" backup
backup_status=$?
if [[ $backup_status -ne 0 ]]; then
    exit "$backup_status"
fi
exec bash "$script_dir/../backup-manager.sh" --config "$1" cleanup --apply
