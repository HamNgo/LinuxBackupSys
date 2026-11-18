import datetime as dt
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from common.core import (BackupError, check_id, checked_path, identifier, load_config,
                         read_json, relative_path, utcnow, write_json)
from common.manifest import scan, subset, validate, verify
from tests.support import Fixture


class ManifestTests(Fixture):
    def test_special_names_empty_files_and_subtree(self):
        self.data()
        manifest = scan(self.source)
        self.assertTrue(verify(self.source, manifest)["verified"])
        selected, kind = subset(manifest, "sub")
        self.assertEqual(kind, "dir")
        self.assertEqual(set(selected["entries"]), {"unicode tiếng Việt.txt"})
        selected, kind = subset(manifest, "sub/unicode tiếng Việt.txt")
        self.assertEqual(kind, "file")
        self.assertEqual(selected["entries"]["unicode tiếng Việt.txt"]["size"], 13)

    def test_changed_missing_and_extra(self):
        path = self.source / "file"
        path.write_bytes(b"one")
        manifest = scan(self.source)
        path.write_bytes(b"two")
        with self.assertRaisesRegex(BackupError, "mismatch"):
            verify(self.source, manifest)
        path.unlink()
        with self.assertRaisesRegex(BackupError, "missing"):
            verify(self.source, manifest)
        path.write_bytes(b"one")
        (self.source / "extra").touch()
        with self.assertRaisesRegex(BackupError, "extra"):
            verify(self.source, manifest)

    def test_symlink_and_fifo_rejected(self):
        if os.name != "posix":
            self.skipTest("Linux object types")
        (self.source / "link").symlink_to(self.base)
        with self.assertRaises(BackupError):
            scan(self.source)
        (self.source / "link").unlink()
        os.mkfifo(self.source / "pipe")
        with self.assertRaises(BackupError):
            scan(self.source)

    def test_invalid_manifest_paths_types_and_duplicate_json(self):
        for key in ("../outside", "/outside", "a//b", ".", "a/./b"):
            with self.subTest(key=key), self.assertRaises(BackupError):
                validate({"schema": 1, "algorithm": "sha256", "entries": {key: {"type": "dir", "mode": 0o700}}})
        path = self.base / "duplicate.json"
        path.write_text('{"entries": {}, "entries": {}}')
        with self.assertRaises(BackupError):
            read_json(path)
        with self.assertRaises(BackupError):
            validate({"schema": 1, "algorithm": "sha256", "entries": {"no-parent/file": {"type": "dir", "mode": 0o700}}})

    def test_empty_source_is_valid_missing_is_error(self):
        self.assertEqual(scan(self.source)["entries"], {})
        with self.assertRaises(BackupError):
            scan(self.source / "missing")

    def test_permission_change_detected(self):
        if os.name != "posix":
            self.skipTest("Linux permissions")
        path = self.source / "file"
        path.write_text("data")
        path.chmod(0o600)
        manifest = scan(self.source)
        path.chmod(0o640)
        with self.assertRaises(BackupError):
            verify(self.source, manifest)


class ConfigTests(Fixture):
    def client_file(self, **changes):
        cfg = self.client_cfg | changes
        path = self.base / "client.conf"
        path.write_text("\n".join(key + " = " + json.dumps(value) for key, value in cfg.items()), encoding="utf-8")
        return path

    def test_valid_config_and_literal_shell_content(self):
        value = str(self.base / "data $(touch sentinel); 'literal'")
        cfg = load_config(self.client_file(BACKUP_SOURCE=value), "client")
        self.assertEqual(cfg["BACKUP_SOURCE"], value)
        self.assertFalse((self.base / "sentinel").exists())

    def test_invalid_typed_values_and_unknown_keys(self):
        for changes in ({"SSH_PORT": True}, {"SSH_PORT": 0}, {"VERIFY_CHECKSUM": "true"},
                        {"TIMEOUT_SECONDS": -1}, {"SSH_HOST": "-oProxyCommand=evil"},
                        {"BACKUP_SOURCE": ""}, {"BACKUP_SOURCE": "/tmp/../etc"}, {"EXTRA": 1}):
            with self.subTest(changes=changes), self.assertRaises(BackupError):
                load_config(self.client_file(**changes), "client")

    def test_retention_zero_negative_wrong_type_rejected(self):
        for value in (0, -1, "7", True):
            self.server_config.write_text('CLIENT_ID="test-client"\nSTORAGE_ROOT=' + json.dumps(str(self.base / "storage")) +
                                          '\nRETENTION_DAYS=' + json.dumps(value))
            with self.assertRaises(BackupError):
                load_config(self.server_config, "server")

    def test_source_log_overlap_rejected(self):
        with self.assertRaises(BackupError):
            load_config(self.client_file(LOG_FILE=str(self.source / "history.jsonl")), "client")

    def test_ids_and_relative_paths(self):
        self.assertEqual(check_id(identifier())[:1], "2")
        for value in ("../x", "x/y", "", None, "20260101T000000Z"):
            with self.assertRaises(BackupError):
                check_id(value)
        with self.assertRaises(BackupError):
            relative_path("../file")

    def test_symlink_parent_rejected(self):
        if os.name != "posix":
            self.skipTest("Linux symlinks")
        link = self.base / "link"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(BackupError):
            checked_path(link / "new", exists=False)

    def test_group_writable_config_rejected(self):
        if os.name != "posix":
            self.skipTest("Linux permissions")
        path = self.client_file()
        path.chmod(0o666)
        with self.assertRaises(BackupError):
            load_config(path, "client")


@unittest.skipUnless(os.name == "posix", "Server filesystem tests require Linux")
class StoreTests(Fixture):
    def completed(self, *, age=0):
        snapshot_id = self.store.begin(identifier(), None)
        (self.store.staging / snapshot_id / "payload" / "file").write_bytes(b"snapshot")
        meta = self.store.finish(snapshot_id, None)
        meta["completed_at"] = (self.now - dt.timedelta(days=age)).isoformat()
        write_json(self.store.snapshots / snapshot_id / "metadata.json", meta)
        return snapshot_id

    def setUp(self):
        super().setUp()
        self.now = utcnow()

    def test_retention_boundary_latest_and_dry_run_apply(self):
        old = self.completed(age=8)
        boundary = self.completed(age=7)
        new = self.completed(age=0)
        stage = self.store.begin(identifier(), None)
        plan = self.store.cleanup(now=self.now)
        self.assertTrue((self.store.snapshots / old).exists())
        actions = {d["snapshot_id"]: d["action"] for d in plan["decisions"]}
        self.assertEqual(actions, {old: "delete", boundary: "keep", new: "keep"})
        applied = self.store.cleanup(apply=True, now=self.now)
        self.assertEqual([d["snapshot_id"] for d in applied["decisions"] if d["deleted"]], [old])
        self.assertTrue((self.store.staging / stage).exists())
        self.assertTrue(self.store.verify(boundary)["verified"])
        self.assertTrue(self.store.verify(new)["verified"])

    def test_empty_and_only_old_snapshot(self):
        self.assertEqual(self.store.cleanup(apply=True)["decisions"], [])
        only = self.completed(age=100)
        self.store.cleanup(apply=True, now=self.now)
        self.assertTrue(self.store.verify(only)["verified"])

    def test_unknown_and_symlink_entries_preserve_sentinel(self):
        old = self.completed(age=8)
        self.completed()
        sentinel = self.base / "sentinel"
        sentinel.write_text("untouched")
        link = self.store.snapshots / identifier()
        link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(BackupError):
            self.store.cleanup(apply=True, now=self.now)
        self.assertEqual(sentinel.read_text(), "untouched")
        self.assertTrue((self.store.snapshots / old).exists())
        link.unlink()
        (self.store.snapshots / "unknown").mkdir()
        with self.assertRaises(BackupError):
            self.store.cleanup(apply=True, now=self.now)

    def test_mismatch_does_not_publish(self):
        (self.source / "file").write_text("expected")
        manifest = scan(self.source)
        snapshot_id = self.store.begin(identifier(), manifest)
        (self.store.staging / snapshot_id / "payload" / "file").write_text("wrong")
        with self.assertRaises(BackupError):
            self.store.finish(snapshot_id, manifest)
        self.assertEqual(self.store.list_snapshots(), [])
        self.assertTrue((self.store.staging / snapshot_id).is_dir())

    def test_snapshot_id_collision_does_not_overwrite(self):
        snapshot_id = self.store.begin(identifier(), None)
        with mock.patch("server.store.identifier", return_value=snapshot_id):
            with self.assertRaises(FileExistsError):
                self.store.begin(identifier(), None)
        self.assertTrue((self.store.staging / snapshot_id / "run.json").exists())

    def test_metadata_failure_before_publication(self):
        snapshot_id = self.store.begin(identifier(), None)
        with mock.patch("server.store.write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.finish(snapshot_id, None)
        self.assertEqual(self.store.list_snapshots(), [])

    def test_permission_error_during_deletion_is_failure(self):
        old = self.completed(age=8)
        new = self.completed()
        with mock.patch("server.store.shutil.rmtree", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.store.cleanup(apply=True, now=self.now)
        self.assertTrue((self.store.snapshots / old).exists())
        self.assertTrue(self.store.verify(new)["verified"])

    def test_nested_mount_detection_before_deletion(self):
        old = self.completed(age=8)
        self.completed()
        with mock.patch("server.store.os.path.ismount", return_value=True):
            with self.assertRaises(BackupError):
                self.store.cleanup(apply=True, now=self.now)
        self.assertTrue((self.store.snapshots / old).exists())

    def test_corrupt_metadata_rejected(self):
        snapshot_id = self.completed()
        path = self.store.snapshots / snapshot_id / "metadata.json"
        meta = read_json(path)
        meta["client_id"] = "impostor"
        write_json(path, meta)
        with self.assertRaises(BackupError):
            self.store.verify(snapshot_id)
