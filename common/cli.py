#!/usr/bin/env python3
"""Unified LinuxBackupSys CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.operations import Client
from common.core import BackupError, checked_path, history, load_config


def parser():
    cli = argparse.ArgumentParser(description="Versioned rsync/SSH backups and verified file recovery")
    cli.add_argument("--config", help="absolute TOML client config path (default: /etc/linux-backup/backup.conf)")
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("gui", help="open the desktop client")
    sub.add_parser("backup", help="back up configured source into a new snapshot")
    sub.add_parser("status", help="list completed snapshots and unfinished staging")
    restore = sub.add_parser("restore", help="restore into a NEW directory; existing destinations are refused")
    restore.add_argument("snapshot_id")
    restore.add_argument("--path", default=".", help="payload-relative file/directory (default: entire snapshot)")
    restore.add_argument("--destination", help="absolute new directory under an existing parent")
    verify = sub.add_parser("verify", help="verify stored snapshot against its original manifest")
    verify.add_argument("snapshot_id")
    browse = sub.add_parser("list-files", help="list direct children of a directory in a snapshot manifest")
    browse.add_argument("snapshot_id")
    browse.add_argument("--path", default=".", help="payload-relative directory (default: snapshot root)")
    cleanup = sub.add_parser("cleanup", help="show retention candidates; apply explicitly to delete")
    mode = cleanup.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    hist = sub.add_parser("history", help="show JSONL audit events")
    hist.add_argument("--local", action="store_true", help="read client log instead of server log")
    hist.add_argument("--limit", type=int, default=100)
    hist.add_argument("--operation", help="filter by operation name")
    configure = sub.add_parser("configure", help="write a new example or validate a config; never executes shell")
    configure.add_argument("--role", choices=("client", "server"), default="client")
    target = configure.add_mutually_exclusive_group(required=True)
    target.add_argument("--output", help="write a template to a NEW absolute path")
    target.add_argument("--check", action="store_true", help="validate --config for the selected role")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "gui":
            try:
                from client.desktop import launch
            except ModuleNotFoundError as exc:
                if exc.name not in ("tkinter", "_tkinter"):
                    raise
                raise BackupError("Giao diện cần Tk. Trên Ubuntu cài python3-tk, trên Arch cài tk.") from exc
            return launch(args.config)
        if args.config is None:
            args.config = "/etc/linux-backup/backup.conf"
        if args.command == "configure":
            if args.output:
                output = checked_path(args.output, exists=False)
                template = Path(__file__).resolve().parents[1] / args.role / (args.role + ".conf.example")
                with output.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(template.read_text(encoding="utf-8"))
                result = {"created": str(output), "next": "Edit placeholders, then run configure --check"}
            else:
                load_config(args.config, args.role)
                result = {"valid": True, "role": args.role, "config": args.config}
        else:
            cfg = load_config(args.config, "client")
            if args.command == "history" and not 1 <= args.limit <= 10000:
                raise BackupError("History limit must be in 1..10000", 2)
            if args.command == "history" and args.local:
                result = {"events": history(cfg["LOG_FILE"], args.limit, args.operation)}
            else:
                options = {}
                if args.command in ("restore", "verify", "list-files"):
                    options["snapshot_id"] = args.snapshot_id
                if args.command == "restore":
                    options.update(path=args.path, destination=args.destination)
                elif args.command == "list-files":
                    options["path"] = args.path
                elif args.command == "cleanup":
                    options["apply"] = args.apply
                elif args.command == "history":
                    options.update(limit=args.limit, filter_operation=args.operation)
                result = Client(cfg).execute(args.command, **options)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except KeyboardInterrupt:
        print("Interrupted; inspect status/history for incomplete or published runs", file=sys.stderr)
        return 130
    except (BackupError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return getattr(exc, "code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
