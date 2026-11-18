"""Server-owned storage lifecycle. Call operations while holding the usage lock."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import shutil
import stat

from common.core import (BackupError, audit, check_id, checked_path, contained,
                         identifier, read_json, sync_dir, timestamp, utcnow, write_json)
from common.manifest import scan, validate, verify


class Store:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = checked_path(cfg["STORAGE_ROOT"], exists=False)
        if len(self.root.parts) < 3:
            raise BackupError("STORAGE_ROOT must be a dedicated directory at least two levels below /", 2)
        self.client = self.root / cfg["CLIENT_ID"]
        self.snapshots = self.client / "snapshots"
        self.staging = self.client / ".staging"
        self.usage_lock = self.client / "usage.lock"
        self.writer_lock = self.client / "writer.lock"
        self.log = self.client / "history.jsonl"

    def initialize(self):
        self._parents_trusted()
        if self.client.exists():
            self.check()
            return {"initialized": True, "client_root": str(self.client), "existing": True}
        self.root.mkdir(mode=0o700, exist_ok=True)
        self._private(self.root)
        self.client.mkdir(mode=0o700)
        self.snapshots.mkdir(mode=0o700)
        self.staging.mkdir(mode=0o700)
        write_json(self.client / "owner.json", {"schema": 1, "client_id": self.cfg["CLIENT_ID"]})
        sync_dir(self.root)
        return {"initialized": True, "client_root": str(self.client), "existing": False}

    @staticmethod
    def _private(path):
        checked_path(path)
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise BackupError(f"Expected directory: {path}")
        if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise BackupError(f"Managed directory must be owned by the service user with mode 0700: {path}")

    def _parents_trusted(self):
        for parent in self.root.parents:
            info = parent.stat()
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not sticky_root):
                raise BackupError(f"Storage parent can be changed by another user: {parent}")

    def check(self):
        self._parents_trusted()
        for path in (self.root, self.client, self.snapshots, self.staging):
            self._private(path)
            if path.stat().st_dev != self.root.stat().st_dev:
                raise BackupError(f"Nested filesystems are not supported in storage: {path}")
        if read_json(self.client / "owner.json") != {"schema": 1, "client_id": self.cfg["CLIENT_ID"]}:
            raise BackupError("Storage ownership marker does not match this configuration")

    def event(self, run_id, operation, status, **fields):
        audit(self.log, run_id=run_id, client_id=self.cfg["CLIENT_ID"],
              operation=operation, status=status, **fields)

    def snapshot(self, snapshot_id):
        check_id(snapshot_id)
        path = contained(self.snapshots, self.snapshots / snapshot_id)
        if not path.is_dir():
            raise BackupError("Snapshot is not a directory")
        meta = read_json(path / "metadata.json")
        if (not isinstance(meta, dict) or meta.get("schema") != 1 or
                meta.get("snapshot_id") != snapshot_id or meta.get("client_id") != self.cfg["CLIENT_ID"] or
                meta.get("publication") != "complete" or meta.get("transfer") != "complete" or
                meta.get("verification") not in ("verified", "skipped")):
            raise BackupError(f"Snapshot lacks valid completion metadata: {snapshot_id}")
        try:
            completed = dt.datetime.fromisoformat(meta["completed_at"])
            if completed.tzinfo is None or completed.utcoffset() != dt.timedelta(0):
                raise ValueError("timestamp must be UTC")
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError(f"Invalid snapshot completion timestamp: {snapshot_id}") from exc
        contained(path, path / "payload")
        return path, meta

    def list_snapshots(self):
        result = []
        # Unexpected entries stop cleanup rather than guessing their provenance.
        for entry in sorted(self.snapshots.iterdir()):
            _, meta = self.snapshot(entry.name)
            result.append(meta)
        return sorted(result, key=lambda x: (x["completed_at"], x["snapshot_id"]))

    def begin(self, run_id, expected):
        check_id(run_id)
        if expected is not None:
            validate(expected)
        snapshot_id = identifier()
        stage = self.staging / snapshot_id
        if (self.snapshots / snapshot_id).exists():
            raise BackupError("Snapshot ID collision")
        stage.mkdir(mode=0o700)  # no exist_ok: never reuse another run's staging
        (stage / "payload").mkdir(mode=0o700)
        write_json(stage / "run.json", {
            "run_id": run_id, "snapshot_id": snapshot_id, "started_at": timestamp(),
            "client_id": self.cfg["CLIENT_ID"], "state": "transferring",
        })
        return snapshot_id

    def finish(self, snapshot_id, expected):
        stage = contained(self.staging, self.staging / check_id(snapshot_id))
        run = read_json(stage / "run.json")
        manifest = scan(stage / "payload")
        if expected is not None and manifest != validate(expected):
            raise BackupError("Transferred snapshot differs from the pre-transfer source manifest", 5)
        write_json(stage / "manifest.json", manifest)
        meta = {
            "schema": 1, "snapshot_id": snapshot_id, "client_id": self.cfg["CLIENT_ID"],
            "run_id": run["run_id"], "started_at": run["started_at"], "completed_at": timestamp(),
            "transfer": "complete", "verification": "verified" if expected is not None else "skipped",
            "publication": "complete", "files": sum(e["type"] == "file" for e in manifest["entries"].values()),
            "bytes": sum(e.get("size", 0) for e in manifest["entries"].values()),
        }
        # Flush received content before publishing. No changes to completed snapshots.
        for base, dirs, files in os.walk(stage / "payload", topdown=False):
            for name in files:
                with (Path(base) / name).open("rb") as handle:
                    os.fsync(handle.fileno())
            sync_dir(base)
        write_json(stage / "metadata.json", meta)
        destination = self.snapshots / snapshot_id
        checked_path(destination, exists=False)
        if destination.exists():
            raise BackupError("Snapshot ID collision at publication")
        os.rename(stage, destination)
        sync_dir(self.snapshots)
        sync_dir(self.staging)
        return meta

    def verify(self, snapshot_id):
        path, meta = self.snapshot(snapshot_id)
        result = verify(path / "payload", read_json(path / "manifest.json"))
        return {"snapshot_id": snapshot_id, "source_verification": meta["verification"], **result}

    def cleanup(self, *, apply=False, now=None):
        now = now or utcnow()
        snapshots = self.list_snapshots()
        newest = snapshots[-1]["snapshot_id"] if snapshots else None
        cutoff = now - dt.timedelta(days=self.cfg["RETENTION_DAYS"])
        decisions = []
        for meta in snapshots:
            snapshot_id = meta["snapshot_id"]
            expired = dt.datetime.fromisoformat(meta["completed_at"]) < cutoff
            remove = expired and snapshot_id != newest
            reason = "newest-successful" if snapshot_id == newest else "expired" if expired else "within-retention"
            decisions.append({"snapshot_id": snapshot_id, "completed_at": meta["completed_at"],
                              "path": str(self.snapshots / snapshot_id), "action": "delete" if remove else "keep",
                              "reason": reason, "deleted": False})
        # Validate every candidate before any deletion. Refuse nested mounts/symlinks.
        if apply:
            for decision in decisions:
                if decision["action"] == "delete":
                    path, _ = self.snapshot(decision["snapshot_id"])
                    self._check_deletion_tree(path)
            for decision in decisions:
                if decision["action"] != "delete":
                    continue
                self.check()
                path, _ = self.snapshot(decision["snapshot_id"])
                self._check_deletion_tree(path)
                # Read-only source directories can be removed by their owner. This
                # touches only directory modes in the snapshot being deleted.
                for base, dirs, files in os.walk(path):
                    os.chmod(base, os.stat(base).st_mode | 0o700)
                shutil.rmtree(path)
                sync_dir(self.snapshots)
                decision["deleted"] = True
                self.event(decision["snapshot_id"], "cleanup-delete", "success", snapshot_id=decision["snapshot_id"])
        return {"dry_run": not apply, "retention_days": self.cfg["RETENTION_DAYS"],
                "cutoff": cutoff.isoformat(), "decisions": decisions}

    def _check_deletion_tree(self, path):
        contained(self.snapshots, path)
        # st_dev/ismount alone miss same-filesystem bind mounts on Linux.
        # mountinfo uses octal escaping for space, tab, newline and backslash.
        import re
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            encoded = line.split()[4]
            decoded = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), encoded)
            mount = Path(decoded)
            if mount == path or mount.is_relative_to(path):
                raise BackupError(f"Refusing nested mount during cleanup: {mount}")
        if path.stat().st_uid != os.geteuid():
            raise BackupError("Refusing to delete a snapshot owned by another user")
        def failed(error):
            raise error
        for base, dirs, files in os.walk(path, followlinks=False, onerror=failed):
            for entry in [Path(base), *(Path(base) / name for name in dirs + files)]:
                checked_path(entry)
                info = entry.lstat()
                if info.st_dev != self.root.stat().st_dev or os.path.ismount(entry):
                    raise BackupError(f"Refusing nested mount during cleanup: {entry}")
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise BackupError(f"Refusing unexpected object during cleanup: {entry}")
