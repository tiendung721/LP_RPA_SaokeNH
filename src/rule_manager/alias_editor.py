from __future__ import annotations

from dataclasses import replace
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Iterable

from src.normalizer import normalize_text

from .simple_alias import ManagedTextAlias


class ManagedAliasEditor(ttk.Frame):
    """Small draft editor shared by payment and accounting pages."""

    def __init__(self, parent, on_change: Callable[[], None] | None = None):
        super().__init__(parent, style="Surface.TFrame")
        self.on_change = on_change or (lambda: None)
        self._records: list[ManagedTextAlias] = []
        self._baseline: tuple[tuple[object, ...], ...] = ()
        self._baseline_ids: set[str] = set()
        self._editable = True
        self._editor: ttk.Entry | None = None
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frame = ttk.Frame(self, style="Surface.TFrame")
        frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            frame,
            columns=("alias", "status", "source"),
            show="headings",
            selectmode="browse",
            height=9,
        )
        for column, label, width in (
            ("alias", "Alias", 330),
            ("status", "Trạng thái", 115),
            ("source", "Nguồn", 85),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=60, stretch=False)
        self.tree.tag_configure("active", foreground="#166534")
        self.tree.tag_configure("inactive", foreground="#64748b")
        self.tree.tag_configure("delete", foreground="#b91c1c")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Button-1>", self._begin_edit)
        self.tree.bind("<Button-3>", self._show_menu)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        input_row = ttk.Frame(self, style="Surface.TFrame")
        input_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        input_row.columnconfigure(0, weight=1)
        self.input_var = tk.StringVar()
        self.input_entry = ttk.Entry(input_row, textvariable=self.input_var)
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        self.input_entry.bind("<Return>", lambda _event: self.add())
        self.add_button = ttk.Button(input_row, text="Thêm", command=self.add)
        self.add_button.grid(row=0, column=1)

    def load(self, records: Iterable[ManagedTextAlias], editable: bool = True) -> None:
        self._cancel_editor()
        self._records = list(records)
        self._baseline = self._signature(self._records)
        self._baseline_ids = {record.record_id for record in self._records}
        self.set_editable(editable)
        self._render()

    def clear(self, editable: bool = True) -> None:
        self.load((), editable=editable)

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        state = "normal" if editable else "disabled"
        self.input_entry.configure(state=state)
        self.add_button.configure(state=state)

    def records(self) -> tuple[ManagedTextAlias, ...]:
        return tuple(self._records)

    def has_changes(self) -> bool:
        return self._signature(self._records) != self._baseline

    def add(self) -> None:
        if not self._editable:
            return
        value = self.input_var.get().strip()
        if not value:
            messagebox.showwarning("Alias", "Vui lòng nhập alias.", parent=self)
            return
        if normalize_text(value) in self._visible_values():
            messagebox.showwarning("Alias", "Alias này đã có trong danh sách.", parent=self)
            return
        self._records.append(ManagedTextAlias.new_user(value))
        self.input_var.set("")
        self._changed()

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self._records):
            if record.deleted:
                status, tag = "Chờ xóa", "delete"
            elif record.active:
                status, tag = "Đang dùng", "active"
            else:
                status, tag = "Tạm ngưng", "inactive"
            source = "Người dùng" if record.source == "user" else "Cấu hình"
            self.tree.insert("", "end", iid=f"alias_{index}", values=(record.value, status, source), tags=(tag,))

    def _show_menu(self, event) -> None:
        if not self._editable:
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        index = int(iid.split("_", 1)[1])
        record = self._records[index]
        menu = tk.Menu(self, tearoff=False)
        if record.deleted:
            menu.add_command(label="Hoàn tác xóa", command=lambda: self._replace(index, replace(record, deleted=False, active=True)))
        elif record.active:
            menu.add_command(label="Tạm ngưng", command=lambda: self._replace(index, replace(record, active=False)))
            menu.add_command(label="Xóa", command=lambda: self._delete(index))
        else:
            menu.add_command(label="Kích hoạt lại", command=lambda: self._replace(index, replace(record, active=True, deleted=False)))
            menu.add_command(label="Xóa", command=lambda: self._delete(index))
        menu.tk_popup(event.x_root, event.y_root)

    def _delete(self, index: int) -> None:
        record = self._records[index]
        # A never-published draft can disappear entirely; persisted/config records keep a tombstone.
        if record.record_id not in self._baseline_ids:
            self._records.pop(index)
            self._changed()
            return
        self._replace(index, replace(record, active=False, deleted=True))

    def _replace(self, index: int, record: ManagedTextAlias) -> None:
        self._records[index] = record
        self._changed()

    def _begin_edit(self, event) -> None:
        if not self._editable or self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        index = int(iid.split("_", 1)[1])
        record = self._records[index]
        if record.deleted or not record.active:
            return
        self.after_idle(lambda: self._open_editor(iid, index))

    def _open_editor(self, iid: str, index: int) -> None:
        self._cancel_editor()
        bbox = self.tree.bbox(iid, "#1")
        if not bbox:
            return
        x, y, width, height = bbox
        variable = tk.StringVar(value=self._records[index].value)
        editor = ttk.Entry(self.tree, textvariable=variable)
        self._editor = editor
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.select_range(0, "end")
        editor.bind("<Return>", lambda _event: self._commit_edit(index, variable.get()))
        editor.bind("<Escape>", lambda _event: self._cancel_editor())
        editor.bind("<FocusOut>", lambda _event: self._commit_edit(index, variable.get()))

    def _commit_edit(self, index: int, raw_value: str) -> None:
        if self._editor is None:
            return
        self._cancel_editor()
        value = raw_value.strip()
        if not value:
            messagebox.showwarning("Alias", "Alias không được để trống.", parent=self)
            return
        current = self._records[index]
        if normalize_text(value) != normalize_text(current.value) and normalize_text(value) in self._visible_values(index):
            messagebox.showwarning("Alias", "Alias này đã có trong danh sách.", parent=self)
            return
        previous = list(current.previous_values)
        if normalize_text(value) != normalize_text(current.value) and current.value not in previous:
            previous.append(current.value)
        self._replace(index, replace(current, value=value, previous_values=tuple(previous)))

    def _cancel_editor(self) -> None:
        if self._editor is not None:
            editor = self._editor
            self._editor = None
            editor.destroy()

    def _visible_values(self, excluding: int | None = None) -> set[str]:
        return {
            normalize_text(record.value)
            for index, record in enumerate(self._records)
            if index != excluding and not record.deleted
        }

    def _changed(self) -> None:
        self._render()
        self.on_change()

    @staticmethod
    def _signature(records: Iterable[ManagedTextAlias]) -> tuple[tuple[object, ...], ...]:
        return tuple((item.record_id, item.value, item.active, item.deleted, item.previous_values) for item in records)
