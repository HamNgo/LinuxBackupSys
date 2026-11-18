"""Bounded newline-delimited JSON control protocol; stdout is reserved for JSON."""
import json
import select

from common.core import BackupError

MAX_MESSAGE = 64 * 1024 * 1024


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def send(stream, value):
    data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(data) > MAX_MESSAGE:
        raise BackupError("Control message/manifest exceeds 64 MiB", 2)
    remaining = memoryview(data)
    while remaining:
        written = stream.write(remaining)
        if not written:
            raise BackupError("Control connection stopped accepting data", 4)
        remaining = remaining[written:]
    stream.flush()


def receive(stream, timeout):
    # Callers use unbuffered pipes to avoid hidden read-ahead and select races.
    if not select.select([stream], [], [], timeout)[0]:
        raise BackupError("Control session timed out", 4)
    data = bytearray()
    # A buffered readline would lose the timeout on a partial message. Read with
    # a fixed deadline and check for the terminator after each chunk instead.
    import os
    import time
    deadline = time.monotonic() + timeout
    while True:
        chunk = os.read(stream.fileno(), 65536)
        if not chunk:
            raise BackupError("Control connection closed before completion", 4)
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise BackupError("Control message exceeds 64 MiB", 2)
        if data.endswith(b"\n"):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
            raise BackupError("Control message timed out", 4)
    try:
        value = json.loads(data, object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError) as exc:
        raise BackupError("Invalid or duplicate-key protocol JSON", 2) from exc
    if not isinstance(value, dict):
        raise BackupError("Expected a JSON object", 2)
    return value
