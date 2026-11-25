"""Config written by the desktop editor must be usable by the existing CLI."""
import os
from pathlib import Path
import tempfile
import unittest

from client.desktop_config import _save_new, _template
from common.core import BackupError, load_config


class DesktopConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.values = _template() | {
            "BACKUP_SOURCE": str(self.root / "Tài liệu"), "RESTORE_ROOT": str(self.root / "restore"),
            "LOG_FILE": str(self.root / "history.jsonl"), "SSH_IDENTITY": str(self.root / "ssh.key"),
            "SSH_KNOWN_HOSTS": str(self.root / "known_hosts"),
            "SSH_HOST": "100.101.102.103", "CLIENT_ID": "arch-tailnet-test",
            "SERVER_CONFIG": "/etc/linux-backup/server-tailnet-test.conf",
        }

    def test_saved_copy_round_trips_and_an_existing_target_is_preserved(self):
        target = self.root / "backup.conf"
        self.assertEqual(_save_new(target, self.values), str(target))
        self.assertEqual(load_config(target, "client"), self.values)
        before = target.read_bytes()
        with self.assertRaises(BackupError):
            _save_new(target, self.values | {"VERIFY_CHECKSUM": False})
        self.assertEqual(target.read_bytes(), before)
        if os.name == "posix":
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_overlap_is_rejected_before_publishing(self):
        bad = self.values | {"LOG_FILE": str(Path(self.values["BACKUP_SOURCE"]) / "history.jsonl")}
        with self.assertRaises(BackupError):
            _save_new(self.root / "invalid.conf", bad)
        self.assertEqual(list(self.root.iterdir()), [])
