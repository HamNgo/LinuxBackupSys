"""Native widget acceptance tests; use xvfb-run on a headless Linux client."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

try:
    import tkinter as tk
except ImportError:
    tk = None

from common.core import BackupError, identifier


@unittest.skipIf(tk is None, "Tk is an optional desktop dependency")
class DesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.temp = tempfile.TemporaryDirectory(prefix="backup-desktop-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.config = self.base / "client profile.conf"
        config = {
            "CLIENT_ID": "gui-client",
            "SSH_HOST": "fixture.invalid",
            "SSH_USER": "backup",
            "SERVER_PROGRAM": "/opt/linux-backup/server/agent.py",
            "SERVER_CONFIG": "/etc/linux-backup/server.conf",
            "SSH_IDENTITY": str(self.base / "key"),
            "SSH_KNOWN_HOSTS": str(self.base / "known_hosts"),
            "BACKUP_SOURCE": str(self.base / "source"),
            "RESTORE_ROOT": str(self.base / "restore"),
            "LOG_FILE": str(self.base / "history.jsonl"),
        }
        self.config.write_text("\n".join(
            f"{key} = {json.dumps(value)}" for key, value in config.items()
        ), encoding="utf-8")
        self.older = identifier()
        self.newer = identifier()
        self.status = {
            "client_id": "gui-client", "latest": self.newer, "staging": [],
            "snapshots": [
                {"snapshot_id": key, "files": 2, "bytes": 200,
                 "completed_at": f"2026-11-{day}T02:00:00+00:00", "verification": state,
                 "publication": "complete", "transfer": "complete"}
                for day, key, state in [(15, self.older, "skipped"), (16, self.newer, "verified")]
            ],
        }
        self.restore_to = str(self.base / "restored reports")
        self.responses = {
            "status": self.status, "verify": {"verified": True, "snapshot_id": self.older,
                                             "files": 2, "source_verification": "skipped"},
            "restore": {"verified": True, "destination": self.restore_to, "snapshot_id": self.older,
                        "source_verification": "skipped", "path": "."},
            "history": {"events": []},
            "cleanup": {"decisions": [], "dry_run": True, "retention_days": 7},
        }
        self.runner = Mock(side_effect=self.run_fixture)

    def run_fixture(self, config, argv):
        self.assertEqual(Path(config), self.config)
        self.assertNotEqual(threading.get_ident(), threading.main_thread().ident)
        response = self.responses[argv[0]]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response()
        return response

    def open_app(self):
        from client.desktop import DesktopApp
        self.app = DesktopApp(self.root, str(self.config), runner=self.runner)
        self.pump_until(lambda: self.app.snapshots.exists(self.newer) and not self.app.busy)

    def pump_until(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail("Desktop operation did not complete")

    def issued(self, operation):
        return [call.args[1] for call in self.runner.call_args_list if call.args[1][0] == operation]

    def test_selected_older_snapshot_is_used_for_verify_and_restore(self):
        self.open_app()
        self.app.snapshots.selection_set(self.older)
        self.root.update()
        self.app.verify()
        self.pump_until(lambda: self.issued("verify") and not self.app.busy)
        self.assertEqual(self.issued("verify"), [["verify", self.older]])

        path = "-reports/Tiếng Việt; mùa hè.txt"
        self.app.start_restore(self.older, path, self.restore_to)
        self.pump_until(lambda: self.issued("restore") and not self.app.busy)
        self.assertEqual(self.issued("restore"), [[
            "restore", self.older, "--path=" + path, "--destination=" + self.restore_to,
        ]])

    def test_default_restore_lets_backend_allocate_fresh_destination(self):
        self.open_app()
        self.app.snapshots.selection_set(self.older)
        self.app.start_restore(self.older, ".", "")
        self.pump_until(lambda: self.issued("restore") and not self.app.busy)
        args, = self.issued("restore")
        self.assertEqual(args[:2], ["restore", self.older])
        self.assertFalse(any(arg.startswith("--destination") for arg in args))

    def test_pending_backup_blocks_double_click_and_allows_retry_after_error(self):
        self.open_app()
        entered = threading.Event()
        release = threading.Event()
        def fail_transfer():
            entered.set()
            if not release.wait(5):
                raise AssertionError("Worker did not return control to the Tk event loop")
            raise BackupError("fixture: transfer interrupted", 4)
        self.responses["backup"] = fail_transfer
        self.app.backup()
        try:
            self.pump_until(entered.is_set)
            self.assertTrue(self.app.busy)
            self.app.backup()
            self.assertEqual(len(self.issued("backup")), 1)
        finally:
            release.set()
        self.pump_until(lambda: not self.app.busy)
        self.assertIn("fixture: transfer interrupted", self.app.last_details)
        self.assertTrue(self.app.detail_button.instate(["!disabled"]))
        self.app.refresh()
        self.pump_until(lambda: len(self.issued("status")) >= 2 and not self.app.busy)
        self.assertTrue(self.app.snapshots.exists(self.older))

    def test_backup_selects_its_snapshot_and_reports_publication_if_refresh_fails(self):
        self.open_app()
        self.app.snapshots.selection_set(self.older)
        first = identifier()
        self.responses["backup"] = {"snapshot_id": first}
        self.status["snapshots"].append(dict(self.status["snapshots"][-1], snapshot_id=first))
        self.status["latest"] = first
        self.app.backup_button.invoke()
        self.pump_until(lambda: len(self.issued("status")) == 2 and not self.app.busy)
        self.assertEqual(self.app.snapshots.selection(), (first,))

        second = identifier()
        self.responses["backup"] = {"snapshot_id": second}
        self.responses["status"] = BackupError("fixture: status request disconnected", 4)
        self.app.backup_button.invoke()
        self.pump_until(lambda: len(self.issued("status")) == 3 and not self.app.busy)
        self.assertIn(second, self.app.feedback.get())
        self.assertIn("đã sao lưu", self.app.feedback.get().lower())
        self.assertIn("fixture: status request disconnected", self.app.last_details)
        self.assertTrue(self.app.detail_button.instate(["!disabled"]))

    def test_cleanup_is_preview_only_and_local_history_explicit(self):
        self.open_app()
        self.app.preview_cleanup()
        self.pump_until(lambda: self.issued("cleanup") and not self.app.busy)
        self.assertEqual(self.issued("cleanup"), [["cleanup", "--dry-run"]])
        self.app.show_history(local=True)
        self.pump_until(lambda: self.issued("history") and not self.app.busy)
        args, = self.issued("history")
        self.assertIn("--local", args)

    def test_invalid_new_profile_clears_stale_data_and_disables_actions(self):
        self.open_app()
        self.app.use_config(str(self.base / "missing.conf"))
        self.assertFalse(self.app.snapshots.get_children())
        self.assertTrue(self.app.backup_button.instate(["disabled"]))
        self.assertTrue(self.app.restore_button.instate(["disabled"]))
        self.assertTrue(self.app.open_config_button.instate(["!disabled"]))
        self.app.backup()
        self.assertFalse(self.issued("backup"))

    def test_existing_restore_destination_is_refused_without_transfer(self):
        self.open_app()
        target = self.base / "already present"
        target.mkdir()
        sentinel = target / "untouched"
        sentinel.write_bytes(b"keep")
        self.app.start_restore(self.older, ".", str(target))
        self.assertFalse(self.issued("restore"))
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertTrue(self.app.detail_button.instate(["!disabled"]))

    def test_browse_snapshot_and_choose_nested_file(self):
        from tkinter import ttk
        from client.desktop_picker import pick_snapshot_path

        self.open_app()
        folder = "-Dữ liệu cũ"
        filename = "-bản tháng 11.txt"
        self.responses["list-files"] = {"entries": [{"name": folder, "type": "dir"}]}

        def select_file(dialog):
            def descendants(parent):
                for widget in parent.winfo_children():
                    yield widget
                    yield from descendants(widget)

            widgets = list(descendants(dialog))
            tree, = [widget for widget in widgets if isinstance(widget, ttk.Treeview)]
            buttons = {widget.cget("text"): widget for widget in widgets if isinstance(widget, ttk.Button)}
            self.pump_until(lambda: not self.app.busy)
            first, = tree.get_children()
            tree.selection_set(first)
            self.root.update()
            self.responses["list-files"] = {"entries": [{"name": filename, "type": "file"}]}
            buttons["Mở thư mục"].invoke()
            self.pump_until(lambda: not self.app.busy)
            child, = tree.get_children()
            tree.selection_set(child)
            self.root.update()
            self.assertTrue(buttons["Mở thư mục"].instate(["disabled"]))
            buttons["Chọn mục này"].invoke()

        with patch.object(self.root, "wait_window", side_effect=select_file):
            selected = pick_snapshot_path(self.root, self.older, self.app._run)
        self.assertEqual(selected, f"{folder}/{filename}")
        self.assertEqual(self.issued("list-files"), [
            ["list-files", self.older, "--path=."],
            ["list-files", self.older, f"--path={folder}"],
        ])

    def test_browse_failure_can_be_cancelled_without_restore(self):
        from client.desktop_picker import pick_snapshot_path

        self.open_app()
        self.responses["list-files"] = BackupError("fixture: ssh unavailable", 4)

        def cancel(dialog):
            self.pump_until(lambda: not self.app.busy)
            dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))

        with patch.object(self.root, "wait_window", side_effect=cancel):
            selected = pick_snapshot_path(self.root, self.older, self.app._run)
        self.assertIsNone(selected)
        self.assertIn("fixture: ssh unavailable", self.app.last_details)
        self.assertFalse(self.issued("restore"))
