"""Vietnamese desktop client. All data operations go through the existing CLI."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font, ttk
from tkinter.scrolledtext import ScrolledText

from common.core import BackupError, checked_path, check_id, load_config, read_json, relative_path, write_json


DEFAULT_CONFIG = "/etc/linux-backup/backup.conf"
REPO = Path(__file__).resolve().parents[1]
NAVY, INK, MUTED = "#182f43", "#162e3e", "#485f6a"
PAPER, LINE, BLUE = "#f6f8fa", "#d2dde3", "#1756a0"
VIEWS = ("Bản sao lưu", "Lịch sử", "Thời hạn lưu")
OPERATIONS = dict(backup="Sao lưu", restore="Khôi phục", verify="Xác minh",
                  status="Đọc danh sách", cleanup="Kiểm tra thời hạn", history="Xem lịch sử")
OPERATIONS["list-files"] = "Duyệt phiên"
STATES = dict(success="Thành công", failed="Thất bại", started="Bắt đầu",
              verified="Đã đối chiếu", skipped="Đã bỏ qua")


def run_cli(config_path, args):
    result = subprocess.run(
        [sys.executable, str(REPO / "common" / "cli.py"), "--config", config_path, *args],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise BackupError(result.stderr.strip() or f"Lệnh kết thúc với mã {result.returncode}", result.returncode)
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise BackupError("CLI trả về kết quả không đọc được.") from exc
    if not isinstance(payload, dict):
        raise BackupError("CLI trả về kết quả không đúng định dạng.")
    return payload


def preference_path():
    home = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(home) if Path(home).is_absolute() else Path.home() / ".config"
    return base / "LinuxBackupSys" / "desktop.json"


def last_config():
    try:
        value = read_json(preference_path())["config"]
        if isinstance(value, str) and Path(value).is_absolute():
            return value
    except (BackupError, OSError, ValueError, TypeError, KeyError):
        pass
    return DEFAULT_CONFIG


def local_time(value):
    try:
        return dt.datetime.fromisoformat(value).astimezone().strftime("%d/%m/%Y  %H:%M:%S")
    except (ValueError, TypeError, OverflowError):
        return str(value or "—")


def size_text(value):
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:g} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def make_table(parent, columns):
    box = ttk.Frame(parent)
    box.pack(fill="both", expand=True)
    box.columnconfigure(0, weight=1)
    box.rowconfigure(0, weight=1)
    tree = ttk.Treeview(box, columns=[col for col, _, _ in columns], show="headings",
                        height=5, selectmode="browse")
    for col, title, width in columns:
        tree.heading(col, text=title, anchor="w")
        tree.column(col, width=width, minwidth=min(width, 60), anchor="w")
    for direction, orient, row, column, sticky in (
            (tree.yview, "vertical", 0, 1, "ns"), (tree.xview, "horizontal", 1, 0, "ew")):
        bar = ttk.Scrollbar(box, orient=orient, command=direction)
        tree.configure(**{("yscrollcommand" if row == 0 else "xscrollcommand"): bar.set})
        bar.grid(row=row, column=column, sticky=sticky)
    tree.grid(row=0, column=0, sticky="nsew")
    return tree


class DesktopApp:
    def __init__(self, root, config_path, *, runner=run_cli):
        self.root = root
        self.config_path = str(config_path)
        self.runner = runner
        self.cfg = None
        self.busy = False
        self.jobs = queue.Queue()
        self.pending = None
        self.last_details = ""
        self.view = 0
        self.nav = []
        self.controls = []
        self.history_rows = {}
        self.snap_caption = tk.StringVar(root, "Chưa tải danh sách.")
        self.history_caption = tk.StringVar(root, "Chọn nơi đọc nhật ký.")
        self.retention_caption = tk.StringVar(root, "Xem bản sao nào sẽ được giữ hoặc hết hạn.")
        self.feedback = tk.StringVar(root)
        self.selected = tk.StringVar(root, "Chọn một phiên trong danh sách.")
        self.location = tk.StringVar(root)
        self.origin = tk.StringVar(root)
        root.title("LinuxBackupSys")
        root.geometry("1000x640")
        root.minsize(780, 500)
        root.configure(background=PAPER)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        family = font.nametofont("TkDefaultFont").actual("family")
        self.family = family
        style.configure(".", font=(family, 10), foreground=INK)
        style.configure("TFrame", background=PAPER)
        style.configure("TLabel", background=PAPER)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=(family, 23, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Primary.TButton", background=BLUE, foreground="white", borderwidth=0, padding=(14, 9))
        style.map("Primary.TButton", background=[("disabled", "#cad6dd"), ("active", "#104580")],
                  foreground=[("disabled", MUTED), ("!disabled", "white")])
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=32,
                        bordercolor=LINE, borderwidth=1)
        style.configure("Treeview.Heading", font=(family, 10, "bold"), padding=(5, 7),
                        background="#e8eef2", foreground=INK)
        style.map("Treeview", background=[("selected", "#cfe2fa")], foreground=[("selected", INK)])
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self._sidebar()
        self.main = ttk.Frame(root, padding=(20, 18, 20, 12))
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)
        heading = ttk.Frame(self.main)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.title = ttk.Label(heading, style="Title.TLabel")
        self.title.pack(side="left")
        self.backup_button = self.button(heading, "Sao lưu ngay", self.backup, primary=True)
        self.backup_button.pack(side="right")
        self.pages = [ttk.Frame(self.main) for _ in VIEWS]
        self._snapshot_page()
        self._history_page()
        self._retention_page()
        self._statusbar()
        self.welcome = ttk.Frame(self.main, padding=(0, 18))
        ttk.Label(self.welcome, text="Chọn cấu hình cho máy này", font=(family, 16, "bold")).pack(anchor="w")
        ttk.Label(self.welcome, text="Mở tệp cấu hình client để dùng kho sao lưu qua LAN hoặc Tailscale. "
                  "Nếu đây là lần đầu, bạn có thể nhập thông tin máy chủ và chọn thư mục ngay tại đây.",
                  style="Muted.TLabel", wraplength=435).pack(anchor="w", pady=(8, 16))
        actions = ttk.Frame(self.welcome)
        actions.pack(anchor="w")
        ttk.Button(actions, text="Mở cấu hình…", style="Primary.TButton", command=self.choose_config).pack(side="left")
        ttk.Button(actions, text="Soạn cấu hình…", command=self.edit_config).pack(side="left", padx=8)
        self.open_view(0, load=False)
        self.use_config(self.config_path)

    def button(self, parent, label, command, *, primary=False):
        button = ttk.Button(parent, text=label, command=command,
                            style="Primary.TButton" if primary else "TButton")
        self.controls.append(button)
        return button

    def _sidebar(self):
        self.brand_font = font.Font(root=self.root, family=self.family, size=13, weight="bold")
        rail = tk.Frame(self.root, bg=NAVY, padx=12, pady=16, width=max(195, self.brand_font.measure("LinuxBackupSys") + 40))
        rail.grid(row=0, column=0, sticky="nsew")
        rail.grid_propagate(False)
        rail.columnconfigure(0, weight=1)
        rail.rowconfigure(5, weight=1)
        mark = tk.Canvas(rail, width=34, height=32, bg=NAVY, highlightthickness=0)
        mark.grid(row=0, column=0, sticky="w", padx=6)
        for y in (18, 12, 6):
            mark.create_polygon(2, y + 3, 16, y - 3, 30, y + 3, 16, y + 10,
                                fill="#a1d4f1" if y == 6 else "#609bc4", outline=NAVY, width=2)
        tk.Label(rail, text="LinuxBackupSys", fg="white", bg=NAVY, font=self.brand_font
                 ).grid(row=1, sticky="w", padx=5, pady=(4, 24))
        for idx, title in enumerate(VIEWS):
            link = tk.Button(rail, text=title, anchor="w", relief="flat", bd=0, padx=12, pady=9,
                             font=(self.family, 11), fg="white", bg=NAVY, takefocus=True,
                             highlightcolor="#9bd6ff", highlightbackground=NAVY, highlightthickness=1,
                             activebackground="#31536f", activeforeground="white",
                             command=lambda i=idx: self.open_view(i))
            link.grid(row=idx + 2, sticky="ew", pady=1)
            self.nav.append(link)
        tk.Label(rail, text="Máy chủ", bg=NAVY, fg="#c4d7e2", font=(self.family, 9)
                 ).grid(row=6, sticky="w", padx=5)
        tk.Label(rail, textvariable=self.location, wraplength=165, justify="left", bg=NAVY, fg="white",
                 font=(self.family, 10, "bold")).grid(row=7, sticky="w", padx=5, pady=(2, 12))
        for row, (text, command) in enumerate((("Mở cấu hình…", self.choose_config),
                                                ("Soạn cấu hình…", self.edit_config)), 8):
            button = ttk.Button(rail, text=text, command=command)
            button.grid(row=row, sticky="ew", pady=2)
            if row == 8:
                self.open_config_button = button
            else:
                self.edit_config_button = button

    def _snapshot_page(self):
        page = self.pages[0]
        ttk.Label(page, text="Nguồn sao lưu", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(page, textvariable=self.origin, wraplength=550, font=(self.family, 12, "bold")
                  ).pack(anchor="w", pady=(3, 14))
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, textvariable=self.snap_caption, style="Muted.TLabel").pack(side="left")
        self.button(row, "Làm mới", self.refresh).pack(side="right")
        actions = ttk.Frame(page)
        actions.pack(side="bottom", fill="x")
        self.restore_button = self.button(actions, "Khôi phục…", self.restore)
        self.restore_button.pack(side="left")
        self.verify_button = self.button(actions, "Kiểm tra SHA-256", self.verify)
        self.verify_button.pack(side="left", padx=8)
        ttk.Label(page, textvariable=self.selected, style="Muted.TLabel").pack(side="bottom", anchor="w", pady=(10, 5))
        self.snapshots = make_table(page, (("time", "Thời gian", 158), ("files", "Số file", 65),
                                           ("size", "Dung lượng", 84), ("check", "So với nguồn", 115)))
        self.snapshots.bind("<<TreeviewSelect>>", lambda _event: self._selection_changed())
        self.snapshots.bind("<Return>", lambda _event: self.restore())
        self.snapshots.bind("<Double-1>", lambda e: self.restore() if self.snapshots.identify_row(e.y) else None)

    def _history_page(self):
        page = self.pages[1]
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 8))
        self.button(row, "Nhật ký máy chủ", self.show_history).pack(side="left")
        self.button(row, "Nhật ký máy này", lambda: self.show_history(local=True)).pack(side="left", padx=6)
        ttk.Label(page, textvariable=self.history_caption, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.event_button = self.button(page, "Chi tiết sự kiện…", self.event_details)
        self.event_button.pack(side="bottom", anchor="w", pady=(8, 0))
        self.events = make_table(page, (("time", "Thời gian", 155), ("op", "Thao tác", 115),
                                        ("state", "Kết quả", 100)))
        self.events.bind("<Return>", lambda _event: self.event_details())
        self.events.bind("<Double-1>", lambda e: self.event_details() if self.events.identify_row(e.y) else None)
        self.events.bind("<<TreeviewSelect>>", lambda _event: self._states())

    def _retention_page(self):
        page = self.pages[2]
        self.button(page, "Xem trước chính sách", self.preview_cleanup).pack(anchor="w")
        ttk.Label(page, textvariable=self.retention_caption, style="Muted.TLabel", wraplength=510
                  ).pack(anchor="w", pady=(10, 8))
        self.retention = make_table(page, (("id", "Mã phiên", 264), ("action", "Dự kiến", 72),
                                           ("reason", "Lý do", 140)))

    def _statusbar(self):
        area = ttk.Frame(self.main)
        area.grid(row=2, column=0, sticky="ew", pady=(15, 0))
        area.columnconfigure(0, weight=1)
        ttk.Separator(area).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.note = ttk.Label(area, textvariable=self.feedback, wraplength=440, style="Muted.TLabel")
        self.note.grid(row=1, column=0, sticky="w")
        self.detail_button = ttk.Button(area, text="Chi tiết…",
                                        command=lambda: self.details("Kết quả thao tác", self.last_details))
        self.detail_button.grid(row=1, column=1, sticky="e")
        self.progress = ttk.Progressbar(area, mode="indeterminate", length=80)
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.progress.grid_remove()

    def open_view(self, index, load=True):
        if self.busy:
            return
        self.view = index
        for i, (page, link) in enumerate(zip(self.pages, self.nav)):
            if i == index and self.cfg:
                page.grid(row=1, column=0, sticky="nsew")
            else:
                page.grid_remove()
            link.configure(bg="#31536f" if i == index else NAVY, fg="white" if i == index else "#cadbe5")
        self.title.configure(text=VIEWS[index])
        if self.cfg:
            self.welcome.grid_remove()
        else:
            self.title.configure(text="Kết nối kho sao lưu")
            self.welcome.grid(row=1, column=0, sticky="nsew")
        if load and self.cfg:
            (self.refresh, self.show_history, self.preview_cleanup)[index]()

    def choose_config(self):
        if not self.busy:
            path = filedialog.askopenfilename(parent=self.root, title="Mở cấu hình máy khách",
                                              filetypes=[("Cấu hình", "*.conf *.toml"), ("Mọi file", "*")])
            if path:
                self.use_config(path, remember=True)

    def edit_config(self):
        if not self.busy:
            from client.desktop_config import edit_config
            path = edit_config(self.root, self.config_path)
            if path:
                self.use_config(path, remember=True)

    def use_config(self, path, remember=False):
        if self.busy:
            return
        self.config_path = str(path)
        self.cfg = None
        for tree in (self.snapshots, self.events, self.retention):
            tree.delete(*tree.get_children())
        self.history_rows.clear()
        self.snap_caption.set("Chưa tải danh sách.")
        self.history_caption.set("Chọn nơi đọc nhật ký.")
        self.retention_caption.set("Xem bản sao nào sẽ được giữ hoặc hết hạn.")
        self.open_view(0, load=False)
        try:
            self.cfg = load_config(self.config_path, "client")
        except (OSError, ValueError, BackupError) as exc:
            self.origin.set("Mở hoặc soạn cấu hình máy khách để bắt đầu.")
            self.location.set("Chưa cấu hình")
            self.report("Cần cấu hình máy khách.", f"{path}\n{exc}", error=True)
        else:
            self.open_view(0, load=False)
            self.origin.set(self.cfg["BACKUP_SOURCE"])
            self.location.set(f'{self.cfg["SSH_USER"]}@{self.cfg["SSH_HOST"]}')
            if remember:
                try:
                    pref = checked_path(preference_path(), exists=False)
                    pref.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    write_json(pref, {"config": self.config_path})
                except (ValueError, OSError, BackupError) as exc:
                    self.details("Không thể nhớ cấu hình cho lần sau", str(exc))
            self.refresh()
        self._selection_changed()

    def _states(self):
        available = not self.busy and self.cfg is not None
        for widget in self.controls:
            widget.state(["!disabled" if available else "disabled"])
        for widget in (self.open_config_button, self.edit_config_button):
            widget.state(["disabled" if self.busy else "!disabled"])
        for widget in self.nav:
            widget.configure(state="normal" if available else "disabled")
        if not self.snapshots.selection():
            self.restore_button.state(["disabled"])
            self.verify_button.state(["disabled"])
        if not self.events.selection():
            self.event_button.state(["disabled"])

    def _selection_changed(self):
        selected = self.snapshots.selection()
        self.selected.set(f"Mã phiên   {selected[0]}" if selected else "Chọn một phiên trong danh sách.")
        self._states()

    def report(self, message, detail="", *, error=False):
        self.feedback.set(message)
        self.note.configure(foreground="#9d2e26" if error else MUTED)
        self.last_details = detail
        self.detail_button.state(["!disabled" if detail else "disabled"])

    def _run(self, args, caption, on_success, on_error=None):
        if self.busy or not self.cfg:
            return
        self.busy = True
        self.pending = (args[0], on_success, on_error)
        self._states()
        self.report(caption)
        self.progress.grid()
        self.progress.start(12)
        config_path = self.config_path

        def work():
            try:
                data = self.runner(config_path, args)
                self.jobs.put((data, None))
            except Exception as exc:
                self.jobs.put((None, exc))

        threading.Thread(target=work, name="backup-operation", daemon=True).start()
        self.root.after(60, self._poll)

    def _poll(self):
        try:
            data, error = self.jobs.get_nowait()
        except queue.Empty:
            self.root.after(60, self._poll)
            return
        operation, callback, on_error = self.pending
        self.pending = None
        self.busy = False
        self.progress.stop()
        self.progress.grid_remove()
        self._states()
        if error is not None:
            code = getattr(error, "code", None)
            hint = {2: "Kiểm tra cấu hình và đường dẫn.", 3: "Kho đang bận. Hãy thử lại sau.",
                    4: "Kiểm tra SSH và kết nối tới máy chủ.",
                    5: "Kiểm tra dữ liệu và manifest của phiên."}.get(code, "Xem chi tiết để xử lý.")
            if operation == "status":
                self.snap_caption.set("Chưa cập nhật được danh sách.")
            self.report(f"{OPERATIONS.get(operation, operation)} thất bại. {hint}", str(error), error=True)
            if on_error is not None:
                on_error(error)
            return
        try:
            callback(data)
        except (TypeError, ValueError, KeyError, BackupError, tk.TclError) as exc:
            self.report("Không đọc được kết quả thao tác. Hãy kiểm tra lịch sử.", str(exc), error=True)

    def refresh(self, notice="", preferred_id=None):
        def loaded(data):
            old = self.snapshots.selection()
            self.snapshots.delete(*self.snapshots.get_children())
            rows = data["snapshots"]
            for item in reversed(rows):
                sid = check_id(item["snapshot_id"])
                self.snapshots.insert("", "end", iid=sid, values=(
                    local_time(item["completed_at"]), item["files"], size_text(item["bytes"]),
                    STATES.get(item["verification"], item["verification"])))
            self.snap_caption.set(f"{len(rows)} phiên đã hoàn tất" if rows else "Kho trống. Chọn “Sao lưu ngay” để tạo phiên đầu.")
            for sid in (preferred_id, *old, data.get("latest")):
                if sid and self.snapshots.exists(sid):
                    self.snapshots.selection_set(sid)
                    self.snapshots.focus(sid)
                    self.snapshots.see(sid)
                    break
            self._selection_changed()
            staging = data.get("staging") or []
            status = notice or "Đã cập nhật từ máy chủ."
            if staging:
                status += f" Còn {len(staging)} phiên ở vùng tạm."
            self.report(status, "\n".join(staging))
        def refresh_failed(error):
            if notice:
                self.report(f"{notice} Chưa cập nhật được danh sách.", str(error), error=True)

        self._run(["status"], (notice + " " if notice else "") + "Đang đọc danh sách từ máy chủ…",
                  loaded, refresh_failed)

    def backup(self):
        if self.busy or not self.cfg:
            return
        self.open_view(0, load=False)
        def completed(data):
            sid = check_id(data["snapshot_id"])
            self.refresh(f"Đã sao lưu phiên {sid}.", preferred_id=sid)
        self._run(["backup"], "Đang sao lưu dữ liệu…", completed)

    def verify(self):
        selection = self.snapshots.selection()
        if selection:
            sid = selection[0]
            def completed(data):
                self.report(f"Đã kiểm tra {data['files']} file, nội dung khớp manifest của phiên.",
                            f"{sid}\nĐối chiếu với nguồn khi sao lưu: {STATES.get(data['source_verification'], data['source_verification'])}")
            self._run(["verify", sid], "Đang kiểm tra SHA-256…", completed)

    def restore(self):
        selected = self.snapshots.selection()
        if self.busy or not selected or not self.cfg:
            return
        sid = selected[0]
        dialog = tk.Toplevel(self.root)
        dialog.title("Khôi phục bản sao")
        dialog.transient(self.root)
        dialog.resizable(True, False)
        box = ttk.Frame(dialog, padding=18)
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text="Khôi phục bản sao", font=(self.family, 16, "bold")).grid(row=0, sticky="w")
        ttk.Label(box, text=sid, style="Muted.TLabel").grid(row=1, sticky="w", pady=(3, 14))
        ttk.Label(box, text="File hoặc thư mục trong phiên").grid(row=2, sticky="w")
        entry = ttk.Entry(box, width=55)
        entry.grid(row=3, column=0, sticky="ew")
        def pick():
            from client.desktop_picker import pick_snapshot_path
            name = pick_snapshot_path(dialog, sid, self._run)
            if name is not None:
                entry.delete(0, "end")
                entry.insert(0, name)
        ttk.Button(box, text="Duyệt phiên…", command=pick).grid(row=3, column=1, padx=(5, 0))
        ttk.Label(box, text="Để trống để khôi phục toàn bộ phiên.", style="Muted.TLabel").grid(row=4, sticky="w")
        ttk.Label(box, text="Thư mục đích mới").grid(row=5, sticky="w", pady=(12, 0))
        dest = tk.StringVar(dialog)
        ttk.Entry(box, textvariable=dest).grid(row=6, column=0, sticky="ew")
        def browse():
            parent = filedialog.askdirectory(parent=dialog, title="Chọn thư mục cha của đích mới", mustexist=True)
            if parent:
                dest.set(str(Path(parent) / f"restore-{sid}"))
        ttk.Button(box, text="Chọn nơi lưu…", command=browse).grid(row=6, column=1, padx=(5, 0))
        ttk.Label(box, text=f"Để trống để tạo thư mục mới trong {self.cfg['RESTORE_ROOT']}",
                  wraplength=420, style="Muted.TLabel").grid(row=7, columnspan=2, sticky="w")
        row = ttk.Frame(box)
        row.grid(row=8, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(row, text="Hủy", command=dialog.destroy).pack(side="left", padx=5)
        def submit():
            path, destination = entry.get(), dest.get()
            dialog.destroy()
            self.start_restore(sid, path, destination)
        ttk.Button(row, text="Khôi phục", style="Primary.TButton", command=submit).pack(side="left")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        entry.focus_set()

    def start_restore(self, snapshot_id, selection="", destination=""):
        if self.busy or not self.cfg:
            return
        try:
            check_id(snapshot_id)
            path = relative_path(selection or ".")
            if destination and checked_path(destination, exists=False).exists():
                raise BackupError("Thư mục đích đã tồn tại. Hãy chọn một tên mới.")
        except (ValueError, OSError, BackupError) as exc:
            self.report("Không thể khôi phục. Kiểm tra lại đường dẫn.", str(exc), error=True)
            return
        args = ["restore", snapshot_id, f"--path={path}"]
        if destination:
            args.append(f"--destination={destination}")
        self._run(args, "Đang khôi phục và kiểm tra dữ liệu…", lambda data:
                  self.report("Đã khôi phục và xác minh. Đích: " + data["destination"], data["destination"]))

    def show_history(self, local=False):
        if self.busy:
            return
        self.open_view(1, load=False)
        place = "máy này" if local else "máy chủ"
        def loaded(data):
            self.events.delete(*self.events.get_children())
            self.history_rows.clear()
            for event in reversed(data["events"]):
                op, status = event.get("operation", ""), event.get("status", "")
                iid = self.events.insert("", "end", values=(local_time(event.get("time")),
                                         OPERATIONS.get(op, op), STATES.get(status, status)))
                self.history_rows[iid] = event
            self.history_caption.set(f"{len(self.history_rows)} sự kiện gần nhất trên {place}.")
            self.report(f"Đã đọc nhật ký {place}.")
            self._states()
        args = ["history", "--limit", "100"]
        if local:
            args.append("--local")
        self._run(args, f"Đang đọc nhật ký {place}…", loaded)

    def event_details(self):
        selection = self.events.selection()
        if selection:
            self.details("Chi tiết sự kiện", json.dumps(self.history_rows[selection[0]], ensure_ascii=False, indent=2))

    def preview_cleanup(self):
        if self.busy:
            return
        self.open_view(2, load=False)
        def loaded(data):
            self.retention.delete(*self.retention.get_children())
            reasons = {"newest-successful": "Phiên mới nhất", "expired": "Đã hết hạn",
                       "within-retention": "Còn thời hạn"}
            count = 0
            for row in data["decisions"]:
                delete = row["action"] == "delete"
                count += int(delete)
                self.retention.insert("", "end", values=(row["snapshot_id"], "Xóa" if delete else "Giữ",
                                      reasons.get(row["reason"], row["reason"])))
            self.retention_caption.set(f"Thời hạn {data['retention_days']} ngày · {count} phiên dự kiến xóa.")
            self.report("Đã xem trước chính sách. Chưa xóa dữ liệu.")
        self._run(["cleanup", "--dry-run"], "Đang kiểm tra thời hạn lưu…", loaded)

    def details(self, title, detail):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        text = ScrolledText(dlg, wrap="word", width=75, height=16, padx=12, pady=10)
        text.pack(fill="both", expand=True)
        text.insert("1.0", detail)
        text.configure(state="disabled")
        ttk.Button(dlg, text="Đóng", command=dlg.destroy).pack(anchor="e", padx=8, pady=8)
        dlg.bind("<Escape>", lambda _event: dlg.destroy())

    def close(self):
        if self.busy:
            self.report("Thao tác đang chạy. Bạn có thể đóng cửa sổ khi thao tác hoàn tất.")
        else:
            self.root.destroy()


def launch(config_path=None):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise BackupError(f"Không mở được cửa sổ. Hãy chạy trong phiên desktop của máy khách. {exc}") from exc
    DesktopApp(root, config_path or last_config())
    root.mainloop()
    return 0
