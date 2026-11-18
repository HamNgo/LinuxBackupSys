import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from client.transport import SSHTransport, Session
from common.core import load_config
from server.store import Store

REPO = Path(__file__).resolve().parents[1]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="linux-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "source with spaces"
        self.source.mkdir()
        self.restore = self.base / "restore"
        self.restore.mkdir()
        self.server_config = self.base / "server config 'quoted'.conf"
        self.server_config.write_text(
            'CLIENT_ID = "test-client"\nSTORAGE_ROOT = ' + json.dumps(str(self.base / "storage")) +
            '\nRETENTION_DAYS = 7\nTIMEOUT_SECONDS = 15\n', encoding="utf-8")
        self.cfg = load_config(self.server_config, "server")
        self.store = Store(self.cfg)
        self.store.initialize()
        self.client_cfg = {
            "CLIENT_ID": "test-client", "BACKUP_SOURCE": str(self.source),
            "RESTORE_ROOT": str(self.restore), "LOG_FILE": str(self.base / "client.jsonl"),
            "SSH_HOST": "fixture.invalid", "SSH_USER": "backup", "SSH_PORT": 22,
            "SSH_IDENTITY": str(self.base / "identity"), "SSH_KNOWN_HOSTS": str(self.base / "known hosts"),
            "SERVER_PROGRAM": str(REPO / "server" / "agent.py"), "SERVER_CONFIG": str(self.server_config),
            "VERIFY_CHECKSUM": True, "COMPRESSION": False, "TIMEOUT_SECONDS": 15,
        }
        Path(self.client_cfg["SSH_IDENTITY"]).touch()
        Path(self.client_cfg["SSH_KNOWN_HOSTS"]).touch()

    def data(self):
        (self.source / ".hidden").write_bytes(b"hidden version 1")
        (self.source / "empty").touch()
        (self.source / "empty dir").mkdir()
        (self.source / "sub").mkdir()
        (self.source / "sub" / "unicode tiếng Việt.txt").write_bytes(b"version one\x00\xff")
        (self.source / "submarine").mkdir()
        (self.source / "submarine" / "unrelated").write_text("keep out")
        (self.source / "-x ' ; $(touch injected)\nline.txt").write_text("literal filename")


class LocalTransport(SSHTransport):
    """Real rsync and server processes; ONLY SSH is replaced by a local shell.

    This tests remote command escaping/protocol, NOT SSH authentication/network.
    """
    def __init__(self, cfg, base):
        super().__init__(cfg)
        self.fake_ssh = base / "ssh-fixture"
        self.fake_ssh.write_text(
            '#!/usr/bin/env python3\n'
            'import os, sys\n'
            'args = sys.argv[1:]\n'
            'if args and args[0] == "-l": args = args[2:]\n'
            'args = args[1:]  # discard host/user@host\n'
            'os.execv("/bin/sh", ["sh", "-c", " ".join(args)])\n', encoding="utf-8")
        self.fake_ssh.chmod(0o700)

    def ssh(self):
        return [str(self.fake_ssh)]
