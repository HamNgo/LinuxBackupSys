import io
import json
import os
import shutil
import subprocess
import unittest
from unittest import mock

from client.transport import SSHTransport
from common.core import BackupError
from common.protocol import receive, send
from tests.support import Fixture


class ShortWriter(io.BytesIO):
    def write(self, data):
        return super().write(data[:3])


class ProtocolTests(unittest.TestCase):
    def test_partial_writes_do_not_truncate_manifest(self):
        writer = ShortWriter()
        message = {"text": "Unicode tiếng Việt\n" * 100}
        send(writer, message)
        self.assertEqual(json.loads(writer.getvalue()), message)

    def test_message_size_is_bounded(self):
        with mock.patch("common.protocol.MAX_MESSAGE", 10), self.assertRaises(BackupError):
            send(io.BytesIO(), {"text": "too big"})

    @unittest.skipUnless(os.name == "posix", "POSIX pipe/select")
    def test_malformed_duplicate_eof_and_partial_timeout(self):
        for data in (b'{"a":1,"a":2}\n', b'[]\n', b'bad\n', b'', b'{"partial":'):
            with self.subTest(data=data):
                reader, writer = os.pipe()
                with os.fdopen(reader, "rb", buffering=0) as stream:
                    try:
                        os.write(writer, data)
                        if data == b'':
                            os.close(writer)
                            writer = None
                        with self.assertRaises(BackupError):
                            receive(stream, 0.05)
                    finally:
                        if writer is not None:
                            os.close(writer)


@unittest.skipUnless(os.name == "posix" and shutil.which("ssh"), "OpenSSH config parser required")
class SSHArgumentsTests(Fixture):
    def test_known_hosts_path_with_spaces_is_one_ssh_config_argument(self):
        transport = SSHTransport(self.client_cfg)
        result = subprocess.run([*transport.ssh(), "-G", transport.target], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        hosts = next(line for line in result.stdout.splitlines() if line.startswith("userknownhostsfile "))
        self.assertIn(self.client_cfg["SSH_KNOWN_HOSTS"], hosts)
        self.assertIn("stricthostkeychecking true", result.stdout)
        self.assertIn("batchmode yes", result.stdout)
