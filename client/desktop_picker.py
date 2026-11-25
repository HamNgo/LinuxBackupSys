"""Select a payload-relative file or directory from a stored snapshot."""
from pathlib import PurePosixPath
import tkinter as tk
from tkinter import ttk


def pick_snapshot_path(parent, snapshot_id, run):
    dialog = tk.Toplevel(parent)
    dialog.title("Chọn nội dung khôi phục")
    dialog.transient(parent)
    dialog.geometry("600x420")
    dialog.minsize(415, 320)
    panel = ttk.Frame(dialog, padding=14)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(1, weight=1)
    current = PurePosixPath(".")
    result = None
    waiting = False
    entries = {}
    label = tk.StringVar(dialog)
    status = tk.StringVar(dialog)
    toolbar = ttk.Frame(panel)
    toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    up = ttk.Button(toolbar, text="Lên một cấp", command=lambda: load(current.parent))
    up.pack(side="left", padx=(0, 8))
    ttk.Label(toolbar, textvariable=label, wraplength=320).pack(side="left")
    files = ttk.Treeview(panel, columns=("name", "kind"), show="headings", selectmode="browse")
    files.heading("name", text="Tên", anchor="w")
    files.heading("kind", text="Loại", anchor="w")
    files.column("name", width=265, anchor="w")
    files.column("kind", width=90, anchor="w", stretch=False)
    files.grid(row=1, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(panel, orient="vertical", command=files.yview)
    scroll.grid(row=1, column=1, sticky="ns")
    files.configure(yscrollcommand=scroll.set)
    ttk.Label(panel, textvariable=status, wraplength=520).grid(row=2, column=0, columnspan=2,
                                                              sticky="w", pady=6)
    footer = ttk.Frame(panel)
    footer.grid(row=3, column=0, columnspan=2, sticky="ew")

    def controls():
        row = selected()
        up.state(["disabled" if waiting or current == PurePosixPath(".") else "!disabled"])
        enter.state(["!disabled" if not waiting and row and row["type"] == "dir" else "disabled"])
        choose.state(["!disabled" if row and not waiting else "disabled"])

    def selected():
        selection = files.selection()
        return entries.get(selection[0]) if selection else None

    def load(directory):
        nonlocal waiting
        if waiting:
            return
        waiting = True
        controls()
        status.set("Đang đọc danh sách từ máy chủ…")

        def loaded(data):
            nonlocal current, waiting
            waiting = False
            current = directory
            label.set("Gốc bản sao" if str(current) == "." else str(current))
            entries.clear()
            files.delete(*files.get_children())
            for item in data["entries"]:
                iid = files.insert("", "end", values=(item["name"], "Thư mục" if item["type"] == "dir" else "Tệp"))
                entries[iid] = item
            status.set("Thư mục trống." if not entries else "Chọn một mục để khôi phục, hoặc mở thư mục để xem bên trong.")
            controls()

        def failed(exc):
            nonlocal waiting
            waiting = False
            status.set("Không đọc được danh sách. Hãy đóng cửa sổ và nhập đường dẫn, hoặc kiểm tra phiên bản máy chủ.")
            controls()

        run(["list-files", snapshot_id, f"--path={directory}"], "Đang duyệt nội dung bản sao…", loaded, failed)

    def finish():
        nonlocal result
        item = selected()
        if item and not waiting:
            result = str(current / item["name"])
            dialog.destroy()

    def open_item():
        item = selected()
        if item and not waiting:
            if item["type"] == "dir":
                load(current / item["name"])
            else:
                finish()

    def close():
        if not waiting:
            dialog.destroy()

    enter = ttk.Button(footer, text="Mở thư mục", command=open_item)
    enter.pack(side="left")
    choose = ttk.Button(footer, text="Chọn mục này", style="Primary.TButton", command=finish)
    choose.pack(side="right")
    ttk.Button(footer, text="Đóng", command=close).pack(side="right", padx=6)
    files.bind("<<TreeviewSelect>>", lambda _: controls())
    files.bind("<Double-1>", lambda event: open_item() if files.identify_row(event.y) else None)
    files.bind("<Return>", lambda _: open_item())
    dialog.bind("<Escape>", lambda _: close())
    dialog.protocol("WM_DELETE_WINDOW", close)
    dialog.grab_set()
    load(current)
    parent.wait_window(dialog)
    parent.grab_set()
    return result
