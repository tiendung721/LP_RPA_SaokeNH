from __future__ import annotations

from dataclasses import replace
import tkinter as tk
from tkinter import messagebox, ttk

from src.normalizer import normalize_text

from .accounting_models import CASH_FLOWS, FLOW_LABELS, AccountingRuleView, ManagedAccountingRule
from .accounting_service import AccountingRuleManagerService, AccountingValidationError
from .alias_editor import ManagedAliasEditor


LABEL_TO_FLOW = {label: key for key, label in FLOW_LABELS.items()}


class AccountingManagementPage(ttk.Frame):
    def __init__(self, parent, service: AccountingRuleManagerService):
        super().__init__(parent)
        self.service = service
        self.rows: dict[str, AccountingRuleView] = {}
        self.current: AccountingRuleView | None = None
        self.baseline: AccountingRuleView | None = None
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
        left.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(left, style="Surface.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        search = ttk.Entry(toolbar, textvariable=self.search_var)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        search.bind("<Return>", lambda _event: self._load_tree())
        ttk.Button(toolbar, text="Tìm", command=self._load_tree).grid(row=0, column=1, padx=(0, 7))
        ttk.Button(toolbar, text="Thêm nghiệp vụ", command=self.start_new).grid(row=0, column=2)
        filters = ttk.Frame(left, style="Surface.TFrame")
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(filters, text="Luồng", style="Surface.TLabel").grid(row=0, column=0, padx=(0, 7))
        self.filter_flow_var = tk.StringVar(value="Tất cả")
        filter_combo = ttk.Combobox(
            filters,
            textvariable=self.filter_flow_var,
            values=("Tất cả", *FLOW_LABELS.values()),
            state="readonly",
            width=16,
        )
        filter_combo.grid(row=0, column=1, sticky="w")
        filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._load_tree())

        table = ttk.Frame(left, style="Surface.TFrame")
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            columns=("use_case", "account", "flow", "aliases", "status", "source"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("use_case", "Nghiệp vụ", 270),
            ("account", "Tài khoản", 75),
            ("flow", "Luồng", 105),
            ("aliases", "Alias", 50),
            ("status", "Trạng thái", 90),
            ("source", "Nguồn", 70),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=45, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.count_var = tk.StringVar(value="0 nghiệp vụ")
        ttk.Label(left, textvariable=self.count_var, style="SurfaceMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))

        right = ttk.Frame(self, style="Surface.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(1, weight=1)
        right.rowconfigure(6, weight=1)
        ttk.Label(right, text="Thông tin nghiệp vụ kế toán", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.source_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.source_var, style="SurfaceMuted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.use_case_var = tk.StringVar()
        self.account_var = tk.StringVar()
        self.flow_var = tk.StringVar(value=FLOW_LABELS["bao_no"])
        ttk.Label(right, text="Tên nghiệp vụ", style="Surface.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=4)
        self.use_case_entry = ttk.Entry(right, textvariable=self.use_case_var)
        self.use_case_entry.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Tài khoản", style="Surface.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=4)
        self.account_entry = ttk.Entry(right, textvariable=self.account_var)
        self.account_entry.grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Label(right, text="Luồng", style="Surface.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=4)
        self.flow_combo = ttk.Combobox(right, textvariable=self.flow_var, values=tuple(FLOW_LABELS.values()), state="readonly")
        self.flow_combo.grid(row=4, column=1, sticky="ew", pady=4)
        self.flow_combo.bind("<<ComboboxSelected>>", self._flow_changed)
        ttk.Label(right, text="Alias nhận diện từ ND CK", style="Section.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(16, 6))
        self.alias_editor = ManagedAliasEditor(right)
        self.alias_editor.grid(row=6, column=0, columnspan=2, sticky="nsew")
        actions = ttk.Frame(right, style="Surface.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
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
            return bool(self.use_case_var.get().strip() or self.account_var.get().strip() or self.alias_editor.records())
        if not self.current or not self.current.editable:
            return False
        return bool(
            self.use_case_var.get().strip() != self.current.use_case
            or self.account_var.get().strip() != self.current.account
            or LABEL_TO_FLOW.get(self.flow_var.get(), "") != self.current.flow
            or self.alias_editor.has_changes()
            or self.baseline
            and (self.current.active, self.current.deleted) != (self.baseline.active, self.baseline.deleted)
        )

    def discard_pending_changes(self) -> None:
        if self.baseline:
            self._load_current(self.baseline)
        else:
            self._clear_form()

    def _load_tree(self) -> None:
        query = normalize_text(self.search_var.get())
        selected_flow = LABEL_TO_FLOW.get(self.filter_flow_var.get(), "")
        self.rows.clear()
        self.tree.delete(*self.tree.get_children())
        visible = 0
        for index, record in enumerate(self.service.list_rules()):
            if selected_flow and record.flow != selected_flow:
                continue
            if query and query not in normalize_text(f"{record.use_case} {record.account}"):
                continue
            iid = f"accounting_{index}"
            self.rows[iid] = record
            source = "Tự tạo" if record.editable else "Có sẵn"
            status = "Đang dùng" if record.active else "Tạm ngưng"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    record.use_case,
                    record.account,
                    FLOW_LABELS.get(record.flow, record.flow),
                    len(record.active_aliases),
                    status,
                    source,
                ),
            )
            visible += 1
        self.count_var.set(f"{visible:,} nghiệp vụ")

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

    def _load_current(self, record: AccountingRuleView) -> None:
        self.current = record
        self.baseline = record
        self.is_new = False
        self.use_case_var.set(record.use_case)
        self.account_var.set(record.account)
        self.flow_var.set(FLOW_LABELS.get(record.flow, record.flow))
        self.source_var.set("Nghiệp vụ tự tạo — có thể chỉnh sửa" if record.editable else "Nghiệp vụ có sẵn — chỉ xem")
        self.alias_editor.load(record.aliases, editable=record.editable)
        self._set_form_state(record.editable)
        self.toggle_button.configure(text="Tạm ngưng" if record.active else "Kích hoạt", state="normal")
        if record.editable:
            self._flow_changed()

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
        self.use_case_var.set("")
        self.account_var.set("")
        self.flow_var.set(FLOW_LABELS["bao_no"])
        self.source_var.set("Nghiệp vụ tự tạo mới")
        self.alias_editor.clear(editable=True)
        self._set_form_state(True)
        self.toggle_button.configure(state="disabled")
        self.delete_button.configure(state="disabled")
        self.use_case_entry.focus_set()

    def _clear_form(self) -> None:
        self.current = None
        self.baseline = None
        self.is_new = False
        self.use_case_var.set("")
        self.account_var.set("")
        self.source_var.set("")
        self.alias_editor.clear(editable=False)
        self._set_form_state(False)

    def _set_form_state(self, editable: bool) -> None:
        state = "normal" if editable else "disabled"
        self.use_case_entry.configure(state=state)
        self.account_entry.configure(state=state)
        self.flow_combo.configure(state="readonly" if editable else "disabled")
        self.alias_editor.set_editable(editable)
        self.apply_button.configure(state=state)
        self.toggle_button.configure(state="normal" if self.current else "disabled")
        self.delete_button.configure(state=state)

    def _flow_changed(self, _event=None) -> None:
        if not (self.is_new or self.current and self.current.editable):
            return
        flow = LABEL_TO_FLOW.get(self.flow_var.get(), "")
        if flow in CASH_FLOWS:
            self.account_var.set("1111")
            self.account_entry.configure(state="readonly")
        else:
            self.account_entry.configure(state="normal")

    def toggle_active(self) -> None:
        if not self.current:
            return
        active = not self.current.active
        action = "kích hoạt" if active else "tạm ngưng"
        if not messagebox.askyesno(
            action.capitalize() + " loại tài khoản",
            f"Bạn có chắc muốn {action} “{self.current.use_case}” không?",
            parent=self,
        ):
            return
        try:
            result = self.service.set_active(self.current, active)
            rule_id = self.current.rule_id
            messagebox.showinfo(
                "Hoàn thành",
                f"Đã {action} loại tài khoản.\n\nBackup: {result.backup_dir}",
                parent=self,
            )
            self._load_tree()
            self._select_rule(rule_id)
        except AccountingValidationError as exc:
            messagebox.showerror(
                "Không thể cập nhật",
                "- " + "\n- ".join(item.message for item in exc.issues if item.is_error),
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cập nhật thất bại", f"Dữ liệu cũ đã được khôi phục.\n\n{exc}", parent=self)

    def delete_current(self) -> None:
        if not isinstance(self.current, ManagedAccountingRule) or not self.current.editable:
            return
        if messagebox.askyesno("Xóa nghiệp vụ", f"Xóa nghiệp vụ “{self.current.use_case}”?", parent=self):
            self.current = replace(self.current, active=False, deleted=True)
            self.apply_current()

    def apply_current(self) -> None:
        flow = LABEL_TO_FLOW.get(self.flow_var.get(), "")
        if self.is_new:
            record = self.service.new_record(
                self.use_case_var.get(), self.account_var.get(), flow, self.alias_editor.records()
            )
        elif isinstance(self.current, ManagedAccountingRule):
            record = replace(
                self.current,
                use_case=self.use_case_var.get().strip(),
                account=self.account_var.get().strip(),
                flow=flow,
                aliases=self.alias_editor.records(),
            )
        else:
            return
        issues = self.service.validate(record)
        errors = [item.message for item in issues if item.is_error]
        warnings = [item.message for item in issues if item.severity == "warning"]
        if errors:
            messagebox.showerror("Không thể áp dụng", "- " + "\n- ".join(errors), parent=self)
            return
        summary = [
            f"Nghiệp vụ: {record.use_case}",
            f"Tài khoản: {record.account}",
            f"Luồng: {FLOW_LABELS.get(record.flow, record.flow)}",
            f"Alias đang dùng: {len(record.active_aliases)}",
        ]
        if warnings:
            summary.append("\nCảnh báo:\n- " + "\n- ".join(warnings))
        if not messagebox.askyesno("Xác nhận áp dụng", "\n".join(summary), parent=self):
            return
        try:
            result = self.service.apply(record)
            messagebox.showinfo("Hoàn thành", f"Đã cập nhật nghiệp vụ.\n\nBackup: {result.backup_dir}", parent=self)
            self.current = record
            self.baseline = record
            self.is_new = False
            self._load_tree()
            self._select_rule(record.rule_id)
        except AccountingValidationError as exc:
            messagebox.showerror("Dữ liệu không hợp lệ", "- " + "\n- ".join(item.message for item in exc.issues if item.is_error), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cập nhật thất bại", f"Dữ liệu cũ đã được khôi phục.\n\n{exc}", parent=self)

    def _select_rule(self, rule_id: str) -> None:
        for iid, record in self.rows.items():
            if record.rule_id != rule_id:
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
