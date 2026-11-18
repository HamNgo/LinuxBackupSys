"""SHA-256 baseline with unambiguous JSON paths and strict object validation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from common.core import BackupError, checked_path, relative_path


def file_entry(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise BackupError(f"Only regular files and directories are supported: {path}", 2)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise BackupError(f"File changed while opening: {path}", 5)
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
    if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise BackupError(f"Source changed while hashing: {path}", 5)
    return {"type": "file", "size": after.st_size, "mode": stat.S_IMODE(after.st_mode), "sha256": digest}


def scan(root):
    root = checked_path(root)
    entries = {}

    def visit(path, name):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            checked_path(path)
            if name:
                entries[name] = {"type": "dir", "mode": stat.S_IMODE(info.st_mode)}
            for child in sorted(path.iterdir()):
                try:
                    child.name.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise BackupError("Source filenames must be valid UTF-8", 2) from exc
                visit(child, (name + "/" if name else "") + child.name)
        elif stat.S_ISREG(info.st_mode):
            entries[name] = file_entry(path)
        else:
            raise BackupError(f"Symlinks and special files are not supported: {path}", 2)

    visit(root, "" if root.is_dir() else root.name)
    return {"schema": 1, "algorithm": "sha256", "entries": entries}


def validate(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "algorithm", "entries"}:
        raise BackupError("Invalid manifest structure", 5)
    if type(manifest["schema"]) is not int or manifest["schema"] != 1 or manifest["algorithm"] != "sha256" or not isinstance(manifest["entries"], dict):
        raise BackupError("Unsupported manifest", 5)
    entries = manifest["entries"]
    for name, entry in entries.items():
        relative_path(name)
        if name == "." or not isinstance(entry, dict):
            raise BackupError("Invalid manifest entry", 5)
        kind = entry.get("type")
        expected = {"type", "mode"} | ({"size", "sha256"} if kind == "file" else set())
        if kind not in ("file", "dir") or set(entry) != expected:
            raise BackupError(f"Invalid manifest entry: {name}", 5)
        if type(entry["mode"]) is not int or not 0 <= entry["mode"] <= 0o7777:
            raise BackupError("Invalid file mode", 5)
        if kind == "file" and (type(entry["size"]) is not int or entry["size"] < 0 or
                               not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])):
            raise BackupError(f"Invalid file checksum/size: {name}", 5)
        parent = Path(name).parent.as_posix()
        while parent != ".":
            if entries.get(parent, {}).get("type") != "dir":
                raise BackupError(f"Missing directory entry: {parent}", 5)
            parent = Path(parent).parent.as_posix()
    return manifest


def verify(root, expected):
    validate(expected)
    actual = scan(root)
    if actual != expected:
        old, new = expected["entries"], actual["entries"]
        missing = sorted(old.keys() - new.keys())
        extra = sorted(new.keys() - old.keys())
        changed = sorted(k for k in old.keys() & new.keys() if old[k] != new[k])
        raise BackupError(f"Integrity failed: missing={missing[:10]!r}, extra={extra[:10]!r}, mismatch={changed[:10]!r}", 5)
    return {"verified": True, "files": sum(e["type"] == "file" for e in expected["entries"].values())}


def subset(manifest, selection):
    validate(manifest)
    relative_path(selection)
    if selection == ".":
        return manifest, "dir"
    entry = manifest["entries"].get(selection)
    if entry is None:
        raise BackupError(f"Path is absent from snapshot: {selection}", 2)
    if entry["type"] == "file":
        selected = {Path(selection).name: entry}
    else:
        prefix = selection + "/"
        selected = {k[len(prefix):]: v for k, v in manifest["entries"].items() if k.startswith(prefix)}
    return {"schema": 1, "algorithm": "sha256", "entries": selected}, entry["type"]
