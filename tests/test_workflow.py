import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

from client.operations import Client
from common.core import BackupError, history, identifier, lock, read_json, write_json
from common.manifest import scan, verify
from tests.support import Fixture, LocalTransport, REPO


@unittest.skipUnless(os.name == "posix" and shutil.which("rsync"), "Linux and rsync required")
class WorkflowTests(Fixture):
    def test_browse_only_direct_children_of_selected_snapshot(self):
        self.data()
        sid = self.client.execute("backup")["snapshot_id"]
        (self.source / "sub" / "unicode tiếng Việt.txt").unlink()
        listing = self.client.execute("list-files", snapshot_id=sid, path="sub")
        self.assertEqual(listing, {"path": "sub", "entries": [{"name": "unicode tiếng Việt.txt", "type": "file"}]})
        root = self.client.execute("list-files", snapshot_id=sid)
        self.assertEqual([row["name"] for row in root["entries"][:3]], ["empty dir", "sub", "submarine"])
        self.assertEqual(self.client.execute("list-files", snapshot_id=sid, path="empty dir")["entries"], [])
        for invalid in ("../outside", ".hidden", "missing"):
            with self.subTest(invalid=invalid), self.assertRaises(BackupError):
                self.client.execute("list-files", snapshot_id=sid, path=invalid)

    def setUp(self):
        super().setUp()
        self.transport = LocalTransport(self.client_cfg, self.base)
        self.client = Client(self.client_cfg, self.transport)

    def test_versions_old_file_directory_and_whole_restore(self):
        self.data()
        expected = scan(self.source)
        first = self.client.execute("backup")
        self.assertEqual(first["verification"], "verified")
        old_file = self.source / "sub" / "unicode tiếng Việt.txt"
        old_file.write_bytes(b"new version")
        (self.source / ".hidden").unlink()
        second = self.client.execute("backup")
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        verify(self.store.snapshots / first["snapshot_id"] / "payload", expected)
        current = scan(self.source)
        whole = self.client.execute("restore", snapshot_id=first["snapshot_id"], path=".")
        verify(Path(whole["destination"]), expected)
        selected = self.client.execute("restore", snapshot_id=first["snapshot_id"], path="sub")
        self.assertEqual({p.name for p in Path(selected["destination"]).iterdir()}, {"unicode tiếng Việt.txt"})
        file_result = self.client.execute("restore", snapshot_id=first["snapshot_id"], path="sub/unicode tiếng Việt.txt")
        self.assertEqual((Path(file_result["destination"]) / "unicode tiếng Việt.txt").read_bytes(), b"version one\x00\xff")
        verify(self.source, current)
        status = self.client.execute("status")
        self.assertEqual(len(status["snapshots"]), 2)
        self.assertEqual(status["latest"], second["snapshot_id"])
        self.assertTrue(self.client.execute("verify", snapshot_id=first["snapshot_id"])["verified"])
        self.assertTrue(self.client.execute("history")["events"])

    def test_single_file_source(self):
        path = self.source / "a 'quoted' file"
        path.write_bytes(b"single")
        self.client_cfg["BACKUP_SOURCE"] = str(path)
        result = self.client.execute("backup")
        restored = self.client.execute("restore", snapshot_id=result["snapshot_id"])
        self.assertEqual((Path(restored["destination"]) / path.name).read_bytes(), b"single")

    def test_valid_empty_source(self):
        result = self.client.execute("backup")
        self.assertEqual(result["files"], 0)
        restored = self.client.execute("restore", snapshot_id=result["snapshot_id"])
        self.assertEqual(list(Path(restored["destination"]).iterdir()), [])

    def test_transfer_failure_preserves_previous_snapshot(self):
        (self.source / "keep").write_text("old")
        first = self.client.execute("backup")
        with mock.patch.object(self.transport, "transfer", side_effect=BackupError("rsync exit 23", 4)):
            with self.assertRaises(BackupError):
                self.client.execute("backup")
        self.assertEqual(len(self.store.list_snapshots()), 1)
        self.assertEqual(len(list(self.store.staging.iterdir())), 1)
        self.assertTrue(self.store.verify(first["snapshot_id"])["verified"])

    def test_modified_source_during_transfer_is_not_published(self):
        path = self.source / "file"
        path.write_text("before")
        transfer = self.transport.transfer
        def mutate(*args, **kwargs):
            path.write_text("after!")
            return transfer(*args, **kwargs)
        with mock.patch.object(self.transport, "transfer", side_effect=mutate):
            with self.assertRaisesRegex(BackupError, "differs"):
                self.client.execute("backup")
        self.assertEqual(self.store.list_snapshots(), [])

    def test_checksum_disabled_is_never_reported_as_source_verified(self):
        (self.source / "file").write_text("data")
        self.client_cfg["VERIFY_CHECKSUM"] = False
        result = self.client.execute("backup")
        self.assertEqual(result["verification"], "skipped")
        verified = self.client.execute("verify", snapshot_id=result["snapshot_id"])
        self.assertEqual(verified["source_verification"], "skipped")
        self.assertTrue(verified["verified"])

    def test_corruption_blocks_verify_and_restore(self):
        (self.source / "file").write_text("original")
        snapshot = self.client.execute("backup")["snapshot_id"]
        (self.store.snapshots / snapshot / "payload" / "file").write_text("tampered")
        for operation in ("verify", "restore"):
            with self.subTest(operation=operation), self.assertRaises(BackupError):
                self.client.execute(operation, snapshot_id=snapshot)

    def test_restore_transfer_corruption_and_failure_preserve_source(self):
        (self.source / "file").write_text("original")
        snapshot = self.client.execute("backup")["snapshot_id"]
        transfer = self.transport.transfer
        target = self.restore / "target"
        def corrupt(direction, snapshot_id, local, selection, **kwargs):
            transfer(direction, snapshot_id, local, selection, **kwargs)
            (local / "file").write_text("corrupt")
        with mock.patch.object(self.transport, "transfer", side_effect=corrupt):
            with self.assertRaises(BackupError):
                self.client.execute("restore", snapshot_id=snapshot, destination=str(target))
        self.assertFalse(target.exists())
        self.assertEqual((self.source / "file").read_text(), "original")
        self.assertTrue(self.store.verify(snapshot)["verified"])

    def test_restore_collision_escape_and_symlink_rejected(self):
        (self.source / "file").write_text("original")
        snapshot = self.client.execute("backup")["snapshot_id"]
        (self.restore / "link").symlink_to(self.source, target_is_directory=True)
        for target in (self.source, self.source / "child", self.base, self.restore / "link" / "child", self.restore):
            with self.subTest(target=target), self.assertRaises(BackupError):
                self.client.execute("restore", snapshot_id=snapshot, destination=str(target))
        with self.assertRaises(BackupError):
            self.client.execute("restore", snapshot_id=snapshot, path="../outside")
        self.assertEqual((self.source / "file").read_text(), "original")

    def test_locks_block_cleanup_and_overlapping_backups(self):
        with lock(self.store.usage_lock):
            with self.assertRaises(BackupError) as caught:
                self.client.execute("cleanup", apply=True)
            self.assertEqual(caught.exception.code, 3)
        with lock(self.store.writer_lock, exclusive=True):
            with self.assertRaises(BackupError) as caught:
                self.client.execute("backup")
            self.assertEqual(caught.exception.code, 3)
        with lock(self.store.usage_lock, exclusive=True):
            with self.assertRaises(BackupError):
                self.client.execute("backup")

    def test_post_publication_client_log_failure_preserves_snapshot(self):
        from common.core import audit
        calls = 0
        def broken_log(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OSError("disk full")
            return audit(*args, **kwargs)
        with mock.patch("client.operations.audit", side_effect=broken_log):
            with self.assertRaisesRegex(BackupError, "published.*True"):
                self.client.execute("backup")
        snapshots = self.store.list_snapshots()
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(self.store.verify(snapshots[0]["snapshot_id"])["verified"])

    def test_same_host_storage_overlap_is_refused(self):
        self.client_cfg["BACKUP_SOURCE"] = str(self.store.root)
        with self.assertRaisesRegex(BackupError, "overlaps storage"):
            self.client.execute("backup")
        self.client_cfg["BACKUP_SOURCE"] = str(self.source)
        snapshot = self.client.execute("backup")["snapshot_id"]
        with self.assertRaisesRegex(BackupError, "overlaps storage"):
            self.client.execute("restore", snapshot_id=snapshot, destination=str(self.store.root / "restore"))
        self.assertFalse(list(self.store.root.glob(".restore-*")))

    def test_lost_publication_response_is_reported_as_unknown(self):
        from client.transport import Session
        original = Session.receive
        calls = 0
        def disconnect(session):
            nonlocal calls
            calls += 1
            response = original(session)
            if calls == 2:
                raise BackupError("simulated lost commit response", 4)
            return response
        with mock.patch.object(Session, "receive", disconnect):
            with self.assertRaisesRegex(BackupError, "published=unknown"):
                self.client.execute("backup")
        self.assertEqual(len(self.store.list_snapshots()), 1)
        event = history(self.client_cfg["LOG_FILE"])[-1]
        self.assertEqual(event["published"], "unknown")
        self.assertEqual(event["snapshot_id"], self.store.list_snapshots()[0]["snapshot_id"])

    def test_data_process_keeps_lock_after_control_wrapper_is_killed(self):
        snapshot = self.store.begin(identifier(), None)
        cmd = [sys.executable, str(REPO / "server/agent.py"), "--config", str(self.server_config),
               "rsync", "upload", snapshot, "Lg==", "--server", "-rpt", ".", "payload"]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child = None
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                children = Path(f"/proc/{process.pid}/task/{process.pid}/children").read_text().split()
                if children:
                    child = int(children[0])
                    break
                time.sleep(0.02)
            self.assertIsNotNone(child)
            # Give rsync time to exec and initialize, rather than testing only
            # the inherited descriptor of a child that has not exec'd yet.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and Path(f"/proc/{child}/comm").read_text().strip() != "rsync":
                time.sleep(0.02)
            process.kill()
            process.wait(timeout=5)
            with self.assertRaises(BackupError):
                with lock(self.store.usage_lock, exclusive=True):
                    pass
        finally:
            if child:
                try:
                    os.kill(child, 15)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_special_filename_restore_is_literal(self):
        name = "-a * [? ' ; $(touch sentinel)\nTiếng Việt"
        (self.source / name).write_text("literal")
        snapshot = self.client.execute("backup")["snapshot_id"]
        result = self.client.execute("restore", snapshot_id=snapshot, path=name)
        self.assertEqual((Path(result["destination"]) / name).read_text(), "literal")
        self.assertEqual(len(list(Path(result["destination"]).iterdir())), 1)

    def test_cli_help_configure_and_validation(self):
        new = self.base / "generated.conf"
        cmd = ["bash", str(REPO / "backup-manager.sh")]
        help_result = subprocess.run([*cmd, "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0)
        first = subprocess.run([*cmd, "configure", "--output", str(new)], capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run([*cmd, "configure", "--output", str(new)], capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        checked = subprocess.run([*cmd, "--config", str(self.server_config), "configure", "--role", "server", "--check"], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
