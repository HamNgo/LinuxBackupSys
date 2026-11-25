#!/usr/bin/env python3
"""SSH entrypoint and rsync wrapper. Run with the dedicated backup account."""
from __future__ import annotations

import argparse
import base64
import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.core import (BackupError, check_id, checked_path, history, load_config,
                         lock, machine_id, overlap, read_json, relative_path)
from common.manifest import subset
from common.protocol import receive, send
from server.store import Store


def session(store):
    request = receive(sys.stdin.buffer, store.cfg["TIMEOUT_SECONDS"])
    operation = request.get("operation")
    if operation not in {"backup", "restore", "verify", "list-files", "cleanup", "status", "history"}:
        raise BackupError("Unknown operation", 2)
    if request.get("client_id") != store.cfg["CLIENT_ID"]:
        raise BackupError("Client identity does not match server configuration", 2)
    run_id = check_id(request.get("run_id"))
    if operation in ("backup", "restore") and request.get("machine_id") == machine_id():
        local = checked_path(request.get("local_path", ""), exists=False)
        if overlap(local, store.root):
            raise BackupError("Source/restore destination overlaps storage on this machine", 2)
    snapshot_id = request.get("snapshot_id")
    published = False
    with contextlib.ExitStack() as stack:
        stack.enter_context(lock(store.usage_lock, exclusive=operation == "cleanup"))
        if operation == "backup":
            stack.enter_context(lock(store.writer_lock, exclusive=True))
        store.check()
        try:
            store.event(run_id, operation, "started", snapshot_id=snapshot_id)
            if operation == "backup":
                expected = request.get("manifest")
                snapshot_id = store.begin(run_id, expected)
                send(sys.stdout.buffer, {"ok": True, "snapshot_id": snapshot_id})
                finish = receive(sys.stdin.buffer, store.cfg["TIMEOUT_SECONDS"])
                if finish.get("action") != "finish" or finish.get("transfer_exit") != 0:
                    raise BackupError("Backup transfer did not complete successfully", 4)
                result = store.finish(snapshot_id, expected)
                published = True
            elif operation == "restore":
                path, meta = store.snapshot(snapshot_id)
                selection = relative_path(request.get("path", "."))
                # Verify stored baseline before allowing a transfer; never regenerate it.
                store.verify(snapshot_id)
                manifest, kind = subset(read_json(path / "manifest.json"), selection)
                send(sys.stdout.buffer, {"ok": True, "manifest": manifest, "kind": kind,
                                         "source_verification": meta["verification"]})
                finish = receive(sys.stdin.buffer, store.cfg["TIMEOUT_SECONDS"])
                if finish.get("action") != "finish" or finish.get("verified") is not True:
                    raise BackupError("Client restore transfer/verification did not complete", 5)
                result = {"snapshot_id": snapshot_id, "verified": True, "path": selection}
            elif operation == "verify":
                result = store.verify(snapshot_id)
            elif operation == "list-files":
                path, _ = store.snapshot(snapshot_id)
                selection = relative_path(request.get("path", "."))
                manifest, kind = subset(read_json(path / "manifest.json"), selection)
                if kind != "dir":
                    raise BackupError("Choose a directory in the snapshot", 2)
                children = [{"name": name, "type": entry["type"]}
                            for name, entry in manifest["entries"].items() if "/" not in name]
                children.sort(key=lambda entry: (entry["type"] != "dir", entry["name"]))
                result = {"path": selection, "entries": children}
            elif operation == "cleanup":
                if type(request.get("apply", False)) is not bool:
                    raise BackupError("apply must be boolean", 2)
                result = store.cleanup(apply=request.get("apply", False))
            elif operation == "history":
                limit = request.get("limit", 100)
                if type(limit) is not int or not 1 <= limit <= 10000:
                    raise BackupError("History limit must be in 1..10000", 2)
                result = {"events": history(store.log, limit, request.get("filter_operation"))}
            else:
                snapshots = store.list_snapshots()
                result = {"client_id": store.cfg["CLIENT_ID"], "snapshots": snapshots,
                          "latest": snapshots[-1]["snapshot_id"] if snapshots else None,
                          "staging": sorted(p.name for p in store.staging.iterdir())}
            store.event(run_id, operation, "success", snapshot_id=snapshot_id, published=published)
            send(sys.stdout.buffer, {"ok": True, "result": result})
        except (BackupError, OSError, ValueError) as exc:
            # Metadata on disk remains authoritative if history/response fails
            # after rename. Retain staging for investigation after failures.
            if operation == "backup" and snapshot_id and (store.snapshots / check_id(snapshot_id)).is_dir():
                published = True
            try:
                store.event(run_id, operation, "failed", snapshot_id=snapshot_id,
                            published=published, error=str(exc))
            except (OSError, BackupError) as log_exc:
                print(f"Audit failure: {log_exc}", file=sys.stderr)
            raise BackupError(f"{exc}; snapshot_id={snapshot_id}; published={published}",
                              getattr(exc, "code", 1)) from exc


def rsync(store, args):
    direction, snapshot_id, selection_token, *options = args
    check_id(snapshot_id)
    if direction not in ("upload", "download") or not options or options[0] != "--server":
        raise BackupError("Invalid rsync wrapper invocation", 2)
    remote = "payload" if direction == "upload" else "payload/"
    if len(options) < 3 or options[-2:] != [".", remote]:
        raise BackupError("Invalid literal remote rsync path", 2)
    if ("--sender" in options) != (direction == "download"):
        raise BackupError("Rsync direction mismatch", 2)
    # The extra lock is owned for the full data process lifetime, even when
    # the independent control SSH connection is interrupted.
    with lock(store.usage_lock):
        store.check()
        if direction == "upload":
            path = checked_path(store.staging / snapshot_id / "payload")
            if not path.is_relative_to(store.staging):
                raise BackupError("Invalid staging path")
            read_json(path.parent / "run.json")
        else:
            snapshot, _ = store.snapshot(snapshot_id)
            try:
                selection = base64.urlsafe_b64decode(selection_token.encode()).decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise BackupError("Invalid restore selection", 2) from exc
            relative_path(selection)
            _, kind = subset(read_json(snapshot / "manifest.json"), selection)
            path = checked_path(snapshot / "payload" / selection)
            if not path.is_relative_to(snapshot / "payload"):
                raise BackupError("Restore selection escaped payload", 2)
            path = str(path if kind == "dir" else path.parent) + "/"
        options[-1] = str(path)
        # An abrupt wrapper exit must not release the lock while rsync survives.
        # Pass the parent's usage-lock descriptor via a separate inherited lock.
        fd = os.open(store.usage_lock, os.O_RDONLY | os.O_NOFOLLOW)
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            proc = subprocess.run(["rsync", *options], pass_fds=(fd,), check=False)
            return proc.returncode
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("command", choices=("init", "session", "rsync"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        store = Store(load_config(args.config, "server"))
        if args.command == "init":
            send(sys.stdout.buffer, store.initialize())
        else:
            store.check()
            if args.command == "rsync":
                if len(args.args) < 6:
                    raise BackupError("Incomplete rsync arguments", 2)
                return rsync(store, args.args)
            session(store)
        return 0
    except (BackupError, OSError, ValueError) as exc:
        if args.command == "session":
            try:
                send(sys.stdout.buffer, {"ok": False, "error": str(exc), "code": getattr(exc, "code", 1)})
            except (OSError, BackupError):
                # Avoid a second BrokenPipeError during interpreter shutdown.
                fd = os.open(os.devnull, os.O_WRONLY)
                os.dup2(fd, sys.stdout.fileno())
                os.close(fd)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return getattr(exc, "code", 1)


if __name__ == "__main__":
    raise SystemExit(main())
