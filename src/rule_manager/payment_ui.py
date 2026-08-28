from __future__ import annotations

from dataclasses import replace
import tkinter as tk
from tkinter import messagebox, ttk

from src.normalizer import normalize_text

from .alias_editor import ManagedAliasEditor
from .payment_models import ManagedPaymentPurpose
from .payment_service import PaymentRuleManagerService, PaymentValidationError


class PaymentManagementPage(ttk.Frame):
    def __init__(self, parent, service: PaymentRuleManagerService):
        super().__init__(parent)
        self.service = service
        self.rows: dict[str, ManagedPaymentPurpose] = {}
        self.current: ManagedPaymentPurpose | None = None
        self.baseline: ManagedPaymentPurpose | None = None
        self.is_new = False
        self._suppress_selection = False
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=4)
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self, style="Surface.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(left, style="Surface.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        search = ttk.Entry(toolbar, textvariable=self.search_var)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        search.bind("<Return>", lambda _event: self._load_tree())
        ttk.Button(toolbar, text="Tìm", command=self._load_tree).grid(row=0, column=1, padx=(0, 7))
        ttk.Button(toolbar, text="Thêm loại thanh toán", command=self.start_new).grid(row=0, column=2)
        table = ttk.Frame(left, style="Surface.TFrame")
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("label", "aliases", "status"), show="headings", selectmode="browse")
        for column, label, width in (("label", "Loại thanh toán", 330), ("aliases", "Alias", 60), ("status", "Trạng thái", 100)):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=55, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.count_var = tk.StringVar(value="0 loại thanh toán")
        ttk.Label(left, textvariable=self.count_var, style="SurfaceMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))

        right = ttk.Frame(self, style="Surface.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        ttk.Label(right, text="Thông tin loại thanh toán", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(right, text="Tên loại thanh toán", style="Surface.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.label_var = tk.StringVar()
        self.label_entry = ttk.Entry(right, textvariable=self.label_var)
        self.label_entry.grid(row=1, column=1, sticky="ew")
        ttk.Label(right, text="Alias nhận diện", style="Section.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(18, 6))
        self.alias_editor = ManagedAliasEditor(right)
        self.alias_editor.grid(row=3, column=0, columnspan=2, sticky="nsew")
        actions = ttk.Frame(right, style="Surface.TFrame")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        self.toggle_button = ttk.Button(actions, text="Tạm ngưng", command=self.toggle_active)
        self.toggle_button.grid(row=0, column=1, padx=(0, 7))
        self.delete_button = ttk.Button(actions, text="Xóa", command=self.delete_current)
        self.delete_button.grid(row=0, column=2, padx=(0, 7))
        self.apply_button = ttk.Button(actions, text="Áp dụng", style="Accent.TButton", command=self.apply_current)
        self.apply_button.grid(row=0, column=3)
        self._set_form_state(False)

    def refresh(self) -> None:
        self._load_tree()

    def has_pending_changes(self) -> bool:
        if self.is_new:
            return bool(self.label_var.get().strip() or self.alias_editor.records())
        if not self.current:
            return False
        return bool(
            self.label_var.get().strip() != self.current.label
            or self.alias_editor.has_changes()
            or self.baseline
            and (self.current.active, self.current.deleted) != (self.baseline.active, self.baseline.deleted)
        )

    def discard_pending_changes(self) -> None:
        if self.baseline:
            self._load_current(self.baseline)
        else:
            self.label_var.set("")
            self.alias_editor.clear()
            self.is_new = False

    def _load_tree(self) -> None:
        query = normalize_text(self.search_var.get())
        self.rows.clear()
        self.tree.delete(*self.tree.get_children())
        visible = 0
        for index, record in enumerate(self.service.list_purposes()):
            if query and query not in normalize_text(record.label):
                continue
            iid = f"payment_{index}"
            self.rows[iid] = record
            status = "Đang dùng" if record.active else "Tạm ngưng"
            self.tree.insert("", "end", iid=iid, values=(record.label, len(record.active_aliases), status))
            visible += 1
        self.count_var.set(f"{visible:,} loại thanh toán")

    def _selected(self, _event=None) -> None:
        if self._suppress_selection:
            return
        selected = self.tree.selection()
        if not selected:
            return
        record = self.rows.get(selected[0])
        if not record:
            return
        if self.current and record.record_id == self.current.record_id and not self.is_new:
            return
        if self.has_pending_changes() and not messagebox.askyesno(
            "Bỏ thay đổi bản nháp",
            "Các thay đổi chưa được áp dụng. Bạn có muốn bỏ các thay đổi này?",
            parent=self,
        ):
            self._restore_selection()
            return
        self._load_current(record)

    def _load_current(self, record: ManagedPaymentPurpose) -> None:
        self.current = record
        self.baseline = record
        self.is_new = False
        self.label_var.set(record.label)
        self.alias_editor.load(record.aliases, editable=True)
        self._set_form_state(True)
        self.toggle_button.configure(text="Tạm ngưng" if record.active else "Kích hoạt")

    def start_new(self) -> None:
        if self.has_pending_changes() and not messagebox.askyesno(
            "Bỏ thay đổi bản nháp",
            "Các thay đổi chưa được áp dụng. Bạn có muốn bỏ các thay đổi này?",
            parent=self,
        ):
            return
        self.current = None
        self.baseline = None
        self.is_new = True
        self.label_var.set("")
        self.alias_editor.clear(editable=True)
        self._set_form_state(True)
        self.toggle_button.configure(state="disabled")
        self.delete_button.configure(state="disabled")
        self.label_entry.focus_set()

    def _set_form_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.label_entry.configure(state=state)
        self.alias_editor.set_editable(enabled)
        self.apply_button.configure(state=state)
        self.toggle_button.configure(state=state)
        self.delete_button.configure(state=state)

    def toggle_active(self) -> None:
        if not self.current:
            return
        self.current = replace(self.current, active=not self.current.active, deleted=False)
        self.toggle_button.configure(text="Tạm ngưng" if self.current.active else "Kích hoạt")

    def delete_current(self) -> None:
        if not self.current:
            return
        if messagebox.askyesno("Xóa loại thanh toán", f"Xóa loại “{self.current.label}”?", parent=self):
            self.current = replace(self.current, active=False, deleted=True)
            self.apply_current()

    def apply_current(self) -> None:
        if self.is_new:
            record = self.service.new_record(self.label_var.get(), self.alias_editor.records())
        elif self.current:
            record = replace(self.current, label=self.label_var.get().strip(), aliases=self.alias_editor.records())
        else:
            return
        issues = self.service.validate(record)
        errors = [item.message for item in issues if item.is_error]
        warnings = [item.message for item in issues if item.severity == "warning"]
        if errors:
            messagebox.showerror("Không thể áp dụng", "- " + "\n- ".join(errors), parent=self)
            return
        summary = [f"Loại thanh toán: {record.label}", f"Alias đang dùng: {len(record.active_aliases)}"]
        if warnings:
            summary.append("\nCảnh báo:\n- " + "\n- ".join(warnings))
        if not messagebox.askyesno("Xác nhận áp dụng", "\n".join(summary), parent=self):
            return
        try:
            result = self.service.apply(record)
            messagebox.showinfo("Hoàn thành", f"Đã cập nhật loại thanh toán.\n\nBackup: {result.backup_dir}", parent=self)
            self.current = record
            self.baseline = record
            self.is_new = False
            self._load_tree()
            self._select_code(record.code)
        except PaymentValidationError as exc:
            messagebox.showerror("Dữ liệu không hợp lệ", "- " + "\n- ".join(item.message for item in exc.issues if item.is_error), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cập nhật thất bại", f"Dữ liệu cũ đã được khôi phục.\n\n{exc}", parent=self)

    def _select_code(self, code: str) -> None:
        for iid, record in self.rows.items():
            if record.code != code:
                continue
            self._suppress_selection = True
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self._suppress_selection = False
            self._load_current(record)
            return

    def _restore_selection(self) -> None:
        if not self.baseline:
            self._suppress_selection = True
            self.tree.selection_remove(self.tree.selection())
            self._suppress_selection = False
            return
        for iid, record in self.rows.items():
            if record.record_id == self.baseline.record_id:
                self._suppress_selection = True
                self.tree.selection_set(iid)
                self._suppress_selection = False
                return
