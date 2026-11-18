"""Configuration, safe paths, durable JSON, locks and audit records."""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import tomllib
import uuid


class BackupError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def timestamp():
    return utcnow().isoformat()


def machine_id():
    # A boot ID distinguishes two machines even when their filesystem layouts
    # are identical. Used only to detect source/restore overlap on the SAME host.
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def identifier():
    return utcnow().strftime("%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex[:12]


def check_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}T\d{12}Z-[0-9a-f]{12}", value):
        raise BackupError("Invalid snapshot/run ID", 2)
    return value


def relative_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BackupError("Invalid relative path", 2)
    if value == ".":
        return value
    path = PurePosixPath(value)
    if path.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise BackupError("Path must be relative, without empty, '.' or '..' components", 2)
    return value


def checked_path(value, *, exists=True):
    """Reject symlinks in every existing component; never use string prefixes."""
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise BackupError(f"Expected an absolute path without '..': {path}", 2)
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise BackupError(f"Symlink paths are not supported: {part}", 2)
    if exists and not path.exists():
        raise BackupError(f"Path does not exist: {path}", 2)
    if path.resolve(strict=exists) != path:
        raise BackupError(f"Path must be canonical: {path}", 2)
    return path


def contained(root, path):
    root = checked_path(root)
    path = checked_path(path)
    if not path.is_relative_to(root) or path == root:
        raise BackupError(f"Path escapes managed root: {path}", 2)
    return path


def overlap(a, b):
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


CLIENT_DEFAULTS = {
    "SSH_PORT": 22, "VERIFY_CHECKSUM": True, "COMPRESSION": False,
    "TIMEOUT_SECONDS": 300,
}
CLIENT_REQUIRED = {
    "CLIENT_ID", "BACKUP_SOURCE", "SSH_HOST", "SSH_USER", "SSH_IDENTITY",
    "SSH_KNOWN_HOSTS", "SERVER_PROGRAM", "SERVER_CONFIG", "LOG_FILE", "RESTORE_ROOT",
}
SERVER_DEFAULTS = {"RETENTION_DAYS": 7, "TIMEOUT_SECONDS": 300}
SERVER_REQUIRED = {"CLIENT_ID", "STORAGE_ROOT"}


def load_config(filename, role):
    path = checked_path(filename)
    if not path.is_file():
        raise BackupError("Configuration must be a regular file", 2)
    if os.name == "posix" and (path.stat().st_mode & 0o022 or path.stat().st_uid not in (0, os.geteuid())):
        raise BackupError("Configuration must be owned by root/service user and not writable by group/others", 2)
    try:
        with path.open("rb") as handle:
            values = tomllib.load(handle)
    except (ValueError, OSError) as exc:
        raise BackupError(f"Cannot parse configuration: {exc}", 2) from exc
    defaults, required = ((CLIENT_DEFAULTS, CLIENT_REQUIRED) if role == "client"
                          else (SERVER_DEFAULTS, SERVER_REQUIRED))
    unknown = values.keys() - (defaults.keys() | required)
    missing = required - values.keys()
    if unknown or missing:
        raise BackupError(f"Config keys: missing={sorted(missing)}, unknown={sorted(unknown)}", 2)
    cfg = defaults | values
    if not isinstance(cfg["CLIENT_ID"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", cfg["CLIENT_ID"]):
        raise BackupError("CLIENT_ID must contain 1-64 letters, digits, '_' or '-'", 2)
    for key, value in cfg.items():
        if key in ("VERIFY_CHECKSUM", "COMPRESSION"):
            if type(value) is not bool:
                raise BackupError(f"{key} must be a TOML boolean", 2)
        elif key in ("SSH_PORT", "RETENTION_DAYS", "TIMEOUT_SECONDS"):
            limit = {"SSH_PORT": 65535, "RETENTION_DAYS": 36500, "TIMEOUT_SECONDS": 86400}[key]
            if type(value) is not int or not 1 <= value <= limit:
                raise BackupError(f"{key} must be an integer in 1..{limit}", 2)
        elif not isinstance(value, str) or not value or "\x00" in value or "\n" in value or "\r" in value:
            raise BackupError(f"{key} must be a nonempty, single-line string", 2)
    if role == "client":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cfg["SSH_HOST"]):
            raise BackupError("SSH_HOST must be an IPv4 address or DNS name", 2)
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", cfg["SSH_USER"]):
            raise BackupError("Invalid SSH_USER", 2)
        for key in ("SERVER_PROGRAM", "SERVER_CONFIG"):
            value = PurePosixPath(cfg[key])
            if not value.is_absolute() or ".." in value.parts:
                raise BackupError(f"{key} must be an absolute server path", 2)
        local_keys = ("BACKUP_SOURCE", "SSH_IDENTITY", "SSH_KNOWN_HOSTS", "LOG_FILE", "RESTORE_ROOT")
    else:
        local_keys = ("STORAGE_ROOT",)
    for key in local_keys:
        checked_path(cfg[key], exists=False)
    if role == "client":
        source = Path(cfg["BACKUP_SOURCE"])
        for key in ("LOG_FILE", "RESTORE_ROOT", "SSH_IDENTITY", "SSH_KNOWN_HOSTS"):
            if overlap(source, Path(cfg[key])):
                raise BackupError(f"BACKUP_SOURCE must be separate from {key}", 2)
    return cfg


def sync_dir(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path, value):
    path = Path(path)
    checked_path(path, exists=False)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=True, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    from common.protocol import no_duplicates
    path = checked_path(path)
    if not path.is_file():
        raise BackupError(f"Expected a regular JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError) as exc:
        raise BackupError(f"Invalid JSON: {path}") from exc


@contextlib.contextmanager
def lock(path, *, exclusive=False, blocking=False):
    if os.name != "posix":
        raise BackupError("Runtime locks require Linux; run using Ubuntu/WSL")
    import fcntl
    checked_path(path, exists=False)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, flags | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise BackupError("Another operation holds the server lock; retry later", 3) from exc
        yield
    finally:
        os.close(fd)


def audit(path, **fields):
    """A failed audit write is an operation failure, including after publication."""
    path = checked_path(path, exists=False)
    if not path.parent.is_dir():
        raise BackupError(f"Log directory must exist: {path.parent}")
    record = {"time": timestamp(), **fields}
    with lock(path.with_name(path.name + ".lock"), exclusive=True, blocking=True):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def history(path, limit=100, operation=None):
    from common.protocol import no_duplicates
    import collections
    path = checked_path(path, exists=False)
    if not path.exists():
        return []
    result = collections.deque(maxlen=limit)
    with lock(path.with_name(path.name + ".lock"), blocking=True), path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                record = json.loads(line, object_pairs_hook=no_duplicates)
            except ValueError as exc:
                raise BackupError(f"History contains an incomplete/corrupt line {number}") from exc
            if operation is None or record.get("operation") == operation:
                result.append(record)
    return list(result)
