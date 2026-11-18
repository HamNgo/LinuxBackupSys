#!/usr/bin/env bash
# Explicit, conservative code installation; never creates users or starts services.
set -u
if [[ $# -ne 1 || $1 != /* || $1 == / ]]; then
    printf 'Usage: sudo bash %s /absolute/new/install-directory\n' "$0" >&2
    exit 2
fi
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 1
exec python3 - "$repo_dir" "$1" <<'PY'
import os
from pathlib import Path
import shutil
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
if ".." in target.parts or any(p.is_symlink() for p in (target, *target.parents)):
    raise SystemExit("Refusing a symlink or '..' in installation path")
if target.exists() or not target.parent.is_dir():
    raise SystemExit("Installation target must be new, with an existing parent")
if target.is_relative_to(source) or source.is_relative_to(target):
    raise SystemExit("Installation must be separate from the source checkout")
target.mkdir(mode=0o755)
target.chmod(0o755)
for name in ("common", "client", "server", "deploy"):
    shutil.copytree(source / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.conf", "*.jsonl", "*.lock"))
shutil.copy2(source / "backup-manager.sh", target / "backup-manager.sh")
for path in target.rglob("*"):
    path.chmod(0o755 if path.is_dir() or path.suffix == ".sh" else 0o644)
print(f"Installed code at {target}; configure accounts, SSH, storage and timer separately.")
PY
