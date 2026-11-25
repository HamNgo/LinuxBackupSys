"""Native client configuration editor. Only the selected configuration is read."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tomllib

from common.core import BackupError, checked_path, load_config, sync_dir


def _template():
    # Read the shipped example as data. It may be installed read-only under /opt.
    with Path(__file__).with_name("client.conf.example").open("rb") as source:
        values = tomllib.load(source)
    home = str(Path.home())
    for key in ("BACKUP_SOURCE", "RESTORE_ROOT", "LOG_FILE", "SSH_IDENTITY", "SSH_KNOWN_HOSTS"):
        values[key] = values[key].replace("/home/backup-client", home, 1)
    return values


def _save_new(target, values):
    """Publish a private, CLI-validated file without replacing an existing path."""
    target = checked_path(target, exists=False)
    if target.exists():
        raise BackupError("Tên tệp đã tồn tại. Hãy chọn tên mới.")
    if not target.parent.is_dir():
        raise BackupError("Thư mục chứa tệp cấu hình phải tồn tại.")
    fd, temp_name = tempfile.mkstemp(prefix=".linux-backup-", dir=target.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for key, value in values.items():
                literal = json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
                handle.write(f"{key} = {literal}\n")
            handle.flush()
            os.fsync(handle.fileno())
        load_config(temporary, "client")
        if os.name == "nt":
            # Windows rename already refuses a destination created by another process.
            temporary.rename(target)
        else:
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    sync_dir(target.parent)
    return str(target)


def edit_config(parent, current_path: str) -> str | None:
    """Open a modal editor and return the path of the newly saved client config."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    values = _template()
    starting_path = Path(current_path) if current_path else None
    load_error = None
    if starting_path is not None and starting_path.exists():
        try:
            values = load_config(starting_path, "client")
        except (BackupError, OSError, ValueError) as exc:
            load_error = str(exc)

    window = tk.Toplevel(parent)
    window.title("Cấu hình máy khách")
    window.transient(parent)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)
    result = None
    file_types = [("Cấu hình", "*.conf *.toml"), ("Tất cả tệp", "*")]
    fields = {
        key: (tk.BooleanVar(window, value) if isinstance(value, bool)
              else tk.StringVar(window, str(value)))
        for key, value in values.items()
    }
    header = ttk.Frame(window, padding=(16, 14, 16, 8))
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)
    source_text = tk.StringVar(window)
    ttk.Label(header, textvariable=source_text, wraplength=370).grid(row=0, column=0, sticky="w")
    source_text.set(f"Đang chỉnh bản sao của {starting_path.name}"
                    if starting_path and starting_path.is_file() and not load_error else "Tạo cấu hình từ mẫu")

    def open_file():
        name = filedialog.askopenfilename(parent=window, title="Mở cấu hình máy khách",
                                          filetypes=file_types)
        if not name:
            return
        try:
            loaded = load_config(name, "client")
        except (BackupError, OSError, ValueError) as exc:
            messagebox.showerror("Không đọc được cấu hình", str(exc), parent=window)
            return
        for key, value in loaded.items():
            fields[key].set(value)
        source_text.set(f"Đang chỉnh bản sao của {Path(name).name}")

    ttk.Button(header, text="Mở cấu hình khác…", command=open_file).grid(row=0, column=1, padx=(12, 0))
    notebook = ttk.Notebook(window)
    notebook.grid(row=1, column=0, padx=16, pady=(4, 12), sticky="nsew")

    def add_page(title):
        page = ttk.Frame(notebook, padding=(12, 12))
        page.columnconfigure(1, weight=1)
        notebook.add(page, text=title)
        return page

    def browse(key, kind):
        current = Path(fields[key].get())
        folder = current if current.is_dir() else current.parent
        options = {"parent": window, "initialdir": str(folder if folder.is_dir() else Path.home())}
        if kind == "directory":
            name = filedialog.askdirectory(**options, mustexist=True)
        elif kind == "log":
            selected = filedialog.askdirectory(**options, mustexist=True, title="Thư mục lưu history.jsonl")
            name = str(Path(selected) / "history.jsonl") if selected else ""
        else:
            name = filedialog.askopenfilename(**options)
        if name:
            fields[key].set(name)

    def row(page, index, label, key, picks=()):
        ttk.Label(page, text=label).grid(row=index, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(page, textvariable=fields[key], width=29)
        entry.grid(row=index, column=1, sticky="ew", pady=4)
        for col, (caption, kind) in enumerate(picks, start=2):
            ttk.Button(page, text=caption, command=lambda k=kind: browse(key, k)).grid(
                row=index, column=col, padx=(5, 0), pady=4
            )
        return entry

    data = add_page("Dữ liệu")
    first = row(data, 0, "Mã máy khách", "CLIENT_ID")
    row(data, 1, "Nguồn sao lưu", "BACKUP_SOURCE", (("Tệp…", "file"), ("Thư mục…", "directory")))
    row(data, 2, "Thư mục khôi phục", "RESTORE_ROOT", (("Chọn…", "directory"),))
    row(data, 3, "Tệp nhật ký", "LOG_FILE", (("Thư mục…", "log"),))
    ttk.Checkbutton(data, text="Đối chiếu SHA-256 với nguồn khi sao lưu",
                    variable=fields["VERIFY_CHECKSUM"]).grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
    ttk.Label(data, text="Chọn thư mục khôi phục và nơi lưu nhật ký đã tồn tại, nằm ngoài nguồn sao lưu.",
              wraplength=465).grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

    ssh = add_page("Kết nối SSH")
    row(ssh, 0, "Máy chủ (IP hoặc DNS)", "SSH_HOST")
    row(ssh, 1, "Tài khoản SSH", "SSH_USER")
    row(ssh, 2, "Cổng SSH", "SSH_PORT")
    row(ssh, 3, "Khóa SSH riêng", "SSH_IDENTITY", (("Chọn…", "file"),))
    row(ssh, 4, "Tệp known_hosts", "SSH_KNOWN_HOSTS", (("Chọn…", "file"),))
    ttk.Checkbutton(ssh, text="Nén dữ liệu khi truyền", variable=fields["COMPRESSION"]).grid(
        row=5, column=0, columnspan=3, sticky="w", pady=(10, 0)
    )

    server = add_page("Máy chủ")
    row(server, 0, "Chương trình trên máy chủ", "SERVER_PROGRAM")
    row(server, 1, "Cấu hình trên máy chủ", "SERVER_CONFIG")
    row(server, 2, "Thời gian chờ (giây)", "TIMEOUT_SECONDS")
    ttk.Label(server, text="Nhập đường dẫn tuyệt đối đến agent.py và tệp cấu hình trên máy nhận bản sao.",
              wraplength=465).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def save():
        nonlocal result
        edited = {key: field.get() for key, field in fields.items()}
        for key, label in (("SSH_PORT", "Cổng SSH"), ("TIMEOUT_SECONDS", "Thời gian chờ")):
            try:
                edited[key] = int(edited[key], 10)
            except ValueError:
                messagebox.showerror("Giá trị chưa hợp lệ", f"{label} phải là số nguyên.", parent=window)
                return
        name = filedialog.asksaveasfilename(parent=window, title="Lưu cấu hình với tên mới",
                                            initialdir=str(Path.home()), initialfile="backup-client.conf",
                                            defaultextension=".conf", filetypes=file_types, confirmoverwrite=False)
        if not name:
            return
        try:
            result = _save_new(name, edited)
        except (BackupError, OSError, ValueError) as exc:
            messagebox.showerror("Chưa lưu được cấu hình", str(exc), parent=window)
            return
        window.destroy()

    footer = ttk.Frame(window, padding=(16, 0, 16, 14))
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    ttk.Button(footer, text="Hủy", command=window.destroy).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(footer, text="Lưu bản mới…", command=save).grid(row=0, column=2)
    window.bind("<Escape>", lambda _event: window.destroy())
    window.grab_set()
    first.focus_set()
    if load_error:
        messagebox.showwarning("Đang dùng mẫu cấu hình",
                               f"Không mở được {current_path}.\n\n{load_error}", parent=window)
    parent.wait_window(window)
    return result
