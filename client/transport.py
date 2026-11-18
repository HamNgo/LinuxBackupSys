"""Strict SSH transport; no shell on the client, quoted server command arguments."""
from __future__ import annotations

import base64
import contextlib
from pathlib import Path
import shlex
import subprocess
import sys

from common.core import BackupError, checked_path
from common.protocol import receive, send


class Session:
    def __init__(self, process, timeout):
        self.process = process
        self.timeout = timeout

    def send(self, value):
        send(self.process.stdin, value)

    def receive(self):
        result = receive(self.process.stdout, self.timeout)
        if result.get("ok") is not True:
            raise BackupError(result.get("error", "Server returned an invalid response"), result.get("code", 1))
        return result


class SSHTransport:
    def __init__(self, cfg):
        self.cfg = cfg
        for key in ("SSH_IDENTITY", "SSH_KNOWN_HOSTS"):
            if not checked_path(cfg[key]).is_file():
                raise BackupError(f"{key} must be a regular file", 2)
        self.target = f'{cfg["SSH_USER"]}@{cfg["SSH_HOST"]}'

    def ssh(self):
        # Disable ambient SSH config: user-authored config can run LocalCommand,
        # ProxyCommand, or change destination and known-hosts handling.
        return ["ssh", "-F", "/dev/null", "-T", "-p", str(self.cfg["SSH_PORT"]),
                "-i", self.cfg["SSH_IDENTITY"], "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
                "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                "-o", "UserKnownHostsFile=" + shlex.quote(self.cfg["SSH_KNOWN_HOSTS"])]

    def agent(self):
        return ["python3", self.cfg["SERVER_PROGRAM"], "--config", self.cfg["SERVER_CONFIG"]]

    @contextlib.contextmanager
    def session(self):
        command = [*self.ssh(), self.target, shlex.join([*self.agent(), "session"])]
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=sys.stderr, bufsize=0) as process:
            try:
                yield Session(process, self.cfg["TIMEOUT_SECONDS"])
                process.stdin.close()
                try:
                    status = process.wait(timeout=10)
                except subprocess.TimeoutExpired as exc:
                    raise BackupError("SSH control process did not exit", 4) from exc
                if status:
                    raise BackupError(f"SSH control process failed (exit {status})", 4)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def transfer(self, direction, snapshot_id, local, selection=".", kind="dir"):
        token = base64.urlsafe_b64encode(selection.encode("utf-8")).decode("ascii")
        wrapper = shlex.join([*self.agent(), "rsync", direction, snapshot_id, token])
        command = ["rsync", "-rpt", "--no-links", "--no-devices", "--no-specials",
                   "--timeout=" + str(self.cfg["TIMEOUT_SECONDS"]),
                   "--rsync-path=" + wrapper, "-e", shlex.join(self.ssh())]
        if self.cfg["COMPRESSION"]:
            command.append("-z")
        remote = self.target + (":payload" if direction == "upload" else ":payload/")
        # Directory-shaped requests preserve rsync's file-list safety checks.
        # For one file, send its literal basename through a NUL-delimited list,
        # never through the remote shell or as a glob.
        file_list = None
        if direction == "download" and kind == "file":
            command.extend(["--from0", "--files-from=-"])
            file_list = Path(selection).name.encode("utf-8", errors="surrogateescape") + b"\0"
        local = Path(local)
        if direction == "upload":
            operands = [str(local) + ("/" if local.is_dir() else ""), remote]
        else:
            operands = [remote, str(local) + "/"]
        try:
            result = subprocess.run([*command, "--", *operands], input=file_list,
                                    stdin=subprocess.DEVNULL if file_list is None else None,
                                    stdout=sys.stderr, stderr=sys.stderr,
                                    timeout=self.cfg["TIMEOUT_SECONDS"], check=False)
        except subprocess.TimeoutExpired as exc:
            raise BackupError("Rsync transfer timed out; staging was not published", 4) from exc
        if result.returncode:
            raise BackupError(f"Rsync transfer failed (exit {result.returncode})", 4)
