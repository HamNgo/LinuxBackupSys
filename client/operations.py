"""Client workflow and local verification of restored contents."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from common.core import (BackupError, audit, checked_path, identifier, machine_id, overlap,
                         relative_path, sync_dir)
from common.manifest import scan, verify
from client.transport import SSHTransport


class Client:
    def __init__(self, cfg, transport=None):
        self.cfg = cfg
        self.transport = transport or SSHTransport(cfg)

    def execute(self, operation, **options):
        run_id = identifier()
        request = {"operation": operation, "run_id": run_id, "client_id": self.cfg["CLIENT_ID"],
                   "machine_id": machine_id(), **options}
        log = self.cfg["LOG_FILE"]
        stage = None
        destination = None
        published = False
        snapshot_id = options.get("snapshot_id")
        audit(log, run_id=run_id, operation=operation, status="started", client_id=self.cfg["CLIENT_ID"])
        try:
            if operation == "backup":
                source = checked_path(self.cfg["BACKUP_SOURCE"])
                request["local_path"] = str(source)
                # Scan even with source comparison disabled: unsupported types
                # must never disappear silently because rsync skipped them.
                manifest = scan(source)
                request["manifest"] = manifest if self.cfg["VERIFY_CHECKSUM"] else None
            elif operation == "restore":
                relative_path(options.get("path", "."))
                target = options.pop("destination", None)
                request.pop("destination", None)
                if target is None:
                    target = str(Path(self.cfg["RESTORE_ROOT"]) / (str(options["snapshot_id"]) + "-" + run_id))
                destination = checked_path(target, exists=False)
                request["local_path"] = str(destination)
                source = checked_path(self.cfg["BACKUP_SOURCE"], exists=False)
                if overlap(destination, source):
                    raise BackupError("Restore destination must be separate from BACKUP_SOURCE", 2)
                if destination.exists():
                    raise BackupError("Restore destination already exists; choose a new directory", 2)
                # Existing parents must be explicit. Do not create arbitrary trees.
                parent = checked_path(destination.parent)
                if not parent.is_dir():
                    raise BackupError("Restore parent is not a directory", 2)
            with self.transport.session() as session:
                session.send(request)
                first = session.receive()
                if operation == "backup":
                    snapshot_id = first["snapshot_id"]
                    self.transport.transfer("upload", snapshot_id, source)
                    # After asking the server to commit, a lost response cannot
                    # prove that no snapshot was published.
                    published = "unknown"
                    session.send({"action": "finish", "transfer_exit": 0})
                    result = session.receive()["result"]
                    published = True
                elif operation == "restore":
                    stage = Path(tempfile.mkdtemp(prefix=".restore-" + run_id + "-", dir=parent))
                    self.transport.transfer("download", options["snapshot_id"], stage,
                                            options.get("path", "."), kind=first["kind"])
                    verify(stage, first["manifest"])
                    checked_path(destination, exists=False)
                    if destination.exists():
                        raise BackupError("Restore destination appeared during transfer; refusing overwrite", 2)
                    # Reserve destination exclusively, then move entries into it.
                    # os.rename alone could replace an existing empty directory.
                    destination.mkdir(mode=0o700)
                    published = "partial"
                    for entry in stage.iterdir():
                        os.rename(entry, destination / entry.name)
                    stage.rmdir()
                    sync_dir(destination)
                    sync_dir(destination.parent)
                    published = True
                    session.send({"action": "finish", "verified": True})
                    result = session.receive()["result"] | {"destination": str(destination),
                                                           "source_verification": first["source_verification"]}
                else:
                    result = first["result"]
            audit(log, run_id=run_id, operation=operation, status="success", client_id=self.cfg["CLIENT_ID"],
                  published=published, result=result)
            return result
        except (BackupError, OSError, ValueError, KeyError) as exc:
            details = {"error": str(exc), "published": published,
                       "snapshot_id": snapshot_id,
                       "restore_staging": str(stage) if stage else None,
                       "destination": str(destination) if destination else None}
            try:
                audit(log, run_id=run_id, operation=operation, status="failed",
                      client_id=self.cfg["CLIENT_ID"], **details)
            except (BackupError, OSError) as log_exc:
                raise BackupError(f"{exc}; also failed to write history: {log_exc}; {details}", 1) from exc
            raise BackupError(f"{exc}; snapshot_id={snapshot_id}; published={published}" + (f"; restore_staging={stage}; destination={destination}" if stage else ""),
                              getattr(exc, "code", 1)) from exc
