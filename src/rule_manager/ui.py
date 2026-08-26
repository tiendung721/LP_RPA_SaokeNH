from __future__ import annotations

import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from src.normalizer import normalize_text

from .models import (
    CATALOG_DEFINITIONS,
    CATALOG_PAYABLE,
    MATCH_ALIAS,
    MATCH_EXACT_PHRASE,
    AliasInput,
    ManagedObject,
    ObjectChangeRequest,
)
from .paths import RuleManagerPaths
from .service import ObjectRuleManagerService, RuleManagerValidationError


COLORS = {
    "nav": "#17324d",
    "nav_hover": "#244966",
    "accent": "#0f766e",
    "accent_dark": "#0b5f59",
    "background": "#f4f7fa",
    "surface": "#ffffff",
    "border": "#d8e0e8",
    "text": "#1f2937",
    "muted": "#64748b",
    "warning": "#b45309",
    "danger": "#b91c1c",
}

CATALOG_LABEL_TO_KEY = {definition.label: key for key, definition in CATALOG_DEFINITIONS.items()}
CATALOG_KEY_TO_LABEL = {key: definition.label for key, definition in CATALOG_DEFINITIONS.items()}
MATCH_LABEL_TO_KEY = {
    "Cụm từ chính xác": MATCH_EXACT_PHRASE,
    "Alias linh hoạt": MATCH_ALIAS,
}
MATCH_KEY_TO_LABEL = {value: key for key, value in MATCH_LABEL_TO_KEY.items()}


class RuleManagerApp(tk.Tk):
    def __init__(self, project_root: str | Path):
        super().__init__()
        self.paths = RuleManagerPaths.from_project_root(project_root)
        self.service = ObjectRuleManagerService(self.paths)
        self.title("Bank Agent Rule Manager")
        self.geometry("1320x800")
        self.minsize(1120, 680)
        self.configure(bg=COLORS["background"])
        self._configure_styles()
        self._pages: dict[str, ttk.Frame] = {}
        self._nav_buttons: dict[str, tk.Button] = {}
        self._build_shell()
        self._register_pages()
        self.show_page("objects")

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Surface.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Segoe UI Semibold", 18))
        style.configure("Section.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI Semibold", 11))
        style.configure("Muted.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("SurfaceMuted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), foreground="white", background=COLORS["accent"], padding=(14, 8))
        style.map("Accent.TButton", background=[("active", COLORS["accent_dark"]), ("disabled", "#94a3b8")])
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#eaf0f5")
        style.map("Treeview", background=[("selected", "#cceae6")], foreground=[("selected", COLORS["text"])])

    def _build_shell(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.sidebar = tk.Frame(self, width=230, bg=COLORS["nav"])
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        tk.Label(
            self.sidebar,
            text="BANK AGENT",
            bg=COLORS["nav"],
            fg="white",
            font=("Segoe UI Semibold", 17),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(24, 2))
        tk.Label(
            self.sidebar,
            text="Rule Manager",
            bg=COLORS["nav"],
            fg="#a9c2d5",
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill="x", padx=23, pady=(0, 25))

        self.nav_container = tk.Frame(self.sidebar, bg=COLORS["nav"])
        self.nav_container.pack(fill="x")

        bottom = tk.Frame(self.sidebar, bg=COLORS["nav"])
        bottom.pack(side="bottom", fill="x", padx=16, pady=18)
        tk.Button(
            bottom,
            text="Khôi phục backup gần nhất",
            command=self.restore_latest_backup,
            bg="#264b67",
            fg="white",
            activebackground="#315c7d",
            activeforeground="white",
            relief="flat",
            padx=10,
            pady=9,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).pack(fill="x")
        tk.Label(
            bottom,
            text="Độc lập với Power Automate Desktop",
            bg=COLORS["nav"],
            fg="#8eabbf",
            font=("Segoe UI", 8),
            wraplength=190,
        ).pack(fill="x", pady=(12, 0))

        self.content = ttk.Frame(self, padding=(24, 18))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)

        header = ttk.Frame(self.content)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        self.page_title = ttk.Label(header, text="", style="Title.TLabel")
        self.page_title.grid(row=0, column=0, sticky="w")
        self.status_var = tk.StringVar(value="Sẵn sàng")
        ttk.Label(header, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        self.page_host = ttk.Frame(self.content)
        self.page_host.grid(row=1, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

    def _register_pages(self) -> None:
        self.register_page("objects", "Mã đối tượng", lambda parent: ObjectManagementPage(parent, self.service, self.set_status))
        self.register_page("payments", "Loại thanh toán", lambda parent: FutureModulePage(parent, "Loại thanh toán"), enabled=False)
        self.register_page("accounting", "Nghiệp vụ kế toán", lambda parent: FutureModulePage(parent, "Nghiệp vụ kế toán"), enabled=False)

    def register_page(self, key: str, label: str, factory, enabled: bool = True) -> None:
        button = tk.Button(
            self.nav_container,
            text=("  " + label) if enabled else ("  " + label + "  ·  Sắp có"),
            command=(lambda: self.show_page(key)) if enabled else None,
            state="normal" if enabled else "disabled",
            bg=COLORS["nav"],
            disabledforeground="#6f8ca1",
            fg="white",
            activebackground=COLORS["nav_hover"],
            activeforeground="white",
            relief="flat",
            anchor="w",
            padx=18,
            pady=13,
            font=("Segoe UI Semibold" if enabled else "Segoe UI", 10),
            cursor="hand2" if enabled else "arrow",
        )
        button.pack(fill="x", pady=1)
        self._nav_buttons[key] = button
        page = factory(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        self._pages[key] = page

    def show_page(self, key: str) -> None:
        page = self._pages[key]
        page.tkraise()
        labels = {"objects": "Quản lý Mã đối tượng", "payments": "Loại thanh toán", "accounting": "Nghiệp vụ kế toán"}
        self.page_title.configure(text=labels[key])
        for nav_key, button in self._nav_buttons.items():
            if str(button.cget("state")) == "disabled":
                continue
            button.configure(bg=COLORS["nav_hover"] if nav_key == key else COLORS["nav"])
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def set_status(self, message: str) -> None:
        self.status_var.set(message)
        self.update_idletasks()

    def restore_latest_backup(self) -> None:
        backups = sorted((path for path in self.paths.backup_dir.glob("*") if path.is_dir()), reverse=True)
        if not backups:
            messagebox.showinfo("Khôi phục", "Chưa có bản backup nào.", parent=self)
            return
        latest = backups[0]
        if not messagebox.askyesno(
            "Khôi phục backup",
            f"Khôi phục bản backup gần nhất?\n\n{latest.name}\n\nCác file hiện tại bị tác động sẽ được thay bằng bản cũ.",
            parent=self,
        ):
            return
        try:
            safety_backup = self.service.restore_backup(latest)
            self.set_status(f"Đã khôi phục {latest.name}; backup trước restore: {safety_backup.name}")
            page = self._pages.get("objects")
            if page and hasattr(page, "refresh"):
                page.refresh()
            messagebox.showinfo("Hoàn thành", "Đã khôi phục backup gần nhất.", parent=self)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self._show_exception("Không thể khôi phục backup", exc)

    def _show_exception(self, title: str, exc: Exception) -> None:
        self.set_status("Có lỗi")
        messagebox.showerror(title, f"{exc}\n\nChi tiết kỹ thuật:\n{traceback.format_exc(limit=3)}", parent=self)


class FutureModulePage(ttk.Frame):
    def __init__(self, parent, name: str):
        super().__init__(parent)
        card = ttk.Frame(self, style="Surface.TFrame", padding=40)
        card.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(card, text=name, style="Section.TLabel").pack(pady=(0, 8))
        ttk.Label(
            card,
            text="Khung ứng dụng đã sẵn sàng để bổ sung module này ở giai đoạn sau.",
            style="SurfaceMuted.TLabel",
        ).pack()


class ObjectManagementPage(ttk.Frame):
    def __init__(self, parent, service: ObjectRuleManagerService, status_callback):
        super().__init__(parent)
        self.service = service
        self.set_status = status_callback
        self.object_rows: dict[str, ManagedObject] = {}
        self.pending_aliases: list[AliasInput] = []
        self.current_object: ManagedObject | None = None
        self.is_new_object = False
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=4)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Surface.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(left, style="Surface.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Danh mục", style="Surface.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.catalog_var = tk.StringVar(value=CATALOG_KEY_TO_LABEL[CATALOG_PAYABLE])
        self.catalog_combo = ttk.Combobox(
            toolbar,
            textvariable=self.catalog_var,
            values=[definition.label for definition in CATALOG_DEFINITIONS.values()],
            state="readonly",
            width=16,
        )
        self.catalog_combo.grid(row=0, column=1, sticky="w")
        self.catalog_combo.bind("<<ComboboxSelected>>", self._catalog_changed)
        ttk.Button(toolbar, text="Thêm Mã ĐT", command=self.start_new_object).grid(row=0, column=2, sticky="e")

        search = ttk.Frame(left, style="Surface.TFrame")
        search.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        search.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search, textvariable=self.search_var)
        search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        search_entry.bind("<Return>", lambda _event: self._load_object_tree())
        ttk.Button(search, text="Tìm", command=self._load_object_tree).grid(row=0, column=1)

        table_frame = ttk.Frame(left, style="Surface.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.object_tree = ttk.Treeview(
            table_frame,
            columns=("code", "name", "tax", "aliases"),
            show="headings",
            selectmode="browse",
        )
        self.object_tree.heading("code", text="Mã ĐT")
        self.object_tree.heading("name", text="Tên đối tượng")
        self.object_tree.heading("tax", text="MST")
        self.object_tree.heading("aliases", text="Alias")
        self.object_tree.column("code", width=105, minwidth=80)
        self.object_tree.column("name", width=290, minwidth=180)
        self.object_tree.column("tax", width=110, minwidth=80)
        self.object_tree.column("aliases", width=55, minwidth=45, anchor="center")
        self.object_tree.grid(row=0, column=0, sticky="nsew")
        self.object_tree.bind("<<TreeviewSelect>>", self._on_object_selected)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.object_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.object_tree.configure(yscrollcommand=scrollbar.set)

        self.count_var = tk.StringVar(value="0 đối tượng")
        ttk.Label(left, textvariable=self.count_var, style="SurfaceMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))

        right = ttk.Frame(self, style="Surface.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        right.rowconfigure(8, weight=1)
        ttk.Label(right, text="Thông tin Mã đối tượng", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.code_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.tax_var = tk.StringVar()
        self.address_var = tk.StringVar()
        self.confirmed_var = tk.BooleanVar(value=False)
        self._form_entry(right, 1, "Mã ĐT", self.code_var)
        self._form_entry(right, 2, "Tên ĐT", self.name_var)
        self._form_entry(right, 3, "Mã số thuế", self.tax_var)
        self._form_entry(right, 4, "Địa chỉ", self.address_var)
        self.confirmed_check = ttk.Checkbutton(
            right,
            text="Đã tạo Mã ĐT này trong VACOM",
            variable=self.confirmed_var,
        )
        self.confirmed_check.grid(row=5, column=1, sticky="w", pady=(4, 12))

        separator = ttk.Separator(right)
        separator.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(right, text="Alias nhận diện", style="Section.TLabel").grid(row=7, column=0, columnspan=2, sticky="w")

        alias_frame = ttk.Frame(right, style="Surface.TFrame")
        alias_frame.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
        alias_frame.columnconfigure(0, weight=1)
        alias_frame.rowconfigure(0, weight=1)
        self.alias_tree = ttk.Treeview(
            alias_frame,
            columns=("alias", "type", "status", "source"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        for column, label, width in (
            ("alias", "Alias", 210),
            ("type", "Kiểu", 105),
            ("status", "Trạng thái", 80),
            ("source", "Nguồn", 72),
        ):
            self.alias_tree.heading(column, text=label)
            self.alias_tree.column(column, width=width, minwidth=60)
        self.alias_tree.grid(row=0, column=0, sticky="nsew")
        alias_scroll = ttk.Scrollbar(alias_frame, orient="vertical", command=self.alias_tree.yview)
        alias_scroll.grid(row=0, column=1, sticky="ns")
        self.alias_tree.configure(yscrollcommand=alias_scroll.set)

        alias_input = ttk.Frame(right, style="Surface.TFrame")
        alias_input.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(2, 10))
        alias_input.columnconfigure(0, weight=1)
        self.alias_value_var = tk.StringVar()
        alias_entry = ttk.Entry(alias_input, textvariable=self.alias_value_var)
        alias_entry.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        alias_entry.bind("<Return>", lambda _event: self.add_pending_alias())
        self.match_type_var = tk.StringVar(value="Cụm từ chính xác")
        ttk.Combobox(
            alias_input,
            textvariable=self.match_type_var,
            values=list(MATCH_LABEL_TO_KEY),
            state="readonly",
            width=19,
        ).grid(row=0, column=1, padx=(0, 7))
        ttk.Button(alias_input, text="Thêm", command=self.add_pending_alias).grid(row=0, column=2)

        alias_actions = ttk.Frame(right, style="Surface.TFrame")
        alias_actions.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, 13))
        ttk.Button(alias_actions, text="Bỏ alias bản nháp", command=self.remove_pending_alias).pack(side="left")
        ttk.Button(alias_actions, text="Ngừng alias user", command=self.deactivate_selected_alias).pack(side="left", padx=7)

        actions = ttk.Frame(right, style="Surface.TFrame")
        actions.grid(row=11, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="Kiểm tra", command=self.validate_current).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="Áp dụng", style="Accent.TButton", command=self.apply_current).grid(row=0, column=2)
        self._set_master_entry_state("readonly")
        self.confirmed_check.state(["disabled"])

    def _form_entry(self, parent, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label, style="Surface.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        if label == "Mã ĐT":
            self.code_entry = entry
        elif label == "Tên ĐT":
            self.name_entry = entry
        elif label == "Mã số thuế":
            self.tax_entry = entry
        elif label == "Địa chỉ":
            self.address_entry = entry

    @property
    def catalog_key(self) -> str:
        return CATALOG_LABEL_TO_KEY[self.catalog_var.get()]

    def refresh(self) -> None:
        try:
            self.set_status("Đang đọc danh mục...")
            self._load_object_tree()
            self.set_status("Sẵn sàng")
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self.set_status("Không đọc được danh mục")
            messagebox.showerror("Lỗi đọc dữ liệu", str(exc), parent=self)

    def _catalog_changed(self, _event=None) -> None:
        self.current_object = None
        self.is_new_object = False
        self.pending_aliases.clear()
        self.code_var.set("")
        self.name_var.set("")
        self.tax_var.set("")
        self.address_var.set("")
        self.confirmed_var.set(False)
        self._set_master_entry_state("readonly")
        self.confirmed_check.state(["disabled"])
        self.alias_tree.delete(*self.alias_tree.get_children())
        self.refresh()

    def _load_object_tree(self) -> None:
        query = normalize_text(self.search_var.get())
        self.object_rows.clear()
        self.object_tree.delete(*self.object_tree.get_children())
        rows = self.service.list_objects(self.catalog_key)
        visible = 0
        for index, row in enumerate(rows):
            item = row.object
            searchable = normalize_text(f"{item.code} {item.name} {item.tax_code}")
            if query and query not in searchable:
                continue
            iid = f"obj_{index}"
            self.object_rows[iid] = item
            self.object_tree.insert("", "end", iid=iid, values=(item.code, item.name, item.tax_code, row.alias_count))
            visible += 1
        self.count_var.set(f"{visible:,} đối tượng")

    def _on_object_selected(self, _event=None) -> None:
        selection = self.object_tree.selection()
        if not selection:
            return
        item = self.object_rows.get(selection[0])
        if not item:
            return
        self.current_object = item
        self.is_new_object = False
        self.pending_aliases.clear()
        self.code_var.set(item.code)
        self.name_var.set(item.name)
        self.tax_var.set(item.tax_code)
        self.address_var.set(item.address)
        self.confirmed_var.set(True)
        self._set_master_entry_state("readonly")
        self.confirmed_check.state(["disabled"])
        self._load_alias_tree()

    def start_new_object(self) -> None:
        self.object_tree.selection_remove(self.object_tree.selection())
        self.current_object = None
        self.is_new_object = True
        self.pending_aliases.clear()
        self.code_var.set("")
        self.name_var.set("")
        self.tax_var.set("")
        self.address_var.set("")
        self.confirmed_var.set(False)
        self._set_master_entry_state("normal")
        self.confirmed_check.state(["!disabled"])
        self.alias_tree.delete(*self.alias_tree.get_children())
        self.code_entry.focus_set()
        self.set_status(f"Đang thêm Mã ĐT mới vào danh mục {self.catalog_var.get()}")

    def _set_master_entry_state(self, state: str) -> None:
        for entry in (self.code_entry, self.name_entry, self.tax_entry, self.address_entry):
            entry.configure(state=state)

    def _load_alias_tree(self) -> None:
        self.alias_tree.delete(*self.alias_tree.get_children())
        if self.current_object:
            for index, row in enumerate(self.service.aliases_for_object(self.catalog_key, self.current_object.code)):
                source = "User" if row["managed"] else "Cấu hình"
                status = "Đang dùng" if row["active"] else "Đã ngừng"
                self.alias_tree.insert(
                    "",
                    "end",
                    iid=f"existing_{index}",
                    values=(row["alias"], MATCH_KEY_TO_LABEL.get(str(row["match_type"]), row["match_type"]), status, source),
                    tags=("managed",) if row["managed"] else ("base",),
                )
        for index, alias in enumerate(self.pending_aliases):
            self.alias_tree.insert(
                "",
                "end",
                iid=f"pending_{index}",
                values=(alias.value, MATCH_KEY_TO_LABEL[alias.match_type], "Bản nháp", "User"),
                tags=("pending",),
            )

    def add_pending_alias(self) -> None:
        value = self.alias_value_var.get().strip()
        if not value:
            messagebox.showwarning("Alias", "Vui lòng nhập alias.", parent=self)
            return
        if not self.code_var.get().strip():
            messagebox.showwarning("Alias", "Vui lòng chọn hoặc nhập Mã ĐT trước.", parent=self)
            return
        normalized = normalize_text(value)
        visible_aliases = {
            normalize_text(self.alias_tree.item(iid, "values")[0])
            for iid in self.alias_tree.get_children()
        }
        if normalized in visible_aliases:
            messagebox.showwarning("Alias", "Alias này đã có trong danh sách.", parent=self)
            return
        self.pending_aliases.append(AliasInput(value=value, match_type=MATCH_LABEL_TO_KEY[self.match_type_var.get()]))
        self.alias_value_var.set("")
        self._load_alias_tree()

    def remove_pending_alias(self) -> None:
        selection = self.alias_tree.selection()
        if not selection or not selection[0].startswith("pending_"):
            messagebox.showinfo("Alias", "Hãy chọn một alias có trạng thái Bản nháp.", parent=self)
            return
        index = int(selection[0].split("_", 1)[1])
        self.pending_aliases.pop(index)
        self._load_alias_tree()

    def deactivate_selected_alias(self) -> None:
        selection = self.alias_tree.selection()
        if not selection:
            messagebox.showinfo("Alias", "Hãy chọn một alias do user tạo.", parent=self)
            return
        values = self.alias_tree.item(selection[0], "values")
        if len(values) < 4 or values[3] != "User" or values[2] == "Bản nháp":
            messagebox.showinfo("Alias", "Chỉ có thể ngừng alias đã được tạo bằng Rule Manager.", parent=self)
            return
        alias = str(values[0])
        if not messagebox.askyesno("Ngừng alias", f"Ngừng sử dụng alias “{alias}”?", parent=self):
            return
        try:
            result = self.service.deactivate_alias(self.catalog_key, alias)
            self.set_status(f"Đã ngừng alias; backup: {Path(result.backup_dir).name}")
            self._load_alias_tree()
            self._load_object_tree()
        except Exception as exc:  # noqa: BLE001 - UI boundary
            messagebox.showerror("Không thể ngừng alias", str(exc), parent=self)

    def _build_request(self) -> ObjectChangeRequest:
        return ObjectChangeRequest(
            catalog=self.catalog_key,
            code=self.code_var.get().strip(),
            name=self.name_var.get().strip(),
            tax_code=self.tax_var.get().strip(),
            address=self.address_var.get().strip(),
            confirmed_in_vacom=self.confirmed_var.get(),
            aliases=tuple(self.pending_aliases),
        )

    def validate_current(self) -> None:
        try:
            issues = self.service.validate(self._build_request())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kiểm tra thất bại", str(exc), parent=self)
            return
        if not issues:
            messagebox.showinfo("Kết quả kiểm tra", "Dữ liệu hợp lệ và không có cảnh báo.", parent=self)
            return
        errors = [issue.message for issue in issues if issue.severity == "error"]
        warnings = [issue.message for issue in issues if issue.severity == "warning"]
        parts: list[str] = []
        if errors:
            parts.append("LỖI:\n- " + "\n- ".join(errors))
        if warnings:
            parts.append("CẢNH BÁO:\n- " + "\n- ".join(warnings))
        show = messagebox.showerror if errors else messagebox.showwarning
        show("Kết quả kiểm tra", "\n\n".join(parts), parent=self)

    def apply_current(self) -> None:
        request = self._build_request()
        issues = self.service.validate(request)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        warnings = [issue.message for issue in issues if issue.severity == "warning"]
        if errors:
            messagebox.showerror("Không thể áp dụng", "- " + "\n- ".join(errors), parent=self)
            return
        summary = [f"Danh mục: {CATALOG_KEY_TO_LABEL[request.catalog]}", f"Mã ĐT: {request.code}"]
        if self.is_new_object:
            summary.append(f"Tên ĐT: {request.name}")
        summary.append(f"Alias mới: {len(request.aliases)}")
        if warnings:
            summary.append("\nCảnh báo:\n- " + "\n- ".join(warnings))
        summary.append("\nỨng dụng sẽ backup các file cũ trước khi thay đổi.")
        if not messagebox.askyesno("Xác nhận áp dụng", "\n".join(summary), parent=self):
            return
        try:
            self.set_status("Đang backup và cập nhật dữ liệu...")
            result = self.service.apply(request)
            self.pending_aliases.clear()
            self.set_status(f"Đã áp dụng; backup: {Path(result.backup_dir).name}")
            messagebox.showinfo(
                "Hoàn thành",
                f"Đã cập nhật thành công.\n\n"
                f"Mã ĐT mới: {'Có' if result.object_created else 'Không'}\n"
                f"Alias mới: {result.aliases_changed}\n"
                f"Backup: {result.backup_dir}",
                parent=self,
            )
            self.refresh()
            self._select_code(request.code)
        except RuleManagerValidationError as exc:
            messagebox.showerror("Dữ liệu không hợp lệ", "- " + "\n- ".join(issue.message for issue in exc.issues), parent=self)
        except PermissionError as exc:
            self.set_status("File đang bị khóa")
            messagebox.showerror(
                "Không thể ghi file",
                f"Có thể workbook đang được mở trong Excel. Hãy đóng file và thử lại.\n\n{exc}",
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001 - UI boundary
            self.set_status("Cập nhật thất bại; đã khôi phục backup")
            messagebox.showerror("Cập nhật thất bại", f"Các file cũ đã được khôi phục.\n\n{exc}", parent=self)

    def _select_code(self, code: str) -> None:
        code_norm = normalize_text(code)
        for iid, item in self.object_rows.items():
            if normalize_text(item.code) == code_norm:
                self.object_tree.selection_set(iid)
                self.object_tree.focus(iid)
                self.object_tree.see(iid)
                self._on_object_selected()
                return


def run_rule_manager(project_root: str | Path) -> None:
    app = RuleManagerApp(project_root)
    app.mainloop()
