from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from src.normalizer import normalize_text

from .accounting_service import AccountingRuleManagerService
from .accounting_ui import AccountingManagementPage
from .models import (
    CATALOG_DEFINITIONS,
    CATALOG_PAYABLE,
    AliasInput,
    ManagedAlias,
    ManagedObject,
    ObjectChangeRequest,
)
from .paths import RuleManagerPaths
from .payment_service import PaymentRuleManagerService
from .payment_ui import PaymentManagementPage
from .service import ObjectListRow, ObjectRuleManagerService, RuleManagerValidationError


COLORS = {
    "nav": "#17324d",
    "nav_hover": "#244966",
    "accent": "#0f766e",
    "accent_dark": "#0b5f59",
    "background": "#f4f7fa",
    "surface": "#ffffff",
    "text": "#1f2937",
    "muted": "#64748b",
}

CATALOG_LABEL_TO_KEY = {definition.label: key for key, definition in CATALOG_DEFINITIONS.items()}
CATALOG_KEY_TO_LABEL = {key: definition.label for key, definition in CATALOG_DEFINITIONS.items()}


class RuleManagerApp(tk.Tk):
    def __init__(self, project_root: str | Path):
        super().__init__()
        self.paths = RuleManagerPaths.from_project_root(project_root)
        self.service = ObjectRuleManagerService(self.paths)
        self.payment_service = PaymentRuleManagerService(self.paths)
        self.accounting_service = AccountingRuleManagerService(self.paths)
        self.title("Quản lý dữ liệu sao kê")
        self.geometry("1320x800")
        self.minsize(1120, 680)
        self.configure(bg=COLORS["background"])
        self._configure_styles()
        self._pages: dict[str, ttk.Frame] = {}
        self._nav_buttons: dict[str, tk.Button] = {}
        self._current_page_key: str | None = None
        self._build_shell()
        self._register_pages()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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

        sidebar = tk.Frame(self, width=230, bg=COLORS["nav"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        tk.Label(
            sidebar,
            text="QUẢN LÝ DỮ LIỆU\nSAO KÊ",
            bg=COLORS["nav"],
            fg="white",
            font=("Segoe UI Semibold", 16),
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=22, pady=(24, 25))

        self.nav_container = tk.Frame(sidebar, bg=COLORS["nav"])
        self.nav_container.pack(fill="x")

        bottom = tk.Frame(sidebar, bg=COLORS["nav"])
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

        content = ttk.Frame(self, padding=(24, 18))
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        header = ttk.Frame(content)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.page_title = ttk.Label(header, text="", style="Title.TLabel")
        self.page_title.grid(row=0, column=0, sticky="w")

        self.page_host = ttk.Frame(content)
        self.page_host.grid(row=1, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

    def _register_pages(self) -> None:
        self.register_page("objects", "Mã đối tượng", lambda parent: ObjectManagementPage(parent, self.service))
        self.register_page(
            "payments",
            "Loại thanh toán",
            lambda parent: PaymentManagementPage(parent, self.payment_service),
        )
        self.register_page(
            "accounting",
            "Loại tài khoản",
            lambda parent: AccountingManagementPage(parent, self.accounting_service),
        )

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
        if self._current_page_key and self._current_page_key != key:
            current = self._pages[self._current_page_key]
            if getattr(current, "has_pending_changes", lambda: False)():
                if not messagebox.askyesno(
                    "Bỏ thay đổi bản nháp",
                    "Trang hiện tại có thay đổi chưa áp dụng. Bạn có muốn bỏ các thay đổi này?",
                    parent=self,
                ):
                    return
                discard = getattr(current, "discard_pending_changes", None)
                if callable(discard):
                    discard()
        page = self._pages[key]
        page.tkraise()
        self._current_page_key = key
        labels = {
            "objects": "Quản lý Mã đối tượng",
            "payments": "Loại thanh toán",
            "accounting": "Loại tài khoản",
        }
        self.page_title.configure(text=labels[key])
        for nav_key, button in self._nav_buttons.items():
            if str(button.cget("state")) != "disabled":
                button.configure(bg=COLORS["nav_hover"] if nav_key == key else COLORS["nav"])
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def restore_latest_backup(self) -> None:
        backups = sorted((path for path in self.paths.backup_dir.glob("*") if path.is_dir()), reverse=True)
        if not backups:
            messagebox.showinfo("Khôi phục", "Chưa có bản backup nào.", parent=self)
            return
        latest = backups[0]
        if not messagebox.askyesno(
            "Khôi phục backup",
            f"Khôi phục bản backup gần nhất?\n\n{latest.name}\n\nCác file liên quan sẽ được thay bằng bản cũ.",
            parent=self,
        ):
            return
        try:
            self.service.restore_backup(latest)
            for page in self._pages.values():
                refresh = getattr(page, "refresh", None)
                if callable(refresh):
                    refresh()
            messagebox.showinfo("Hoàn thành", "Đã khôi phục backup gần nhất.", parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Không thể khôi phục backup", str(exc), parent=self)

    def _on_close(self) -> None:
        if any(getattr(page, "has_pending_changes", lambda: False)() for page in self._pages.values()):
            if not messagebox.askyesno(
                "Chưa áp dụng thay đổi",
                "Các thay đổi bản nháp chưa được áp dụng. Bạn vẫn muốn đóng cửa sổ?",
                parent=self,
            ):
                return
        self.destroy()


class FutureModulePage(ttk.Frame):
    def __init__(self, parent, name: str):
        super().__init__(parent)
        card = ttk.Frame(self, style="Surface.TFrame", padding=40)
        card.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(card, text=name, style="Section.TLabel").pack(pady=(0, 8))
        ttk.Label(card, text="Chức năng sẽ được bổ sung ở giai đoạn sau.", style="SurfaceMuted.TLabel").pack()


class ObjectManagementPage(ttk.Frame):
    def __init__(self, parent, service: ObjectRuleManagerService):
        super().__init__(parent)
        self.service = service
        self.object_rows: dict[str, ObjectListRow] = {}
        self.persisted_aliases: dict[str, ManagedAlias] = {}
        self.alias_rows: dict[str, ManagedAlias] = {}
        self.pending_aliases: list[AliasInput] = []
        self.pending_changes: dict[str, ManagedAlias] = {}
        self.current_object: ManagedObject | None = None
        self.current_object_row: ObjectListRow | None = None
        self.is_new_object = False
        self.active_catalog_key = CATALOG_PAYABLE
        self._editor: tk.Widget | None = None
        self._suppress_selection = False
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
            columns=("code", "name", "aliases", "status"),
            show="headings",
            selectmode="browse",
        )
        self.object_tree.heading("code", text="Mã ĐT")
        self.object_tree.heading("name", text="Tên đối tượng")
        self.object_tree.heading("aliases", text="Alias")
        self.object_tree.heading("status", text="Trạng thái")
        self.object_tree.column("code", width=110, minwidth=80, stretch=False)
        self.object_tree.column("name", width=350, minwidth=180, stretch=False)
        self.object_tree.column("aliases", width=60, minwidth=45, anchor="center", stretch=False)
        self.object_tree.column("status", width=100, minwidth=85, stretch=False)
        self.object_tree.grid(row=0, column=0, sticky="nsew")
        self.object_tree.bind("<<TreeviewSelect>>", self._on_object_selected)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.object_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.object_tree.xview)
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.object_tree.configure(
            yscrollcommand=scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )

        self.count_var = tk.StringVar(value="0 đối tượng")
        ttk.Label(left, textvariable=self.count_var, style="SurfaceMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))

        right = ttk.Frame(self, style="Surface.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        right.rowconfigure(5, weight=1)
        ttk.Label(right, text="Thông tin Mã đối tượng", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.code_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.code_entry = self._form_entry(right, 1, "Mã ĐT", self.code_var)
        self.name_entry = self._form_entry(right, 2, "Tên ĐT", self.name_var)

        ttk.Separator(right).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 12))
        ttk.Label(right, text="Alias nhận diện", style="Section.TLabel").grid(row=4, column=0, columnspan=2, sticky="w")

        alias_frame = ttk.Frame(right, style="Surface.TFrame")
        alias_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
        alias_frame.columnconfigure(0, weight=1)
        alias_frame.rowconfigure(0, weight=1)
        self.alias_tree = ttk.Treeview(
            alias_frame,
            columns=("alias", "status", "source"),
            show="headings",
            height=9,
            selectmode="browse",
        )
        for column, label, width in (
            ("alias", "Alias", 325),
            ("status", "Trạng thái", 110),
            ("source", "Nguồn", 80),
        ):
            self.alias_tree.heading(column, text=label)
            self.alias_tree.column(column, width=width, minwidth=60, stretch=False)
        self.alias_tree.tag_configure("active", foreground="#166534")
        self.alias_tree.tag_configure("inactive", foreground="#64748b")
        self.alias_tree.tag_configure("new", foreground="#1d4ed8")
        self.alias_tree.tag_configure("edit", foreground="#b45309")
        self.alias_tree.tag_configure("delete", foreground="#b91c1c")
        self.alias_tree.grid(row=0, column=0, sticky="nsew")
        self.alias_tree.bind("<Button-1>", self._begin_inline_edit)
        self.alias_tree.bind("<Button-3>", self._show_alias_menu)
        alias_scroll = ttk.Scrollbar(alias_frame, orient="vertical", command=self.alias_tree.yview)
        alias_scroll.grid(row=0, column=1, sticky="ns")
        alias_horizontal_scroll = ttk.Scrollbar(alias_frame, orient="horizontal", command=self.alias_tree.xview)
        alias_horizontal_scroll.grid(row=1, column=0, sticky="ew")
        self.alias_tree.configure(
            yscrollcommand=alias_scroll.set,
            xscrollcommand=alias_horizontal_scroll.set,
        )

        alias_input = ttk.Frame(right, style="Surface.TFrame")
        alias_input.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(2, 13))
        alias_input.columnconfigure(0, weight=1)
        self.alias_value_var = tk.StringVar()
        alias_entry = ttk.Entry(alias_input, textvariable=self.alias_value_var)
        alias_entry.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        alias_entry.bind("<Return>", lambda _event: self.add_pending_alias())
        ttk.Button(alias_input, text="Thêm", command=self.add_pending_alias).grid(row=0, column=1)

        actions = ttk.Frame(right, style="Surface.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="Áp dụng", style="Accent.TButton", command=self.apply_current).grid(row=0, column=1)
        self.object_toggle_button = ttk.Button(actions, text="Tạm ngưng", command=self.toggle_current_object)
        self.object_toggle_button.grid(row=0, column=2, padx=(7, 0))
        self.object_delete_button = ttk.Button(actions, text="Xóa", command=self.delete_current_object)
        self.object_delete_button.grid(row=0, column=3, padx=(7, 0))
        self._set_master_entry_state("readonly")
        self._set_object_action_state(False)

    @staticmethod
    def _form_entry(parent, row: int, label: str, variable: tk.StringVar) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Surface.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        return entry

    @property
    def catalog_key(self) -> str:
        return CATALOG_LABEL_TO_KEY[self.catalog_var.get()]

    def has_pending_changes(self) -> bool:
        return bool(
            self.pending_aliases
            or self.pending_changes
            or (self.is_new_object and (self.code_var.get().strip() or self.name_var.get().strip()))
        )

    def discard_pending_changes(self) -> None:
        self._clear_draft()
        if self.current_object:
            self.code_var.set(self.current_object.code)
            self.name_var.set(self.current_object.name)
            self._load_alias_tree(reload=True)
        else:
            self.code_var.set("")
            self.name_var.set("")
            self.alias_tree.delete(*self.alias_tree.get_children())
            self.is_new_object = False
            self._set_master_entry_state("readonly")

    def refresh(self) -> None:
        try:
            self._load_object_tree()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Lỗi đọc dữ liệu", str(exc), parent=self)

    def _confirm_discard(self) -> bool:
        return not self.has_pending_changes() or messagebox.askyesno(
            "Bỏ thay đổi bản nháp",
            "Các thay đổi chưa được áp dụng. Bạn có muốn bỏ các thay đổi này?",
            parent=self,
        )

    def _clear_draft(self) -> None:
        self._cancel_inline_edit()
        self.pending_aliases.clear()
        self.pending_changes.clear()
        self.persisted_aliases.clear()
        self.alias_rows.clear()

    def _catalog_changed(self, _event=None) -> None:
        if not self._confirm_discard():
            self.catalog_var.set(CATALOG_KEY_TO_LABEL[self.active_catalog_key])
            return
        self.active_catalog_key = self.catalog_key
        self.current_object = None
        self.current_object_row = None
        self.is_new_object = False
        self._clear_draft()
        self.code_var.set("")
        self.name_var.set("")
        self._set_master_entry_state("readonly")
        self._set_object_action_state(False)
        self.alias_tree.delete(*self.alias_tree.get_children())
        self.refresh()

    def _load_object_tree(self) -> None:
        query = normalize_text(self.search_var.get())
        self.object_rows.clear()
        self.object_tree.delete(*self.object_tree.get_children())
        visible = 0
        for index, row in enumerate(self.service.list_objects(self.catalog_key)):
            item = row.object
            if query and query not in normalize_text(f"{item.code} {item.name}"):
                continue
            iid = f"obj_{index}"
            self.object_rows[iid] = row
            status = "Đang dùng" if row.active else "Tạm ngưng"
            self.object_tree.insert("", "end", iid=iid, values=(item.code, item.name, row.alias_count, status))
            visible += 1
        self.count_var.set(f"{visible:,} đối tượng")

    def _on_object_selected(self, _event=None) -> None:
        if self._suppress_selection:
            return
        selection = self.object_tree.selection()
        if not selection:
            return
        row = self.object_rows.get(selection[0])
        if not row:
            return
        item = row.object
        if self.current_object and normalize_text(self.current_object.code) == normalize_text(item.code) and not self.is_new_object:
            return
        previous = self.current_object
        if not self._confirm_discard():
            if previous:
                self._select_code(previous.code)
            else:
                self._suppress_selection = True
                self.object_tree.selection_remove(self.object_tree.selection())
                self._suppress_selection = False
            return
        self.current_object = item
        self.current_object_row = row
        self.is_new_object = False
        self._clear_draft()
        self.code_var.set(item.code)
        self.name_var.set(item.name)
        self._set_master_entry_state("readonly")
        self._set_object_action_state(True)
        self._load_alias_tree(reload=True)

    def start_new_object(self) -> None:
        if not self._confirm_discard():
            return
        self._suppress_selection = True
        self.object_tree.selection_remove(self.object_tree.selection())
        self._suppress_selection = False
        self.current_object = None
        self.current_object_row = None
        self.is_new_object = True
        self._clear_draft()
        self.code_var.set("")
        self.name_var.set("")
        self._set_master_entry_state("normal")
        self._set_object_action_state(False)
        self.alias_tree.delete(*self.alias_tree.get_children())
        self.code_entry.focus_set()

    def _set_master_entry_state(self, state: str) -> None:
        self.code_entry.configure(state=state)
        self.name_entry.configure(state=state)

    def _set_object_action_state(self, selected: bool) -> None:
        self.object_toggle_button.configure(state="normal" if selected else "disabled")
        deletable = bool(selected and self.current_object_row and self.current_object_row.deletable)
        self.object_delete_button.configure(state="normal" if deletable else "disabled")
        if selected and self.current_object_row:
            self.object_toggle_button.configure(
                text="Tạm ngưng" if self.current_object_row.active else "Kích hoạt"
            )

    def toggle_current_object(self) -> None:
        if not self.current_object or not self.current_object_row:
            return
        active = not self.current_object_row.active
        action = "kích hoạt" if active else "tạm ngưng"
        if not messagebox.askyesno(
            action.capitalize() + " Mã ĐT",
            f"Bạn có chắc muốn {action} Mã ĐT “{self.current_object.code}” không?",
            parent=self,
        ):
            return
        try:
            result = self.service.set_object_active(self.catalog_key, self.current_object.code, active)
            code = self.current_object.code
            messagebox.showinfo(
                "Hoàn thành",
                f"Đã {action} Mã ĐT {code}.\n\nBackup: {result.backup_dir}",
                parent=self,
            )
            self.refresh()
            self._select_code(code)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cập nhật thất bại", f"Dữ liệu cũ đã được khôi phục.\n\n{exc}", parent=self)

    def delete_current_object(self) -> None:
        if not self.current_object or not self.current_object_row or not self.current_object_row.deletable:
            return
        code = self.current_object.code
        if not messagebox.askyesno(
            "Xóa Mã ĐT mới",
            f"Xóa Mã ĐT “{code}” khỏi danh mục local và toàn bộ alias của mã này?",
            parent=self,
        ):
            return
        try:
            result = self.service.delete_object(self.catalog_key, code)
            self.current_object = None
            self.current_object_row = None
            self._clear_draft()
            self.code_var.set("")
            self.name_var.set("")
            self.alias_tree.delete(*self.alias_tree.get_children())
            self._set_object_action_state(False)
            self.refresh()
            messagebox.showinfo(
                "Hoàn thành",
                f"Đã xóa Mã ĐT {code}.\n\nBackup: {result.backup_dir}",
                parent=self,
            )
        except RuleManagerValidationError as exc:
            messagebox.showerror(
                "Không thể xóa",
                "- " + "\n- ".join(issue.message for issue in exc.issues if issue.is_error),
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Xóa thất bại", f"Dữ liệu cũ đã được khôi phục.\n\n{exc}", parent=self)

    def _load_alias_tree(self, reload: bool = False) -> None:
        self._cancel_inline_edit()
        self.alias_tree.delete(*self.alias_tree.get_children())
        self.alias_rows.clear()
        if reload and self.current_object:
            records = self.service.aliases_for_object(self.catalog_key, self.current_object.code)
            self.persisted_aliases = {record.record_id: record for record in records}

        for index, base in enumerate(self.persisted_aliases.values()):
            desired = self.pending_changes.get(base.record_id, base)
            iid = f"alias_{index}"
            self.alias_rows[iid] = desired
            status, tag = self._alias_status(base, desired)
            source = "Người dùng" if desired.source == "user" else "Cấu hình"
            self.alias_tree.insert(
                "",
                "end",
                iid=iid,
                values=(desired.alias, status, source),
                tags=(tag,),
            )
        for index, alias in enumerate(self.pending_aliases):
            self.alias_tree.insert(
                "",
                "end",
                iid=f"new_{index}",
                values=(alias.value, "Chờ thêm", "Người dùng"),
                tags=("new",),
            )

    @staticmethod
    def _alias_status(base: ManagedAlias, desired: ManagedAlias) -> tuple[str, str]:
        if desired.deleted:
            return "Chờ xóa", "delete"
        if base.active and not desired.active:
            return "Chờ tạm ngưng", "edit"
        if not base.active and desired.active:
            return "Chờ kích hoạt", "edit"
        if desired.alias != base.alias or desired.match_type != base.match_type:
            return "Chờ chỉnh sửa", "edit"
        return ("Đang dùng", "active") if desired.active else ("Đã tạm ngưng", "inactive")

    def add_pending_alias(self) -> None:
        value = self.alias_value_var.get().strip()
        if not value:
            messagebox.showwarning("Alias", "Vui lòng nhập alias.", parent=self)
            return
        if not self.code_var.get().strip():
            messagebox.showwarning("Alias", "Vui lòng chọn hoặc nhập Mã ĐT trước.", parent=self)
            return
        if normalize_text(value) in self._visible_aliases():
            messagebox.showwarning("Alias", "Alias này đã có trong danh sách.", parent=self)
            return
        self.pending_aliases.append(AliasInput(value))
        self.alias_value_var.set("")
        self._load_alias_tree()

    def _visible_aliases(self, excluding: str | None = None) -> set[str]:
        return {
            normalize_text(self.alias_tree.item(iid, "values")[0])
            for iid in self.alias_tree.get_children()
            if iid != excluding
        }

    def _show_alias_menu(self, event) -> None:
        iid = self.alias_tree.identify_row(event.y)
        if not iid:
            return
        self.alias_tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=False)
        if iid.startswith("new_"):
            menu.add_command(label="Xóa khỏi bản nháp", command=lambda: self._remove_new_alias(iid))
        else:
            desired = self.alias_rows[iid]
            base = self.persisted_aliases[desired.record_id]
            if desired.deleted:
                menu.add_command(label="Hoàn tác xóa", command=lambda: self._undo_deleted(base))
            elif base.active and not desired.active:
                menu.add_command(label="Hoàn tác tạm ngưng", command=lambda: self._set_alias_active(base, True))
                menu.add_command(label="Xóa", command=lambda: self._delete_alias(base))
            elif not base.active and desired.active:
                menu.add_command(label="Hoàn tác kích hoạt", command=lambda: self._set_alias_active(base, False))
                menu.add_command(label="Xóa", command=lambda: self._delete_alias(base))
            elif desired.active:
                menu.add_command(label="Tạm ngưng", command=lambda: self._set_alias_active(base, False))
                menu.add_command(label="Xóa", command=lambda: self._delete_alias(base))
            else:
                menu.add_command(label="Kích hoạt lại", command=lambda: self._set_alias_active(base, True))
                menu.add_command(label="Xóa", command=lambda: self._delete_alias(base))
        menu.tk_popup(event.x_root, event.y_root)

    def _remove_new_alias(self, iid: str) -> None:
        self.pending_aliases.pop(int(iid.split("_", 1)[1]))
        self._load_alias_tree()

    def _set_alias_active(self, base: ManagedAlias, active: bool) -> None:
        current = self.pending_changes.get(base.record_id, base)
        self._store_change(base, replace(current, active=active, deleted=False))

    def _delete_alias(self, base: ManagedAlias) -> None:
        current = self.pending_changes.get(base.record_id, base)
        self._store_change(base, replace(current, active=False, deleted=True))

    def _undo_deleted(self, base: ManagedAlias) -> None:
        current = self.pending_changes.get(base.record_id, base)
        self._store_change(base, replace(current, active=base.active, deleted=False))

    @staticmethod
    def _alias_signature(record: ManagedAlias) -> tuple[object, ...]:
        return record.alias, record.match_type, record.active, record.deleted

    def _store_change(self, base: ManagedAlias, desired: ManagedAlias) -> None:
        if self._alias_signature(base) == self._alias_signature(desired):
            self.pending_changes.pop(base.record_id, None)
        else:
            self.pending_changes[base.record_id] = desired
        self._load_alias_tree()

    def _begin_inline_edit(self, event) -> None:
        iid = self.alias_tree.identify_row(event.y)
        column = self.alias_tree.identify_column(event.x)
        if not iid or column != "#1":
            return
        if not iid.startswith("new_"):
            desired = self.alias_rows[iid]
            if desired.deleted or not desired.active:
                return
        self.after_idle(lambda: self._open_editor(iid, column))

    def _open_editor(self, iid: str, column: str) -> None:
        self._cancel_inline_edit()
        bbox = self.alias_tree.bbox(iid, column)
        if not bbox:
            return
        x, y, width, height = bbox
        values = self.alias_tree.item(iid, "values")
        variable = tk.StringVar(value=str(values[0]))
        editor: tk.Widget = ttk.Entry(self.alias_tree, textvariable=variable)
        self._editor = editor
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        if isinstance(editor, ttk.Entry):
            editor.select_range(0, "end")
        editor.bind("<Return>", lambda _event: self._commit_inline_edit(iid, column, variable.get()))
        editor.bind("<Escape>", lambda _event: self._cancel_inline_edit())
        editor.bind("<FocusOut>", lambda _event: self._commit_inline_edit(iid, column, variable.get()))

    def _commit_inline_edit(self, iid: str, column: str, raw_value: str) -> None:
        if self._editor is None:
            return
        editor = self._editor
        self._editor = None
        editor.destroy()
        if iid not in self.alias_tree.get_children():
            return
        if iid.startswith("new_"):
            index = int(iid.split("_", 1)[1])
            current = self.pending_aliases[index]
            value = raw_value.strip()
            if not value:
                messagebox.showwarning("Alias", "Alias không được để trống.", parent=self)
                return
            if normalize_text(value) in self._visible_aliases(excluding=iid):
                messagebox.showwarning("Alias", "Alias này đã có trong danh sách.", parent=self)
                return
            self.pending_aliases[index] = AliasInput(value)
            self._load_alias_tree()
            return

        current = self.alias_rows[iid]
        base = self.persisted_aliases[current.record_id]
        value = raw_value.strip()
        if not value:
            messagebox.showwarning("Alias", "Alias không được để trống.", parent=self)
            return
        if normalize_text(value) in self._visible_aliases(excluding=iid):
            messagebox.showwarning("Alias", "Alias này đã có trong danh sách.", parent=self)
            return
        previous = list(current.previous_aliases)
        if normalize_text(value) != normalize_text(current.alias) and current.alias not in previous:
            previous.append(current.alias)
        desired = replace(current, alias=value, previous_aliases=tuple(previous))
        self._store_change(base, desired)

    def _cancel_inline_edit(self) -> None:
        if self._editor is not None:
            editor = self._editor
            self._editor = None
            editor.destroy()

    def _build_request(self) -> ObjectChangeRequest:
        return ObjectChangeRequest(
            catalog=self.catalog_key,
            code=self.code_var.get().strip(),
            name=self.name_var.get().strip(),
            aliases=tuple(self.pending_aliases),
            alias_changes=tuple(self.pending_changes.values()),
        )

    def apply_current(self) -> None:
        request = self._build_request()
        try:
            issues = self.service.validate(request)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Không thể áp dụng", str(exc), parent=self)
            return
        errors = [issue.message for issue in issues if issue.is_error]
        warnings = [issue.message for issue in issues if issue.severity == "warning"]
        if errors:
            messagebox.showerror("Không thể áp dụng", "- " + "\n- ".join(errors), parent=self)
            return
        summary = [
            f"Danh mục: {CATALOG_KEY_TO_LABEL[request.catalog]}",
            f"Mã ĐT: {request.code}",
            f"Số thay đổi alias: {len(request.aliases) + len(request.alias_changes)}",
        ]
        if warnings:
            summary.append("\nCảnh báo:\n- " + "\n- ".join(warnings))
        summary.append("\nCác file hiện tại sẽ được backup trước khi cập nhật.")
        if not messagebox.askyesno("Xác nhận áp dụng", "\n".join(summary), parent=self):
            return
        try:
            result = self.service.apply(request)
            self._clear_draft()
            messagebox.showinfo(
                "Hoàn thành",
                f"Đã cập nhật thành công.\n\n"
                f"Mã ĐT mới: {'Có' if result.object_created else 'Không'}\n"
                f"Alias thay đổi: {result.aliases_changed}\n"
                f"Backup: {result.backup_dir}",
                parent=self,
            )
            self.refresh()
            self._select_code(request.code)
        except RuleManagerValidationError as exc:
            messagebox.showerror(
                "Dữ liệu không hợp lệ",
                "- " + "\n- ".join(issue.message for issue in exc.issues if issue.is_error),
                parent=self,
            )
        except PermissionError as exc:
            messagebox.showerror(
                "Không thể ghi file",
                f"Có thể workbook đang được mở trong Excel. Hãy đóng file và thử lại.\n\n{exc}",
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Cập nhật thất bại",
                f"Các file cũ đã được khôi phục.\n\n{exc}",
                parent=self,
            )

    def _select_code(self, code: str) -> None:
        code_norm = normalize_text(code)
        for iid, row in self.object_rows.items():
            item = row.object
            if normalize_text(item.code) == code_norm:
                self._suppress_selection = True
                self.object_tree.selection_set(iid)
                self.object_tree.focus(iid)
                self.object_tree.see(iid)
                self._suppress_selection = False
                self.current_object = item
                self.current_object_row = row
                self.is_new_object = False
                self.code_var.set(item.code)
                self.name_var.set(item.name)
                self._set_master_entry_state("readonly")
                self._set_object_action_state(True)
                self._load_alias_tree(reload=True)
                return


def run_rule_manager(project_root: str | Path) -> None:
    app = RuleManagerApp(project_root)
    app.mainloop()
