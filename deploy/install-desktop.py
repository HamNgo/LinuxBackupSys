#!/usr/bin/env python3
"""Install a client launcher in the current user's Linux application menu."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


MANAGED_MARKER = "X-LinuxBackupSys-Managed=true"


def exec_argument(value):
    """Quote one literal argument for both levels of desktop entry parsing."""
    if any(ord(char) < 32 for char in value):
        raise ValueError("Launcher paths cannot contain control characters")
    value = value.replace("%", "%%")
    quoted = "".join("\\" + char if char in '\\"$`' else char for char in value)
    return '"' + quoted.replace("\\", "\\\\") + '"'


def install(config):
    manager = Path(__file__).resolve().parents[1] / "backup-manager.sh"
    if not manager.is_file():
        raise ValueError(f"Cannot find the client entrypoint at {manager}")
    command = ["/bin/bash", exec_argument(str(manager))]
    if config is not None:
        config = config.expanduser()
        if not config.is_absolute() or not config.is_file():
            raise ValueError("--config must point to an existing absolute client config path")
        command.extend(["--config", exec_argument(str(config))])
    command.append("gui")
    entry = "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=LinuxBackupSys",
        "Comment=Back up, verify and restore files",
        "Comment[vi]=Sao lưu, kiểm tra và khôi phục tệp",
        "Icon=drive-harddisk",
        "Categories=Utility;Archiving;",
        "Terminal=false",
        MANAGED_MARKER,
        "Exec=" + " ".join(command),
        "",
    ])

    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not data_home.is_absolute():
        raise ValueError("XDG_DATA_HOME must be an absolute path")
    directory = data_home / "applications"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "linuxbackupsys.desktop"
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f"Expected a regular launcher file at {target}")
    if target.exists() and MANAGED_MARKER not in target.read_text(encoding="utf-8").splitlines():
        raise ValueError(f"A different launcher already exists at {target}")
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(entry)
            stream.flush()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="absolute client config to open on launch")
    args = parser.parse_args()
    try:
        launcher = install(args.config)
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print(f"Installed {launcher}\nOpen LinuxBackupSys from your applications menu.")
