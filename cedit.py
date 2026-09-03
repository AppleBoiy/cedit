#!/usr/bin/env python3
"""
cedit - multi-game save editor
===============================

("cedit", from "c-save-game-editor")

A generic GUI save editor whose game-specific knowledge (save file
locations, parsing quirks, quick-edit fields, binary field decoding) lives
entirely in per-game "profiles" under games/. The editor itself is 100%
generic - adding a new game means adding a new games/<name>.py, nothing in
this file needs to change.

Built on PySide6 (Qt for Python), not Tkinter - see README.txt for why:
short version, Tk on macOS depends on whatever Tcl/Tk Homebrew resolves to,
and Tcl/Tk 9.0's Aqua rendering has real performance problems on macOS as of
early 2026 that aren't fixable from application code. PySide6 ships its own
Qt build via a normal `pip install`, sidestepping that whole situation.

Folder layout:
  games/  - one module per game, each exposing a `PROFILE = GameProfile(...)`
  lib/    - shared plugin contract/utilities (lib/base.py) and any game's
            own parsing library too unusual to be config-driven
            (lib/octopath_lib.py)
  data/   - per-game data/config files (data/duckov.json,
            data/octopath/*.json)

Currently registered games:
  - Escape from Duckov (games/duckov.py, data/duckov.json)
  - Octopath Traveler / II (games/octopath.py, lib/octopath_lib.py)
  - DREDGE (games/dredge.py, lib/dredge_client.py) - opens its own window,
    see GameProfile.custom_launcher

Add more by dropping in a new games/<name>.py (see lib/base.py for the
GameProfile contract) and registering it in games/__init__.py.

Requires: pip install PySide6

Run:
  python3 cedit.py
  python3 cedit.py --game duckov /path/to/Save_1.sav
"""

import argparse
import copy
import csv
import datetime
import json
import os
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from games import get_game, list_games
from lib.base import (
    MAIN_WINDOW_MIN,
    MAIN_WINDOW_SIZE,
    atomic_write_bytes,
    atomic_write_text,
    backup_file,
    coerce_value,
    get_by_path,
    guess_type,
    set_by_path,
    smart_parse,
)


def _resource_path(*parts):
    """Resolve a path that works both running from source and from a
    PyInstaller-built app bundle (which unpacks bundled data under
    sys._MEIPASS instead of next to this script)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def _read_version():
    """The VERSION file at the repo root (or bundled alongside the frozen
    app via packaging/cedit.spec's datas) - the single source of truth
    also used for packaging/cedit.spec and packaging/cedit_cli.spec's own
    CFBundleShortVersionString/--version output, so there's one place to
    bump per release rather than several that can drift out of sync.
    "dev" if it's missing entirely (e.g. a stripped-down checkout) rather
    than crashing the whole app over a cosmetic detail."""
    try:
        with open(_resource_path("VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "dev"


APP_TITLE = "cedit"
APP_VERSION = _read_version()

# QSettings organization/app name pair - identifies where recent-files
# (and any future preferences) get stored via Qt's native per-OS
# mechanism (e.g. ~/Library/Preferences/... plist on macOS).
_SETTINGS_ORG = "cedit"
_SETTINGS_APP = "cedit"
_RECENT_FILES_LIMIT = 10

# QTreeWidgetItem data role used to mark a still-unexpanded lazy placeholder
# child (see the "tree building" section below).
_LAZY_ROLE = Qt.UserRole + 1


def _qt_filter_string(file_patterns):
    """[(label, glob), ...] -> Qt's "label (glob);;label2 (glob2)" filter
    string. A glob may itself be several space-separated patterns
    (e.g. "*.sav *.json *.ES3"), which Qt's filter syntax already accepts
    as-is."""
    return ";;".join(f"{label} ({glob})" for label, glob in file_patterns)



class DictTableDialog(QDialog):
    """Spreadsheet-style view for a dictionary container (e.g. Resources, Header, etc.).
    Shows Key, Description/Name hint, Value, and Type. Allows live editing, filtering,
    sorting, breadcrumb drill-down, CSV export/import, and batch multi-row editing."""

    def __init__(self, parent_window, dict_value: dict, profile, title="Dictionary", path_stack=None):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.profile = profile
        self.dict_value = dict_value
        self.dirty = False
        self.show_internal = False
        self.path_stack = list(path_stack) if path_stack else [title.split()[0]]
        self.setWindowTitle(title)
        self.resize(880, 580)

        layout = QVBoxLayout(self)

        # Top bar: Breadcrumbs & Filter
        top = QHBoxLayout()
        bc_text = " ❯ ".join(self.path_stack)
        bc_label = QLabel(f"<b>Path:</b> <span style='color: #2b78e4;'>{bc_text}</span>")
        top.addWidget(bc_label)
        top.addStretch(1)

        top.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search keys, descriptions, values...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit)

        self.internal_check = QCheckBox("Show internal (_) keys")
        self.internal_check.toggled.connect(self._toggle_internal)
        top.addWidget(self.internal_check)
        layout.addLayout(top)

        # Main Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Key", "Description / Name", "Value", "Type"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.table, stretch=1)

        # Bottom bar: CSV Tools & Close
        bot = QHBoxLayout()
        exp_btn = QPushButton("Export CSV...")
        exp_btn.clicked.connect(self._export_csv)
        bot.addWidget(exp_btn)

        imp_btn = QPushButton("Import CSV...")
        imp_btn.clicked.connect(self._import_csv)
        bot.addWidget(imp_btn)

        bot.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bot.addWidget(close_btn)
        layout.addLayout(bot)

        self._keys = []
        self._populate()

    def _toggle_internal(self, checked):
        self.show_internal = checked
        self._populate()

    def _populate(self):
        self.table.blockSignals(True)
        raw_keys = list(self.dict_value.keys())
        if not self.show_internal:
            self._keys = [k for k in raw_keys if not str(k).startswith("_")]
        else:
            self._keys = raw_keys

        self.table.setRowCount(len(self._keys))
        for row, k in enumerate(self._keys):
            val = self.dict_value[k]
            # Column 0: Key
            k_cell = QTableWidgetItem(str(k))
            k_cell.setFlags(k_cell.flags() & ~Qt.ItemIsEditable)
            k_cell.setData(Qt.UserRole, k)
            self.table.setItem(row, 0, k_cell)

            # Column 1: Description / Hint
            desc = None
            if self.profile.describe_entry:
                try:
                    desc = self.profile.describe_entry(self.windowTitle().split()[0], k, val)
                except Exception:
                    desc = None
            desc_cell = QTableWidgetItem(str(desc) if desc else "")
            desc_cell.setFlags(desc_cell.flags() & ~Qt.ItemIsEditable)
            desc_cell.setForeground(Qt.darkGray)
            self.table.setItem(row, 1, desc_cell)

            # Column 2: Value
            if isinstance(val, (dict, list)):
                v_text = f"{{{len(val)} keys}}" if isinstance(val, dict) else f"[{len(val)} items]"
                v_cell = QTableWidgetItem(v_text)
                v_cell.setFlags(v_cell.flags() & ~Qt.ItemIsEditable)
                v_cell.setForeground(QColor("#2b78e4"))
                v_cell.setToolTip("Double-click to inspect nested table...")
            else:
                v_cell = QTableWidgetItem(str(val) if val is not None else "")
                if self.profile.is_read_only(self.dict_value, k, val) or str(k).startswith("_"):
                    v_cell.setFlags(v_cell.flags() & ~Qt.ItemIsEditable)
            v_cell.setData(Qt.UserRole, k)
            self.table.setItem(row, 2, v_cell)

            # Column 3: Type
            t_cell = QTableWidgetItem(type(val).__name__)
            t_cell.setFlags(t_cell.flags() & ~Qt.ItemIsEditable)
            t_cell.setForeground(Qt.gray)
            self.table.setItem(row, 3, t_cell)

        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        self._apply_filter(self.filter_edit.text())

    def _apply_filter(self, text: str):
        query = text.strip().lower()
        for row in range(self.table.rowCount()):
            if not query:
                self.table.setRowHidden(row, False)
                continue
            k_text = self.table.item(row, 0).text().lower()
            desc_text = self.table.item(row, 1).text().lower()
            v_text = self.table.item(row, 2).text().lower()
            match = query in k_text or query in desc_text or query in v_text
            self.table.setRowHidden(row, not match)

    def _on_item_changed(self, cell):
        if cell.column() != 2:
            return
        key = cell.data(Qt.UserRole)
        if key is None or key not in self.dict_value:
            return
        old_val = self.dict_value[key]
        if isinstance(old_val, (dict, list)):
            return
        new_text = cell.text().strip()
        try:
            if isinstance(old_val, bool):
                new_val = new_text.lower() in ("1", "true", "yes")
            elif isinstance(old_val, int):
                new_val = int(float(new_text))
            elif isinstance(old_val, float):
                new_val = float(new_text)
            else:
                new_val = new_text
            self.dict_value[key] = new_val
            self.dirty = True
        except Exception:
            cell.setText(str(old_val))

    def _on_item_double_clicked(self, cell):
        row = cell.row()
        key_cell = self.table.item(row, 0)
        if not key_cell:
            return
        key = key_cell.data(Qt.UserRole)
        if key is None or key not in self.dict_value:
            return
        val = self.dict_value[key]
        sub_stack = self.path_stack + [str(key)]
        if isinstance(val, dict):
            dialog = DictTableDialog(self, val, self.profile, title=f"{key} ({len(val)} entries)", path_stack=sub_stack)
            dialog.exec()
            if dialog.dirty:
                self.dirty = True
                self._populate()
        elif isinstance(val, list):
            dialog = ListTableDialog(self, val, self.profile, title=f"{key} ({len(val)} items)", path_stack=sub_stack)
            dialog.exec()
            if dialog.dirty:
                self.dirty = True
                self._populate()

    def _show_context_menu(self, pos):
        selected_rows = sorted(list(set(item.row() for item in self.table.selectedItems())))
        if not selected_rows:
            return
        menu = QMenu(self)
        s_suffix = "s" if len(selected_rows) > 1 else ""
        count_label = f"Selected {len(selected_rows)} row{s_suffix}"
        info_act = menu.addAction(count_label)
        info_act.setEnabled(False)
        menu.addSeparator()

        set_val_act = menu.addAction("Set Value for Selected...")
        add_num_act = menu.addAction("Add / Subtract Number...")
        zero_act = menu.addAction("Zero Out Selected (Set to 0)")

        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == set_val_act:
            text, ok = QInputDialog.getText(self, "Batch Set Value", f"Enter new value for {len(selected_rows)} items:")
            if ok and text is not None:
                for r in selected_rows:
                    k = self.table.item(r, 0).data(Qt.UserRole)
                    if k in self.dict_value and not isinstance(self.dict_value[k], (dict, list)):
                        old = self.dict_value[k]
                        try:
                            if isinstance(old, bool):
                                val = text.lower() in ("1", "true", "yes")
                            elif isinstance(old, int):
                                val = int(float(text))
                            elif isinstance(old, float):
                                val = float(text)
                            else:
                                val = text
                            self.dict_value[k] = val
                            self.dirty = True
                        except Exception:
                            pass
                self._populate()

        elif act == add_num_act:
            delta, ok = QInputDialog.getInt(self, "Add / Subtract Number", "Enter amount to add (positive or negative):", 0, -9999999, 9999999)
            if ok:
                for r in selected_rows:
                    k = self.table.item(r, 0).data(Qt.UserRole)
                    if k in self.dict_value and isinstance(self.dict_value[k], (int, float)):
                        self.dict_value[k] += delta
                        self.dirty = True
                self._populate()

        elif act == zero_act:
            for r in selected_rows:
                k = self.table.item(r, 0).data(Qt.UserRole)
                if k in self.dict_value and isinstance(self.dict_value[k], (int, float)):
                    self.dict_value[k] = 0
                    self.dirty = True
            self._populate()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Table to CSV", "", "CSV Files (*.csv);;All Files (*.*)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Key", "Description", "Value", "Type"])
                for k in self._keys:
                    val = self.dict_value[k]
                    desc = None
                    if self.profile.describe_entry:
                        try:
                            desc = self.profile.describe_entry(self.windowTitle().split()[0], k, val)
                        except Exception:
                            desc = None
                    writer.writerow([str(k), str(desc or ""), str(val), type(val).__name__])
            QMessageBox.information(self, "Export CSV", f"Successfully exported table to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV: {e}")

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Values from CSV", "", "CSV Files (*.csv);;All Files (*.*)")
        if not path:
            return
        try:
            updated = 0
            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header row
                for row in reader:
                    if len(row) >= 3:
                        k, _, v_str = row[0], row[1], row[2]
                        # Match key in dict
                        matching_k = None
                        for ek in self.dict_value:
                            if str(ek) == k:
                                matching_k = ek
                                break
                        if matching_k is not None:
                            old = self.dict_value[matching_k]
                            if not isinstance(old, (dict, list)):
                                try:
                                    if isinstance(old, bool):
                                        nv = v_str.lower() in ("1", "true", "yes")
                                    elif isinstance(old, int):
                                        nv = int(float(v_str))
                                    elif isinstance(old, float):
                                        nv = float(v_str)
                                    else:
                                        nv = v_str
                                    self.dict_value[matching_k] = nv
                                    updated += 1
                                    self.dirty = True
                                except Exception:
                                    pass
            self._populate()
            QMessageBox.information(self, "Import CSV", f"Successfully updated {updated} entries from CSV.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import CSV: {e}")


class ListTableDialog(QDialog):
    """Spreadsheet-style view for a list whose items are dicts or primitives.
    Shows index, fields as columns, allows live editing, filtering, sorting,
    breadcrumbs, CSV export/import, and batch multi-row operations."""

    def __init__(self, parent_window, list_value, profile, title="List", path_stack=None):
        super().__init__(parent_window)
        self.profile = profile
        self.list_value = list_value
        self.dirty = False
        self.show_internal = False
        self.path_stack = list(path_stack) if path_stack else [title.split()[0]]
        self.setWindowTitle(title)
        self.resize(960, 580)

        layout = QVBoxLayout(self)

        # Top bar: Breadcrumbs & Filter
        top = QHBoxLayout()
        bc_text = " ❯ ".join(self.path_stack)
        bc_label = QLabel(f"<b>Path:</b> <span style='color: #2b78e4;'>{bc_text}</span>")
        top.addWidget(bc_label)
        top.addStretch(1)

        top.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter rows...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit)

        self.internal_check = QCheckBox("Show internal (_) fields")
        self.internal_check.toggled.connect(self._toggle_internal)
        top.addWidget(self.internal_check)

        if not profile.binary:
            add_btn = QPushButton("Add Row")
            add_btn.clicked.connect(self._add_row)
            top.addWidget(add_btn)
            del_btn = QPushButton("Delete Row")
            del_btn.clicked.connect(self._delete_row)
            top.addWidget(del_btn)
        layout.addLayout(top)

        self.columns = self._compute_columns()
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns) + 1)
        self.table.setHorizontalHeaderLabels(["#"] + self.columns)
        self.table.horizontalHeader().setMaximumSectionSize(260)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.table, stretch=1)

        # Bottom bar: CSV Tools & Close
        bot = QHBoxLayout()
        exp_btn = QPushButton("Export CSV...")
        exp_btn.clicked.connect(self._export_csv)
        bot.addWidget(exp_btn)

        imp_btn = QPushButton("Import CSV...")
        imp_btn.clicked.connect(self._import_csv)
        bot.addWidget(imp_btn)

        bot.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bot.addWidget(close_btn)
        layout.addLayout(bot)

        self._populate()

    def _compute_columns(self):
        columns = []
        seen = set()
        has_scalar = False
        for item in self.list_value:
            if isinstance(item, dict):
                for k in item:
                    if k not in seen and (self.show_internal or not str(k).startswith("_")):
                        seen.add(k)
                        columns.append(k)
            else:
                has_scalar = True
        if has_scalar:
            columns.append("(value)")
        return columns

    def _toggle_internal(self, checked):
        self.show_internal = checked
        self.columns = self._compute_columns()
        self.table.setColumnCount(len(self.columns) + 1)
        self.table.setHorizontalHeaderLabels(["#"] + self.columns)
        self._populate()

    def _populate(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.list_value))
        for row, item in enumerate(self.list_value):
            index_cell = QTableWidgetItem(str(row))
            index_cell.setFlags(index_cell.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, index_cell)
            for col, key in enumerate(self.columns, start=1):
                cell = self._make_cell(row, item, key)
                self.table.setItem(row, col, cell)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

    @staticmethod
    def _display_for(value):
        if isinstance(value, dict):
            return f"{{{len(value)} keys}}"
        if isinstance(value, list):
            return f"[{len(value)} items]"
        return ListTableDialog._short(value)

    def _make_cell(self, row, item, key):
        if isinstance(item, dict):
            if key == "(value)" or key not in item:
                cell = QTableWidgetItem("")
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                return cell
            value = item[key]
            special = self.profile.find_special_node(item, key, value)
            try:
                display = special.decode(item, key, value) if special else value
            except Exception:
                display = value
            if isinstance(display, (dict, list)):
                cell = QTableWidgetItem(self._display_for(display))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                cell.setForeground(QColor("#2b78e4"))
                cell.setToolTip("Double-click to inspect nested table...")
                cell.setData(Qt.UserRole + 1, (row, key))
                return cell
            cell = QTableWidgetItem(self._short(display))
            if self.profile.is_read_only(item, key, value) or str(key).startswith("_"):
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            cell.setData(Qt.UserRole, (row, key))
            return cell
        if key == "(value)":
            cell = QTableWidgetItem(self._short(item))
            cell.setData(Qt.UserRole, (row, None))
            return cell
        cell = QTableWidgetItem("")
        cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
        return cell

    @staticmethod
    def _short(value):
        s = str(value)
        return s if len(s) <= 200 else s[:197] + "..."

    def _on_item_double_clicked(self, cell):
        payload = cell.data(Qt.UserRole + 1)
        if not payload:
            return
        row_index, key = payload
        item = self.list_value[row_index]
        value = item.get(key)
        sub_stack = self.path_stack + [f"[{row_index}]", str(key)]
        if isinstance(value, dict):
            dialog = DictTableDialog(self, value, self.profile, title=f"{key} ({len(value)} entries)", path_stack=sub_stack)
            dialog.exec()
            if dialog.dirty:
                self.dirty = True
                self._populate()
        elif isinstance(value, list):
            dialog = ListTableDialog(self, value, self.profile, title=f"{key} ({len(value)} items)", path_stack=sub_stack)
            dialog.exec()
            if dialog.dirty:
                self.dirty = True
                self._populate()

    def _on_item_changed(self, cell):
        col = cell.column()
        if col == 0:
            return
        payload = cell.data(Qt.UserRole)
        if not payload:
            return
        row_index, key = payload
        item = self.list_value[row_index]
        new_text = cell.text().strip()
        if key is None:
            old_value = item
            target_obj = self.list_value
            target_key = row_index
        else:
            old_value = item.get(key)
            target_obj = item
            target_key = key
        special = self.profile.find_special_node(item, key, old_value) if key is not None else None
        try:
            if special:
                coerced = special.encode(new_text, old_value)
            elif isinstance(old_value, bool):
                coerced = new_text.lower() in ("1", "true", "yes")
            elif isinstance(old_value, int):
                coerced = int(float(new_text))
            elif isinstance(old_value, float):
                coerced = float(new_text)
            else:
                coerced = new_text
            target_obj[target_key] = coerced
            self.dirty = True
        except Exception:
            cell.setText(self._short(old_value))

    def _apply_filter(self, text):
        query = text.strip().lower()
        for row in range(self.table.rowCount()):
            if not query:
                self.table.setRowHidden(row, False)
                continue
            row_text = " ".join(
                self.table.item(row, col).text().lower()
                for col in range(self.table.columnCount())
                if self.table.item(row, col)
            )
            self.table.setRowHidden(row, query not in row_text)

    def _add_row(self):
        if self.columns and self.columns != ["(value)"]:
            new_item = {k: 0 for k in self.columns if k != "(value)"}
        else:
            new_item = ""
        self.list_value.append(new_item)
        self.dirty = True
        self._populate()
        self.table.scrollToBottom()

    def _delete_row(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.list_value):
            return
        del self.list_value[row]
        self.dirty = True
        self._populate()

    def _show_context_menu(self, pos):
        selected_rows = sorted(list(set(item.row() for item in self.table.selectedItems())))
        if not selected_rows:
            return
        menu = QMenu(self)
        s_suffix = "s" if len(selected_rows) > 1 else ""
        count_label = f"Selected {len(selected_rows)} row{s_suffix}"
        info_act = menu.addAction(count_label)
        info_act.setEnabled(False)
        menu.addSeparator()

        del_act = menu.addAction("Delete Selected Rows")
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == del_act:
            for r in reversed(selected_rows):
                if 0 <= r < len(self.list_value):
                    del self.list_value[r]
            self.dirty = True
            self._populate()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Table to CSV", "", "CSV Files (*.csv);;All Files (*.*)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["#"] + self.columns)
                for row_idx, item in enumerate(self.list_value):
                    row_data = [str(row_idx)]
                    for col_key in self.columns:
                        if isinstance(item, dict):
                            v = item.get(col_key, "")
                        else:
                            v = item if col_key == "(value)" else ""
                        row_data.append(str(v))
                    writer.writerow(row_data)
            QMessageBox.information(self, "Export CSV", f"Successfully exported table to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV: {e}")

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Rows from CSV", "", "CSV Files (*.csv);;All Files (*.*)")
        if not path:
            return
        try:
            updated = 0
            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header or len(header) < 2:
                    return
                col_keys = header[1:]
                for row in reader:
                    if len(row) >= 2:
                        try:
                            idx = int(row[0])
                            if 0 <= idx < len(self.list_value):
                                item = self.list_value[idx]
                                for c_idx, k in enumerate(col_keys):
                                    if c_idx + 1 < len(row) and isinstance(item, dict) and k in item:
                                        raw_v = row[c_idx + 1]
                                        old = item[k]
                                        if isinstance(old, bool):
                                            item[k] = raw_v.lower() in ("1", "true", "yes")
                                        elif isinstance(old, int):
                                            item[k] = int(float(raw_v))
                                        elif isinstance(old, float):
                                            item[k] = float(raw_v)
                                        else:
                                            item[k] = raw_v
                                updated += 1
                                self.dirty = True
                        except Exception:
                            pass
            self._populate()
            QMessageBox.information(self, "Import CSV", f"Successfully imported {updated} rows from CSV.")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import CSV: {e}")


class _DiscoveredSavesDialog(QDialog):
    """Lists save files found by GameProfile.discover_saves() (most
    recently modified first) so opening a save doesn't require knowing/
    navigating to wherever the game actually nested it - the same idea as
    DREDGE's own "Discover Saves..." dialog, generalized to any
    config-driven game via file_patterns + default_save_dirs."""

    def __init__(self, parent_window, paths):
        super().__init__(parent_window)
        self.setWindowTitle("Discovered saves")
        self.resize(720, 360)
        self.chosen_path = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Most recently modified first:"))
        self.listw = QListWidget()
        for p in paths:
            self.listw.addItem(QListWidgetItem(p))
        if paths:
            self.listw.setCurrentRow(0)
        self.listw.itemDoubleClicked.connect(lambda *a: self._confirm())
        layout.addWidget(self.listw)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._confirm)
        button_row.addWidget(open_btn)
        layout.addLayout(button_row)

    def _confirm(self):
        item = self.listw.currentItem()
        if item is not None:
            self.chosen_path = item.text()
            self.accept()


class SearchResultsDialog(QDialog):
    """Every match for a search query, listed at once, instead of stepping
    through them one "Find Next" click at a time - useful the moment a
    query has more than a couple of hits (which key had that value again?
    how many places mention this id?). Non-modal and reused across
    searches: stays open so you can jump to one result, look at it in the
    tree, then come back and try another."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Search Results")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        self.results = QTreeWidget()
        self.results.setColumnCount(2)
        self.results.setHeaderLabels(["Key", "Value"])
        self.results.setColumnWidth(0, 320)
        self.results.itemDoubleClicked.connect(self._jump_to_current)
        layout.addWidget(self.results, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        jump_btn = QPushButton("Jump to Selected")
        jump_btn.clicked.connect(self._jump_to_current)
        button_row.addWidget(jump_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def show_results(self, query, matches):
        """matches: list of (path, key_text, value_text)."""
        self.results.clear()
        for path, key_text, value_text in matches:
            item = QTreeWidgetItem([key_text, value_text])
            item.setData(0, Qt.UserRole, path)
            self.results.addTopLevelItem(item)
        count = len(matches)
        self.summary_label.setText(
            f"{count} match{'es' if count != 1 else ''} for '{query}'" if count
            else f"No matches for '{query}'"
        )
        if count:
            self.results.setCurrentItem(self.results.topLevelItem(0))

    def _jump_to_current(self):
        item = self.results.currentItem()
        if item is None:
            return
        path = item.data(0, Qt.UserRole)
        node = self.main_window._ensure_node_for_path(path)
        if node is None:
            return
        self.main_window._reveal(node)
        self.main_window.tree.setCurrentItem(node)
        self.main_window.tree.scrollToItem(node)


class ItemCatalogPickerDialog(QDialog):
    """A searchable picker over a GameProfile's item_catalog() (see
    lib/base.py), so the Inventory Editor window's "Browse Catalog..."
    button doesn't ask for a raw item id typed from memory. Same pattern as
    games/dredge.py's own _CatalogPickerDialog, generalized here since it's
    not tied to DREDGE's own footprint/size columns."""

    def __init__(self, parent, rows, title="Choose an item"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 480)
        self._rows = rows  # [(name, id_str), ...]
        self.chosen_id = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self._populate)
        layout.addWidget(self.search_edit)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Name", "ID"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *a: self._confirm())
        layout.addWidget(self.tree, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        choose_btn = QPushButton("Choose")
        choose_btn.clicked.connect(self._confirm)
        button_row.addWidget(choose_btn)
        layout.addLayout(button_row)

        self._populate("")
        self.search_edit.setFocus()

    def _populate(self, filter_text):
        self.tree.clear()
        needle = filter_text.strip().lower()
        for name, item_id in self._rows:
            if needle and needle not in name.lower() and needle not in item_id.lower():
                continue
            self.tree.addTopLevelItem(QTreeWidgetItem([name, item_id]))

    def _confirm(self):
        item = self.tree.currentItem()
        if item is not None:
            self.chosen_id = item.text(1)
            self.accept()


class InventoryEditorWindow(QMainWindow):
    """Edit > Inventory Editor... - a dedicated full window (matching the
    visual weight of games/dredge.py's own window) for any game profile
    that defines all four of spawn_item_targets/spawn_item/inventory_state/
    remove_inventory_item (see lib/base.py). Shows a container picker, a
    visual grid of occupied/free slots (colored via GameProfile
    .inventory_state()), a side list of the occupied slots' item ids, and
    Spawn/Remove buttons wired to GameProfile.spawn_item()/
    remove_inventory_item() with the same pre-snapshot-then-push-undo
    convention as the rest of the generic editor - so Undo/Redo cover
    everything done through this window too.

    Type ids show a looked-up display name too, wherever the profile's
    describe_entry hook (see lib/base.py) recognizes one - grid cells show
    the bare id (a name usually won't fit in one small cell) with the name
    in a hover tooltip, the occupied-slots list has its own Name column,
    and typing an id into the spawn field previews its name live. If the
    profile also sets item_catalog, a "Browse Catalog..." button opens a
    searchable picker (ItemCatalogPickerDialog) over every named item
    instead of requiring an id typed from memory - that button just stays
    hidden for a profile without one. A game with no catalog at all just
    shows raw ids everywhere - nothing here ever fabricates or guesses a
    name.
    """

    GRID_COLUMNS = 10
    CELL_SIZE = 64
    EXTRA_EMPTY_SLOTS = 20  # shown after the last occupied one, when capacity is unknown
    WINDOW_SIZE = (860, 600)
    WINDOW_MIN = (680, 460)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Inventory Editor")
        self.resize(*self.WINDOW_SIZE)
        self.setMinimumSize(*self.WINDOW_MIN)

        self._state = None  # last inventory_state() result, for click/remove lookups
        self._slots_by_position = {}  # grid position -> slot dict, for the current container

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Container:"))
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self.refresh)
        top_row.addWidget(self.target_combo, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(refresh_btn)
        root.addLayout(top_row)

        self.capacity_label = QLabel("")
        self.capacity_label.setWordWrap(True)
        root.addWidget(self.capacity_label)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        grid_box = QGroupBox("Slots (click a cell to select it)")
        grid_box_layout = QVBoxLayout(grid_box)
        grid_box_layout.setAlignment(Qt.AlignTop)
        self.grid_table = QTableWidget()
        self.grid_table.setColumnCount(self.GRID_COLUMNS)
        self.grid_table.horizontalHeader().setVisible(False)
        self.grid_table.verticalHeader().setVisible(False)
        self.grid_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid_table.setShowGrid(True)
        # Fixed, not Expanding - a small backpack grid shouldn't stretch to
        # fill however wide this window happens to be; that just leaves a
        # big blank rectangle instead of keeping the cells a sensible size.
        # The exact size is set once per render, in _render_grid(), since it
        # depends on how many rows this particular container needs.
        self.grid_table.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.grid_table.itemSelectionChanged.connect(self._on_grid_selection_changed)
        grid_box_layout.addWidget(self.grid_table, 0, Qt.AlignLeft | Qt.AlignTop)
        splitter.addWidget(grid_box)

        list_box = QGroupBox("Occupied slots")
        list_layout = QVBoxLayout(list_box)
        self.item_table = QTableWidget()
        self.item_table.setColumnCount(4)
        self.item_table.setHorizontalHeaderLabels(["Position", "Type ID", "Name", "Instance ID"])
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.item_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.item_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.item_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.item_table.itemSelectionChanged.connect(self._on_item_selection_changed)
        list_layout.addWidget(self.item_table)
        splitter.addWidget(list_box)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("Item type id:"))
        self.item_id_edit = QLineEdit()
        self.item_id_edit.setPlaceholderText("e.g. 594")
        self.item_id_edit.setFixedWidth(140)
        self.item_id_edit.textChanged.connect(self._update_item_id_preview)
        form_row.addWidget(self.item_id_edit)
        self.browse_catalog_btn = QPushButton("Browse Catalog...")
        self.browse_catalog_btn.clicked.connect(self._browse_catalog)
        self.browse_catalog_btn.setVisible(self.main_window.profile.item_catalog is not None)
        form_row.addWidget(self.browse_catalog_btn)
        self.item_id_preview_label = QLabel("")
        self.item_id_preview_label.setStyleSheet("color: palette(mid);")
        form_row.addWidget(self.item_id_preview_label, 1)
        form_row.addWidget(QLabel("Quantity:"))
        self.quantity_edit = QLineEdit("1")
        self.quantity_edit.setFixedWidth(50)
        form_row.addWidget(self.quantity_edit)
        root.addLayout(form_row)

        button_row = QHBoxLayout()
        self.spawn_btn = QPushButton("Spawn Into Selected Slot")
        self.spawn_btn.clicked.connect(self._spawn)
        button_row.addWidget(self.spawn_btn)
        self.remove_btn = QPushButton("Remove Selected Item")
        self.remove_btn.clicked.connect(self._remove)
        self.remove_btn.setEnabled(False)
        button_row.addWidget(self.remove_btn)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self._reload_targets()

    # ---------------------------------------------------------------- data

    def _reload_targets(self):
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        targets = []
        if self.main_window.data is not None and self.main_window.profile.spawn_item_targets:
            try:
                targets = self.main_window.profile.spawn_item_targets(self.main_window.data)
            except Exception:
                targets = []
        for label, key in targets:
            self.target_combo.addItem(label, key)
        self.target_combo.blockSignals(False)
        self.refresh()

    def refresh(self):
        """Re-read inventory_state() for the current container and redraw
        both the grid and the item list. Safe to call any time (after an
        edit, an undo/redo, a reload, or opening this window) - it never
        assumes the previously selected container still exists."""
        self._state = None
        self._slots_by_position = {}
        target_key = self.target_combo.currentData()
        profile = self.main_window.profile
        if (
            target_key is None
            or self.main_window.data is None
            or profile.inventory_state is None
        ):
            self.grid_table.setRowCount(0)
            self.item_table.setRowCount(0)
            self.capacity_label.setText("No container selected.")
            self.remove_btn.setEnabled(False)
            return

        try:
            state = profile.inventory_state(self.main_window.data, target_key)
        except ValueError as e:
            self.grid_table.setRowCount(0)
            self.item_table.setRowCount(0)
            self.capacity_label.setText(f"Couldn't read this container: {e}")
            self.remove_btn.setEnabled(False)
            return

        self._state = state
        capacity = state.get("capacity")
        slots = state.get("slots", [])
        note = state.get("capacity_note")

        if capacity is not None:
            self.capacity_label.setText(f"Capacity: {len(slots)} / {capacity} used.")
            total_cells = max(capacity, len(slots))
        else:
            base = f"Occupied: {len(slots)} (no fixed capacity for this container)."
            self.capacity_label.setText(f"{base}  {note}" if note else base)
            total_cells = len(slots) + self.EXTRA_EMPTY_SLOTS

        self._render_grid(slots, total_cells)
        self._render_item_list(slots)
        self.remove_btn.setEnabled(False)

    def _render_grid(self, slots, total_cells):
        occupied_by_position = {s["position"]: s for s in slots if s.get("position") is not None}
        columns = min(self.GRID_COLUMNS, max(1, total_cells))
        rows = max(1, (total_cells + columns - 1) // columns)
        self.grid_table.setColumnCount(columns)
        self.grid_table.setRowCount(rows)
        for row in range(rows):
            self.grid_table.setRowHeight(row, self.CELL_SIZE)
        for col in range(columns):
            self.grid_table.setColumnWidth(col, self.CELL_SIZE)
        # Fixed size policy (set in __init__) needs an explicit size to
        # actually take effect - +2 covers the outer frame border so the
        # last row/column isn't clipped.
        self.grid_table.setFixedSize(columns * self.CELL_SIZE + 2, rows * self.CELL_SIZE + 2)

        self._slots_by_position = {}
        for position in range(total_cells):
            row, col = divmod(position, columns)
            slot = occupied_by_position.get(position)
            cell = QTableWidgetItem()
            cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            cell.setTextAlignment(Qt.AlignCenter)
            if slot is not None:
                type_id = slot.get("type_id")
                name = self._type_name(type_id)
                # The cell itself just shows the id - it's guaranteed to
                # fit, unlike most item names. The full name (where known)
                # shows on hover, and always in the Occupied Slots list.
                cell.setText(str(type_id) if type_id is not None else "?")
                cell.setToolTip(f"type {type_id}" + (f"\n{name}" if name else ""))
                cell.setBackground(QColor("#4a7a4a"))
                cell.setData(Qt.UserRole, position)
                self._slots_by_position[position] = slot
            else:
                cell.setText("")
                cell.setToolTip("Empty - select, then Spawn Into Selected Slot")
                cell.setBackground(QColor("#3a3a3a"))
                cell.setData(Qt.UserRole, position)
            self.grid_table.setItem(row, col, cell)

    def _render_item_list(self, slots):
        self.item_table.setRowCount(len(slots))
        for row, slot in enumerate(slots):
            type_id = slot.get("type_id")
            self.item_table.setItem(row, 0, QTableWidgetItem(str(slot.get("position"))))
            self.item_table.setItem(row, 1, QTableWidgetItem(str(type_id)))
            self.item_table.setItem(row, 2, QTableWidgetItem(self._type_name(type_id) or ""))
            self.item_table.setItem(row, 3, QTableWidgetItem(str(slot.get("instance_id"))))
            self.item_table.item(row, 0).setData(Qt.UserRole, slot.get("instance_id"))

    def _type_name(self, type_id):
        """Looked-up display name for a type id via the profile's generic
        describe_entry hook (see lib/base.py) - reused here rather than a
        separate name-lookup hook, since it's exactly the same
        "typeID -> optional name" lookup describe_entry already does for
        the tree view. None if the profile has no such hook, or it doesn't
        know this id."""
        profile = self.main_window.profile
        if profile.describe_entry is None or type_id is None:
            return None
        try:
            return profile.describe_entry(None, "typeID", type_id)
        except Exception:
            return None

    def _browse_catalog(self):
        profile = self.main_window.profile
        if profile.item_catalog is None:
            return
        try:
            rows = profile.item_catalog(self.main_window.data)
        except Exception as e:
            QMessageBox.critical(self, "Inventory Editor", f"Couldn't load the item catalog:\n{e}")
            return
        if not rows:
            QMessageBox.information(self, "Inventory Editor", "The item catalog is empty.")
            return
        dialog = ItemCatalogPickerDialog(self, rows, title="Choose an item to spawn")
        if dialog.exec() == QDialog.Accepted and dialog.chosen_id is not None:
            self.item_id_edit.setText(str(dialog.chosen_id))

    def _update_item_id_preview(self, text):
        text = text.strip()
        if not text:
            self.item_id_preview_label.setText("")
            return
        try:
            type_id = int(text)
        except ValueError:
            self.item_id_preview_label.setText("(not a whole number)")
            return
        name = self._type_name(type_id)
        self.item_id_preview_label.setText(f"→ {name}" if name else "(no known name for this id)")

    # ----------------------------------------------------------- selection

    def _on_grid_selection_changed(self):
        items = self.grid_table.selectedItems()
        if not items:
            self.remove_btn.setEnabled(False)
            return
        position = items[0].data(Qt.UserRole)
        slot = self._slots_by_position.get(position)
        self.remove_btn.setEnabled(slot is not None)

    def _on_item_selection_changed(self):
        self.remove_btn.setEnabled(bool(self.item_table.selectedItems()))

    def _selected_empty_position(self):
        items = self.grid_table.selectedItems()
        if not items:
            return None
        position = items[0].data(Qt.UserRole)
        if position in self._slots_by_position:
            return None  # occupied - spawn_item() picks its own free position anyway
        return position

    def _selected_instance_id(self):
        grid_items = self.grid_table.selectedItems()
        if grid_items:
            slot = self._slots_by_position.get(grid_items[0].data(Qt.UserRole))
            if slot is not None:
                return slot.get("instance_id")
        list_items = self.item_table.selectedItems()
        if list_items:
            row = list_items[0].row()
            cell = self.item_table.item(row, 0)
            if cell is not None:
                return cell.data(Qt.UserRole)
        return None

    # --------------------------------------------------------------- edits

    def _spawn(self):
        profile = self.main_window.profile
        target_key = self.target_combo.currentData()
        if profile.spawn_item is None or target_key is None or self.main_window.data is None:
            return
        try:
            item_id = int(self.item_id_edit.text().strip())
            quantity = int(self.quantity_edit.text().strip())
        except ValueError:
            QMessageBox.critical(self, "Inventory Editor", "Item type id and quantity must both be whole numbers.")
            return

        # Snapshot before calling spawn_item, not after - spawn_item is
        # required to raise before mutating anything on invalid input, so
        # there's simply nothing to snapshot yet if it fails.
        pre_spawn_snapshot = self.main_window._snapshot()
        try:
            message = profile.spawn_item(self.main_window.data, target_key, item_id, quantity)
        except ValueError as e:
            QMessageBox.critical(self, "Inventory Editor", f"Couldn't spawn item:\n{e}")
            return
        self.main_window._push_undo(pre_spawn_snapshot)
        self.main_window.rebuild_tree()
        self.main_window.refresh_raw_from_tree()
        self.main_window.refresh_quick_edit()
        self.main_window._set_dirty(True)
        self.main_window._set_status(message)
        self.status_label.setText(message)
        self.refresh()

    def _remove(self):
        profile = self.main_window.profile
        target_key = self.target_combo.currentData()
        instance_id = self._selected_instance_id()
        if profile.remove_inventory_item is None or target_key is None or instance_id is None:
            return
        if QMessageBox.question(
            self, "Inventory Editor", f"Remove item (instance {instance_id})? (You can Undo this.)"
        ) != QMessageBox.Yes:
            return

        pre_remove_snapshot = self.main_window._snapshot()
        try:
            message = profile.remove_inventory_item(self.main_window.data, target_key, instance_id)
        except ValueError as e:
            QMessageBox.critical(self, "Inventory Editor", f"Couldn't remove item:\n{e}")
            return
        self.main_window._push_undo(pre_remove_snapshot)
        self.main_window.rebuild_tree()
        self.main_window.refresh_raw_from_tree()
        self.main_window.refresh_quick_edit()
        self.main_window._set_dirty(True)
        self.main_window._set_status(message)
        self.status_label.setText(message)
        self.refresh()

    def closeEvent(self, event):
        self.main_window._inventory_editor_window = None
        super().closeEvent(event)

    def values(self):
        """(target_key, item_id, quantity) - only meaningful after accept()."""
        return self._target_key, self._item_id, self._quantity



class BackupManagerDialog(QDialog):
    """
    Snapshot & Backup Manager. Lists timestamped .bak files for the current save,
    allowing 1-click snapshot creation, backup restoration, and inspection.
    """
    def __init__(self, parent_window, save_path: str):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.save_path = save_path
        self.setWindowTitle(f"Backup & Snapshot Manager - {os.path.basename(save_path)}")
        self.resize(750, 480)
        from lib.base import backup_file, list_backups, restore_backup
        self.list_backups = list_backups
        self.backup_file = backup_file
        self.restore_backup = restore_backup
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info_label = QLabel(
            "<b>Save File Backups & Snapshots</b><br>"
            "cedit automatically creates timestamped backups on save. You can also create explicit snapshots "
            "or restore any previous backup state below."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Snapshot Filename", "Created Date", "Size", "Path"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.table, stretch=1)

        # Button row
        btn_row = QHBoxLayout()
        snap_btn = QPushButton("Create Snapshot Now")
        snap_btn.clicked.connect(self._create_snapshot)
        btn_row.addWidget(snap_btn)

        restore_btn = QPushButton("Restore Selected Snapshot")
        restore_btn.setStyleSheet("background-color: #d46b08; color: white; font-weight: bold;")
        restore_btn.clicked.connect(self._restore_selected)
        btn_row.addWidget(restore_btn)

        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(del_btn)

        btn_row.addStretch(1)

        open_folder_btn = QPushButton("Open Backup Folder")
        open_folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_folder_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _refresh(self):
        self.table.blockSignals(True)
        backups = self.list_backups(self.save_path)
        self.table.setRowCount(len(backups))
        for row, b in enumerate(backups):
            fn_cell = QTableWidgetItem(b["filename"])
            fn_cell.setData(Qt.UserRole, b["path"])
            self.table.setItem(row, 0, fn_cell)

            dt = datetime.datetime.fromtimestamp(b["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            self.table.setItem(row, 1, QTableWidgetItem(dt))

            size_str = f"{b['size'] / 1024:.1f} KB" if b["size"] >= 1024 else f"{b['size']} B"
            self.table.setItem(row, 2, QTableWidgetItem(size_str))

            self.table.setItem(row, 3, QTableWidgetItem(b["path"]))
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

    def _create_snapshot(self):
        if not self.save_path or not os.path.isfile(self.save_path):
            QMessageBox.warning(self, "Create Snapshot", "No valid save file is currently open.")
            return
        p = self.backup_file(self.save_path, keep=None)
        QMessageBox.information(self, "Snapshot Created", f"Created snapshot:\n{os.path.basename(p)}")
        self._refresh()

    def _restore_selected(self):
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Restore Snapshot", "Please select a backup from the list to restore.")
            return
        row = selected[0].row()
        backup_path = self.table.item(row, 0).data(Qt.UserRole)
        fn = self.table.item(row, 0).text()

        ans = QMessageBox.question(
            self, "Confirm Restore",
            f"Are you sure you want to restore snapshot {fn}?\n\n"
            "Your current save will be safely backed up before overwriting.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            return

        try:
            self.restore_backup(backup_path, self.save_path)
            QMessageBox.information(self, "Restored", f"Successfully restored {fn}. Reloading save file...")
            if hasattr(self.parent_window, "open_path"):
                self.parent_window.open_path(self.save_path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Restore Error", f"Failed to restore backup: {e}")

    def _delete_selected(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        backup_path = self.table.item(row, 0).data(Qt.UserRole)
        fn = self.table.item(row, 0).text()

        ans = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete backup file {fn} permanently?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ans == QMessageBox.Yes:
            try:
                os.remove(backup_path)
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, "Delete Error", f"Failed to delete backup: {e}")

    def _open_folder(self):
        import subprocess
        d = os.path.dirname(self.save_path) or "."
        if sys.platform == "darwin":
            subprocess.Popen(["open", d])
        elif sys.platform.startswith("win"):
            os.startfile(d)
        else:
            subprocess.Popen(["xdg-open", d])


class SaveEditorWindow(QMainWindow):
    def __init__(self, profile):
        super().__init__()
        self.profile = profile
        self.file_path = None
        self.data = None
        self.dirty = False
        # QTreeWidgetItem -> (parent_container, key_or_index). The root
        # QTreeWidgetItem itself maps to (None, None).
        self.node_lookup = {}
        self.quick_rows = {}  # name -> (QLineEdit, QPushButton)

        # Snapshot-based undo/redo: each entry is a full deepcopy of
        # self.data from just before one mutating action. Simple rather
        # than a proper command pattern, but edits happen through many
        # different code paths (quick-edit, tree double-click, add/delete
        # key, raw-JSON apply, table-dialog edits) and a snapshot-per-action
        # covers all of them uniformly instead of needing bespoke undo
        # logic duplicated in each one. Save files aren't huge enough for
        # the deepcopy cost to matter, and the stack is capped so memory
        # use can't grow unbounded across a long editing session.
        self._undo_stack = []
        self._redo_stack = []
        self._UNDO_LIMIT = 25

        self.setWindowTitle(APP_TITLE)
        self.resize(*MAIN_WINDOW_SIZE)
        self.setMinimumSize(*MAIN_WINDOW_MIN)

        self._build_menu()
        self._build_central_widget()
        self._set_dirty(False)
        self._apply_profile_to_ui()
        self._refresh_recent_menu()

    # ---------------------------------------------------------- UI setup

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        open_action = QAction("Open Save File...", self, shortcut=QKeySequence.Open)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)
        default_folder_action = QAction("Open Default Save Folder...", self)
        default_folder_action.triggered.connect(self.open_default_folder)
        file_menu.addAction(default_folder_action)
        discover_action = QAction("Discover Saves...", self)
        discover_action.triggered.connect(self.discover_saves)
        file_menu.addAction(discover_action)
        manage_backups_action = QAction("Manage Backups...", self)
        manage_backups_action.triggered.connect(self.open_backup_manager)
        file_menu.addAction(manage_backups_action)
        self.recent_menu = QMenu("Open Recent", self)
        file_menu.addMenu(self.recent_menu)
        file_menu.addSeparator()
        save_action = QAction("Save", self, shortcut=QKeySequence.Save)
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)
        save_as_action = QAction("Save As...", self)
        save_as_action.triggered.connect(self.save_file_as)
        file_menu.addAction(save_as_action)
        file_menu.addSeparator()
        reload_action = QAction("Reload from Disk", self)
        reload_action.triggered.connect(self.reload_file)
        file_menu.addAction(reload_action)
        file_menu.addSeparator()
        self.fix_texture_action = QAction("Fix Texture (Hades II)...", self)
        self.fix_texture_action.triggered.connect(self.open_fix_texture_dialog)
        file_menu.addAction(self.fix_texture_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self, shortcut=QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = menubar.addMenu("&Edit")
        self.undo_action = QAction("Undo", self, shortcut=QKeySequence.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.undo_action.setEnabled(False)
        edit_menu.addAction(self.undo_action)
        self.redo_action = QAction("Redo", self, shortcut=QKeySequence.Redo)
        self.redo_action.triggered.connect(self.redo)
        self.redo_action.setEnabled(False)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        add_key_action = QAction("Add Key to Selected...", self)
        add_key_action.triggered.connect(self.add_key_to_selected)
        edit_menu.addAction(add_key_action)
        delete_action = QAction("Delete Selected", self)
        delete_action.triggered.connect(self.delete_selected)
        edit_menu.addAction(delete_action)
        edit_menu.addSeparator()
        self.spawn_item_action = QAction("Inventory Editor...", self)
        self.spawn_item_action.triggered.connect(self.open_inventory_editor)
        self.spawn_item_action.setEnabled(False)  # enabled per-profile in _apply_profile_to_ui
        edit_menu.addAction(self.spawn_item_action)
        self.hades_suite_action = QAction("Hades Editor Suite...", self)
        self.hades_suite_action.triggered.connect(self.open_hades_suite)
        edit_menu.addAction(self.hades_suite_action)
        edit_menu.addSeparator()
        find_action = QAction("Find...", self, shortcut=QKeySequence.Find)
        find_action.triggered.connect(self.focus_search)
        edit_menu.addAction(find_action)

        view_menu = menubar.addMenu("&View")
        expand_action = QAction("Expand All", self)
        expand_action.triggered.connect(lambda: self._expand_all(True))
        view_menu.addAction(expand_action)
        collapse_action = QAction("Collapse All", self)
        collapse_action.triggered.connect(lambda: self._expand_all(False))
        view_menu.addAction(collapse_action)

        game_menu = menubar.addMenu("&Game")
        for prof in list_games():
            action = QAction(prof.display_name, self)
            action.triggered.connect(lambda checked=False, p=prof: self.switch_game(p))
            game_menu.addAction(action)

    def _build_central_widget(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        layout.addWidget(self._build_toolbar())
        self.quick_group = self._build_quick_edit()
        layout.addWidget(self.quick_group)
        layout.addWidget(self._build_body(), stretch=1)
        layout.addLayout(self._build_raw_buttons())

        self.statusBar().showMessage("Ready.")
        # A permanent widget (not showMessage()) so the version stays
        # visible in the footer's right corner no matter what status text
        # _set_status() puts in the main (left) part of the bar.
        version_label = QLabel(f"{APP_TITLE} v{APP_VERSION}")
        version_label.setStyleSheet("color: palette(mid);")
        self.statusBar().addPermanentWidget(version_label)

    def _build_toolbar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel("Game:"))
        self.game_combo = QComboBox()
        self.game_combo.addItems([p.display_name for p in list_games()])
        self.game_combo.currentTextChanged.connect(self._on_game_combo_changed)
        row.addWidget(self.game_combo)

        row.addSpacing(10)
        open_btn = QPushButton("Open...")
        open_btn.clicked.connect(self.open_file)
        row.addWidget(open_btn)
        discover_btn = QPushButton("Discover Saves...")
        discover_btn.clicked.connect(self.discover_saves)
        row.addWidget(discover_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_file)
        row.addWidget(save_btn)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.reload_file)
        row.addWidget(reload_btn)
        self.hades_suite_btn = QPushButton("Hades Suite...")
        self.hades_suite_btn.setStyleSheet("color: #2b78e4; font-weight: bold;")
        self.hades_suite_btn.clicked.connect(self.open_hades_suite)
        row.addWidget(self.hades_suite_btn)

        row.addSpacing(14)
        row.addWidget(QLabel("Find:"))
        self.search_edit = QLineEdit()
        # setMinimumWidth (not setFixedWidth) - a fixed width pins a hard
        # floor into the whole toolbar row's layout, which is what was
        # making the window's minimum size feel stuck regardless of how
        # small you tried to resize it. Minimum + a size policy lets it
        # both shrink with the window and grow to fill spare space.
        self.search_edit.setMinimumWidth(100)
        self.search_edit.returnPressed.connect(self.run_search)
        row.addWidget(self.search_edit)
        find_btn = QPushButton("Search")
        find_btn.clicked.connect(self.run_search)
        row.addWidget(find_btn)

        row.addStretch(1)
        self.path_label = QLabel("No file loaded")
        self.path_label.setStyleSheet("color: #888;")
        row.addWidget(self.path_label)
        return bar

    # Fields per row before wrapping to the next line. A plain QHBoxLayout
    # packing every field into one row squeezes everyone's labels/fields
    # once a profile defines more than a handful of quick_fields (Dave the
    # Diver's 8 vs. Duckov's 3-ish) - wrapping keeps each field's label
    # fully readable and its Apply button a consistent size regardless of
    # how many fields a given game profile declares.
    _QUICK_EDIT_COLUMNS = 4

    def _build_quick_edit(self):
        group = QGroupBox("Quick Edit")
        self.quick_layout = QGridLayout(group)
        self.quick_layout.setHorizontalSpacing(12)
        self.quick_layout.setVerticalSpacing(6)
        return group

    def _rebuild_quick_edit_widgets(self):
        while self.quick_layout.count():
            child = self.quick_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self.quick_rows.clear()

        if not self.profile.quick_fields:
            self.quick_layout.addWidget(
                QLabel("(no quick-edit fields defined for this game)"), 0, 0
            )
            return

        cols = self._QUICK_EDIT_COLUMNS
        for i, name in enumerate(self.profile.quick_fields):
            row, group_col = divmod(i, cols)
            base_col = group_col * 3

            label = QLabel(f"{name}:")
            label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.quick_layout.addWidget(label, row, base_col)

            edit = QLineEdit()
            edit.setMinimumWidth(70)
            edit.setMaximumWidth(140)
            edit.setEnabled(False)
            self.quick_layout.addWidget(edit, row, base_col + 1)

            btn = QPushButton("Apply")
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked=False, n=name: self.apply_quick_field(n))
            self.quick_layout.addWidget(btn, row, base_col + 2)

            self.quick_rows[name] = (edit, btn)

        # A trailing stretch column so a partially-filled last row doesn't
        # spread its fields out to fill the window's full width.
        self.quick_layout.setColumnStretch(cols * 3, 1)

    def refresh_quick_edit(self):
        for name, path in self.profile.quick_fields.items():
            edit, btn = self.quick_rows[name]
            try:
                value = get_by_path(self.data, path)
            except (KeyError, IndexError, TypeError):
                edit.setText("")
                edit.setEnabled(False)
                btn.setEnabled(False)
                continue
            edit.setText(str(value))
            edit.setEnabled(True)
            btn.setEnabled(True)

    def apply_quick_field(self, name):
        path = self.profile.quick_fields[name]
        try:
            current = get_by_path(self.data, path)
        except (KeyError, IndexError, TypeError):
            return
        edit, _btn = self.quick_rows[name]
        try:
            new_value = coerce_value(edit.text(), current)
        except ValueError as e:
            QMessageBox.critical(self, APP_TITLE, f"Couldn't apply {name}:\n{e}")
            return
        self._push_undo(self._snapshot())
        set_by_path(self.data, path, new_value)
        # Update just this one row (lazily materializing only the nodes
        # along its path, not the whole tree) instead of tearing down and
        # rebuilding everything - for a save with a lot of nested data,
        # doing a full rebuild on every single quick-edit click would be
        # needlessly slow.
        item = self._ensure_node_for_path(path)
        if item is not None:
            item.setText(1, self._short_repr(new_value))
        else:
            self.rebuild_tree()  # fallback - e.g. tree not built yet
        self._set_dirty(True)
        self._set_status(f"Updated {name} to {new_value}")

    def _build_body(self):
        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Key", "Value", "Type"])
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 380)
        self.tree.setColumnWidth(2, 90)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.itemDoubleClicked.connect(self.on_double_click)
        self.tree.itemExpanded.connect(self._on_tree_expanded)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        splitter.addWidget(self.tree)

        raw_panel = QWidget()
        raw_layout = QVBoxLayout(raw_panel)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        raw_layout.addWidget(QLabel("Raw (advanced - click 'Apply Raw' to load into the tree)"))
        self.raw_text = QPlainTextEdit()
        self.raw_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        raw_layout.addWidget(self.raw_text)
        splitter.addWidget(raw_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        # A stretch factor only governs how *extra* space is divided on
        # resize - the tree's three columns (320+380+90) need ~800px just
        # to show without their own horizontal scrollbar, so the initial
        # split has to be set explicitly too, or a plain 60/40 of a modest
        # starting window width leaves the tree cramped and the raw JSON
        # panel oversized for what it's actually used for.
        splitter.setSizes([850, 450])
        self.body_splitter = splitter
        return splitter

    def _build_raw_buttons(self):
        row = QHBoxLayout()
        row.addStretch(1)
        refresh_btn = QPushButton("Refresh Raw from Tree")
        refresh_btn.clicked.connect(self.refresh_raw_from_tree)
        row.addWidget(refresh_btn)
        apply_btn = QPushButton("Apply Raw -> Tree")
        apply_btn.clicked.connect(self.apply_raw_to_tree)
        row.addWidget(apply_btn)
        return row

    # ------------------------------------------------------------ helpers

    def _set_status(self, text):
        self.statusBar().showMessage(text)

    def _set_dirty(self, value):
        self.dirty = value
        title = f"{APP_TITLE} - {self.profile.display_name}"
        if self.file_path:
            title += f" - {os.path.basename(self.file_path)}"
        if value:
            title += " *"
        self.setWindowTitle(title)

    # ------------------------------------------------------------- undo/redo

    def _snapshot(self):
        return copy.deepcopy(self.data)

    def _push_undo(self, snapshot):
        """Records `snapshot` (the state from just BEFORE the mutation the
        caller is about to make/just made) onto the undo stack. Call this
        once a mutation is known to actually be happening - not before
        validation that might still bail out, or every failed/no-op edit
        would pollute the undo history."""
        self._undo_stack.append(snapshot)
        del self._undo_stack[:-self._UNDO_LIMIT]  # keep only the most recent N
        self._redo_stack.clear()
        self._update_undo_redo_actions()

    def _update_undo_redo_actions(self):
        self.undo_action.setEnabled(bool(self._undo_stack))
        self.redo_action.setEnabled(bool(self._redo_stack))

    def _reset_undo_history(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_undo_redo_actions()

    def _after_data_replaced(self, dirty):
        """Common refresh after self.data itself was swapped out from
        under the tree (by undo/redo) - full rebuild, since there's no
        cheap way to know just which nodes changed."""
        self.rebuild_tree()
        self.refresh_raw_from_tree()
        self.refresh_quick_edit()
        self._set_dirty(dirty)
        if getattr(self, "_inventory_editor_window", None) is not None:
            self._inventory_editor_window.refresh()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self.data = self._undo_stack.pop()
        self._update_undo_redo_actions()
        # Once the undo stack is empty, we're back to exactly what was
        # loaded from disk (or last saved) - anything left in it means
        # there's still at least one un-reverted change.
        self._after_data_replaced(dirty=bool(self._undo_stack))
        self._set_status("Undid last change.")

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        del self._undo_stack[:-self._UNDO_LIMIT]
        self.data = self._redo_stack.pop()
        self._update_undo_redo_actions()
        self._after_data_replaced(dirty=True)  # redo always moves away from the on-disk state
        self._set_status("Redid change.")

    def _apply_profile_to_ui(self):
        self.game_combo.blockSignals(True)
        self.game_combo.setCurrentText(self.profile.display_name)
        self.game_combo.blockSignals(False)
        self._rebuild_quick_edit_widgets()
        self.spawn_item_action.setEnabled(
            self.profile.spawn_item is not None
            and self.profile.spawn_item_targets is not None
            and self.profile.inventory_state is not None
            and self.profile.remove_inventory_item is not None
        )
        is_hades = self.profile.key in ("hades", "hades2")
        if hasattr(self, "hades_suite_action"):
            self.hades_suite_action.setVisible(is_hades)
        if hasattr(self, "hades_suite_btn"):
            self.hades_suite_btn.setVisible(is_hades)
        if hasattr(self, "fix_texture_action"):
            self.fix_texture_action.setVisible(self.profile.key == "hades2")
            if self.profile.key == "hades2":
                self._update_fix_texture_menu()
        if self.profile.notes:
            self._set_status(self.profile.notes.splitlines()[0])

    def _on_game_combo_changed(self, selected_name):
        for prof in list_games():
            if prof.display_name == selected_name:
                self.switch_game(prof)
                return

    def switch_game(self, profile):
        if profile.key == self.profile.key:
            return
        if profile.custom_launcher is not None:
            # This game's save model doesn't fit the generic tree editor at
            # all (see lib/base.py's GameProfile.custom_launcher docstring).
            # Open its own window and leave the generic editor's state alone.
            self.game_combo.blockSignals(True)
            self.game_combo.setCurrentText(self.profile.display_name)
            self.game_combo.blockSignals(False)
            profile.custom_launcher(self)
            return
        if self.dirty and QMessageBox.question(
            self, APP_TITLE, "Switching games will discard unsaved changes. Continue?"
        ) != QMessageBox.Yes:
            self.game_combo.blockSignals(True)
            self.game_combo.setCurrentText(self.profile.display_name)
            self.game_combo.blockSignals(False)
            return
        if getattr(self, "_inventory_editor_window", None) is not None:
            # Its cached view is tied to the OLD profile's hooks/shape -
            # closing it here (rather than leaving it open to error on its
            # next refresh) is simpler and safer than trying to re-target
            # it at a profile that may not even define these hooks.
            self._inventory_editor_window.close()
            self._inventory_editor_window = None

        self.profile = profile
        self.file_path = None
        self.data = None
        self._reset_undo_history()
        self.path_label.setText("No file loaded")
        self.rebuild_tree()
        self.refresh_raw_from_tree()
        self._set_dirty(False)
        self._apply_profile_to_ui()
        self._set_status(f"Switched to {profile.display_name}.")

    def open_fix_texture_dialog(self):
        from games.hades_window import FixTextureDialog
        dialog = FixTextureDialog(self)
        dialog.exec()
        self._update_fix_texture_menu()

    def _update_fix_texture_menu(self):
        if hasattr(self, "fix_texture_action") and self.profile.key == "hades2":
            from lib import hades_lib
            content_dir = hades_lib.resolve_hades2_content_dir()
            if content_dir:
                status = hades_lib.get_hades2_texture_status(content_dir)
                if status.get("is_swapped"):
                    self.fix_texture_action.setText("Fix Texture (Hades II) [HD: ON]...")
                else:
                    self.fix_texture_action.setText("Fix Texture (Hades II) [HD: OFF]...")
            else:
                self.fix_texture_action.setText("Fix Texture (Hades II)...")

    def open_backup_manager(self):
        if not self.current_path:
            QMessageBox.information(self, "Manage Backups", "Please open a save file first.")
            return
        dialog = BackupManagerDialog(self, self.current_path)
        dialog.exec()

    def open_default_folder(self):
        d = self.profile.find_default_save_dir()
        if not d:
            hint = "\n".join(self.profile.default_save_dirs) or "(none configured)"
            QMessageBox.information(
                self, APP_TITLE,
                f"Couldn't find a default save folder for {self.profile.display_name}.\n\n"
                f"Typical locations checked:\n{hint}",
            )
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select a save file", d)
        if path:
            self.load_path(path)

    def discover_saves(self):
        paths = self.profile.discover_saves()
        if not paths:
            hint = "\n".join(self.profile.default_save_dirs) or "(none configured)"
            QMessageBox.information(
                self, APP_TITLE,
                f"No {self.profile.display_name} save files found under its default "
                f"save location(s):\n{hint}\n\nUse 'Open Save File...' to browse manually.",
            )
            return
        dialog = _DiscoveredSavesDialog(self, paths)
        if dialog.exec() == QDialog.Accepted and dialog.chosen_path:
            self.load_path(dialog.chosen_path)

    # ------------------------------------------------------------ file IO

    def open_file(self):
        initial = self.profile.find_default_save_dir() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, f"Open {self.profile.display_name} save file", initial,
            _qt_filter_string(self.profile.file_patterns),
        )
        if path:
            self.load_path(path)

    def load_path(self, path):
        try:
            if self.profile.binary:
                with open(path, "rb") as f:
                    raw_text = f.read()
            else:
                with open(path, encoding="utf-8-sig") as f:
                    raw_text = f.read()
        except UnicodeDecodeError:
            QMessageBox.critical(
                self, APP_TITLE,
                "This file doesn't look like a text/JSON file (it may be binary or "
                "encrypted). This game profile expects a plain-text save format.",
            )
            return
        except OSError as e:
            QMessageBox.critical(self, APP_TITLE, f"Couldn't open file:\n{e}")
            return

        try:
            data = self.profile.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as e:
            QMessageBox.critical(
                self, APP_TITLE,
                f"Couldn't parse this file as a {self.profile.display_name} save.\n\n"
                f"Error: {e}",
            )
            return

        try:
            backup_path = backup_file(path)
        except OSError as e:
            if QMessageBox.question(
                self, APP_TITLE,
                f"Couldn't create a backup before opening this file:\n{e}\n\n"
                "Continue opening it anyway? (not recommended)",
            ) != QMessageBox.Yes:
                return
            backup_path = None

        self.file_path = path
        self.data = data
        self._reset_undo_history()
        self._set_dirty(False)
        self.rebuild_tree()
        self.refresh_raw_from_tree()
        self.refresh_quick_edit()

        self.path_label.setText(path)
        msg = f"Loaded {path}"
        if backup_path:
            msg += f"  (backup: {os.path.basename(backup_path)})"
        self._set_status(msg)
        self._add_recent_file(self.profile.key, path)

    # ------------------------------------------------------------ recent files
    #
    # Persisted via QSettings (Qt's native per-OS preferences mechanism -
    # a plist under ~/Library/Preferences on macOS), not a config file of
    # our own, so it needs no extra path-management code. Each entry
    # records which game profile the file was opened under (not just the
    # path) so reopening a recent file also switches to the right game
    # first if it isn't already selected - DREDGE never appears here since
    # its custom_launcher window doesn't go through load_path() at all.

    def _load_recent_entries(self):
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        raw = settings.value("recent_files", [])
        if isinstance(raw, str):  # Qt collapses a single-item list to a bare string on some backends
            raw = [raw]
        entries = []
        for item in raw or []:
            if isinstance(item, str) and "|" in item:
                key, path = item.split("|", 1)
                entries.append((key, path))
        return entries

    def _save_recent_entries(self, entries):
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue("recent_files", [f"{key}|{path}" for key, path in entries])

    def _add_recent_file(self, profile_key, path):
        entries = [e for e in self._load_recent_entries() if e[1] != path]
        entries.insert(0, (profile_key, path))
        del entries[_RECENT_FILES_LIMIT:]
        self._save_recent_entries(entries)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        entries = self._load_recent_entries()
        if not entries:
            empty_action = QAction("(no recent files)", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for profile_key, path in entries:
            try:
                display_name = get_game(profile_key).display_name
            except KeyError:
                display_name = profile_key
            action = QAction(f"{os.path.basename(path)}  —  {display_name}", self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, k=profile_key, p=path: self._open_recent(k, p))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _open_recent(self, profile_key, path):
        if not os.path.isfile(path):
            QMessageBox.warning(self, APP_TITLE, f"This file no longer exists:\n{path}")
            return
        if profile_key != self.profile.key:
            try:
                target_profile = get_game(profile_key)
            except KeyError:
                QMessageBox.warning(self, APP_TITLE, f"Unknown game profile '{profile_key}' for this entry.")
                return
            self.switch_game(target_profile)
            if self.profile.key != profile_key:
                return  # switch was cancelled (e.g. unsaved changes prompt)
        self.load_path(path)

    def _clear_recent_files(self):
        self._save_recent_entries([])
        self._refresh_recent_menu()

    def reload_file(self):
        if not self.file_path:
            QMessageBox.information(self, APP_TITLE, "No file is currently open.")
            return
        if self.dirty and QMessageBox.question(
            self, APP_TITLE, "You have unsaved changes that will be lost. Reload anyway?"
        ) != QMessageBox.Yes:
            return
        self.load_path(self.file_path)

    def save_file(self):
        if not self.file_path:
            self.save_file_as()
            return
        self._write_to(self.file_path)

    def save_file_as(self):
        if self.data is None:
            QMessageBox.information(self, APP_TITLE, "Nothing loaded yet.")
            return
        initial_dir = os.path.dirname(self.file_path) if self.file_path else os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {self.profile.display_name} save file as", initial_dir,
            _qt_filter_string(self.profile.file_patterns),
        )
        if path:
            self._write_to(path)
            self.file_path = path
            self.path_label.setText(path)

    def _write_to(self, path):
        if self.profile.pre_save_check:
            try:
                block_reason = self.profile.pre_save_check(path)
            except Exception:
                block_reason = None
            if block_reason:
                QMessageBox.warning(self, APP_TITLE, block_reason)
                return

        try:
            payload = self.profile.dump(self.data)
        except (TypeError, ValueError) as e:
            QMessageBox.critical(self, APP_TITLE, f"Couldn't serialize the data:\n{e}")
            return

        if os.path.exists(path):
            try:
                backup_file(path)
            except OSError as e:
                if QMessageBox.question(
                    self, APP_TITLE, f"Couldn't create a backup before saving:\n{e}\n\nSave anyway?"
                ) != QMessageBox.Yes:
                    return

        try:
            if self.profile.binary:
                atomic_write_bytes(path, payload)
            else:
                atomic_write_text(path, payload)
        except OSError as e:
            QMessageBox.critical(self, APP_TITLE, f"Couldn't save file:\n{e}")
            return

        self._set_dirty(False)
        self._set_status(f"Saved to {path}")

    # -------------------------------------------------------- tree building
    #
    # Children are built lazily: a dict/list node gets one fake placeholder
    # child (marked via _LAZY_ROLE) instead of its real contents being
    # recursed into immediately. Real children are only built the first time
    # a node is actually expanded (_on_tree_expanded). Without this, a save
    # with a lot of nested data (thousands of inventory/quest/note entries,
    # etc.) would insert every single one of those rows up front, even
    # though almost none of them are ever looked at.

    def rebuild_tree(self):
        self.tree.clear()
        self.node_lookup.clear()
        if self.data is None:
            return
        root_item = QTreeWidgetItem(["(root)", "", guess_type(self.data)])
        self.tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self.node_lookup[root_item] = (None, None)
        self._populate_children(root_item, self.data)

    def _populate_children(self, parent_item, container):
        if isinstance(container, dict):
            items = container.items()
        elif isinstance(container, list):
            items = enumerate(container)
        else:
            return

        for key, value in items:
            special = self.profile.find_special_node(container, key, value)
            if special is not None:
                try:
                    decoded = special.decode(container, key, value)
                    child = QTreeWidgetItem([
                        str(key), self._short_repr(decoded), special.label_for(container, key, value)
                    ])
                    parent_item.addChild(child)
                    self.node_lookup[child] = (container, key)
                    continue
                except Exception:
                    pass  # fall through to default handling

            vtype = guess_type(value)
            display_value = "" if vtype in ("dict", "list") else self._short_repr(value)
            summary = ""
            if vtype == "dict":
                summary = f"{{{len(value)} keys}}"
            elif vtype == "list":
                summary = f"[{len(value)} items]"
            text1 = display_value or summary
            if self.profile.describe_entry:
                try:
                    hint = self.profile.describe_entry(container, key, value)
                except Exception:
                    hint = None
                if hint:
                    text1 = f"{text1}  —  {hint}" if text1 else hint
            child = QTreeWidgetItem([str(key), text1, vtype])
            parent_item.addChild(child)
            self.node_lookup[child] = (container, key)
            if vtype in ("dict", "list") and len(value) > 0:
                placeholder = QTreeWidgetItem([""])
                placeholder.setData(0, _LAZY_ROLE, True)
                child.addChild(placeholder)

    def _on_tree_expanded(self, item):
        self._materialize_children(item)

    def _materialize_children(self, item):
        """Replaces a node's lazy placeholder (if it still has one) with its
        real children. No-ops for a node that's already been materialized
        or has no children."""
        if item is None:
            return
        if item.childCount() != 1 or not item.child(0).data(0, _LAZY_ROLE):
            return
        item.takeChildren()
        container, key = self.node_lookup.get(item, (None, None))
        value = self.data if (container is None and key is None) else container[key]
        self._populate_children(item, value)

    def _find_node_item(self, container, key):
        """The tree item currently showing container[key], if the tree has
        one - used to patch a single row in place instead of rebuilding the
        whole tree for a one-value edit."""
        for item, (c, k) in self.node_lookup.items():
            if c is container and k == key:
                return item
        return None

    def _ensure_node_for_path(self, path):
        """Lazily materializes only the tree nodes along `path` (not the
        whole tree) and returns the item for path's last key, or None if
        the tree hasn't been built at all yet. Lets a quick-edit patch its
        one row in place no matter how deep it is, without needing that
        branch to have already been expanded by the user."""
        if self.tree.topLevelItemCount() == 0:
            return None
        item = self.tree.topLevelItem(0)  # the "(root)" item
        container = self.data
        for depth, key in enumerate(path):
            self._materialize_children(item)
            child = self._find_node_item(container, key)
            if child is None:
                return None
            if depth == len(path) - 1:
                return child
            container = container[key]
            item = child
        return None

    @staticmethod
    def _short_repr(value):
        s = str(value)
        if len(s) > 120:
            s = s[:117] + "..."
        return s

    def _expand_all(self, open_state):
        # Expanding needs to materialize each node's lazy children first
        # (recursively) - unlike a single click on one node, this is an
        # explicit "yes, build everything" request from the user, not
        # something that happens as a side effect of routine editing.
        def recurse(item):
            if open_state:
                self._materialize_children(item)
            item.setExpanded(open_state)
            for i in range(item.childCount()):
                recurse(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            recurse(self.tree.topLevelItem(i))

    # -------------------------------------------------------------- editing

    def _show_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        container, key = self.node_lookup.get(item, (None, None))
        value = self.data if (container is None and key is None) else container[key]
        if not isinstance(value, (dict, list)) or not value:
            return

        menu = QMenu(self)
        action = menu.addAction("View as Table...")
        if isinstance(value, dict):
            action.triggered.connect(lambda: self._open_dict_table(item, value))
        elif isinstance(value, list):
            action.triggered.connect(lambda: self._open_list_table(item, value))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _open_dict_table(self, item, value: dict):
        pre_edit_snapshot = self._snapshot()
        title = item.text(0) if item else "Dictionary"
        dialog = DictTableDialog(self, value, self.profile, title=f"{title} ({len(value)} entries)")
        dialog.exec()
        if not dialog.dirty:
            return
        self._push_undo(pre_edit_snapshot)
        item.takeChildren()
        item.setText(1, f"{{{len(value)} keys}}")
        if len(value) > 0:
            placeholder = QTreeWidgetItem([""])
            placeholder.setData(0, _LAZY_ROLE, True)
            item.addChild(placeholder)
        self.refresh_quick_edit()
        self.refresh_raw_from_tree()
        self._set_dirty(True)
        self._set_status("Applied table edits.")

    def _open_list_table(self, item, value):
        # Taken before exec(), not after - the table dialog mutates
        # `value` (part of self.data) live as the user edits cells, so by
        # the time exec() returns and dialog.dirty is known, the change has
        # already happened; this is the last point where "before" is safe
        # to capture.
        pre_edit_snapshot = self._snapshot()
        dialog = ListTableDialog(self, value, self.profile, title=f"{item.text(0)} ({len(value)} items)")
        dialog.exec()
        if not dialog.dirty:
            return
        self._push_undo(pre_edit_snapshot)
        # Rows may have been added/removed as well as edited - drop this
        # branch's already-materialized children (if any) and let it
        # re-lazy-populate the next time it's expanded, and refresh its own
        # summary text ("[N items]") in case the count changed.
        item.takeChildren()
        item.setText(1, f"[{len(value)} items]")
        if len(value) > 0:
            placeholder = QTreeWidgetItem([""])
            placeholder.setData(0, _LAZY_ROLE, True)
            item.addChild(placeholder)
        self._set_dirty(True)
        self._set_status("Applied table edits.")

    def on_double_click(self, item, column):
        if column != 1:  # only the "value" column is directly editable
            return
        container, key = self.node_lookup.get(item, (None, None))
        if container is None:
            return  # root node
        value = container[key]

        if self.profile.is_read_only(container, key, value):
            QMessageBox.information(
                self, APP_TITLE,
                f"'{key}' is read-only for {self.profile.display_name} in cedit "
                "(shown for reference, but not safe to edit here).",
            )
            return

        special = self.profile.find_special_node(container, key, value)
        if special is not None:
            try:
                decoded = special.decode(container, key, value)
            except Exception as e:
                QMessageBox.critical(self, APP_TITLE, f"Couldn't decode this value:\n{e}")
                return
            type_label = special.label_for(container, key, value)
            new_text, ok = QInputDialog.getText(
                self, "Edit value", f"Key: {key}\nType: {type_label}\n\nNew value:",
                text=str(decoded),
            )
            if not ok:
                return
            try:
                new_raw = special.encode(container, key, new_text)
            except ValueError as e:
                QMessageBox.critical(self, APP_TITLE, f"Couldn't apply that value:\n{e}")
                return
            self._push_undo(self._snapshot())
            container[key] = new_raw
            try:
                redecoded = special.decode(container, key, new_raw)
            except Exception:
                redecoded = new_text
            item.setText(1, self._short_repr(redecoded))
            self._set_dirty(True)
            self._set_status(f"Updated '{key}' to {redecoded}")
            return

        vtype = guess_type(value)
        if vtype in ("dict", "list"):
            hint = (
                "expand it in the tree and edit its individual fields instead"
                if vtype == "dict" else
                "expand it in the tree, or right-click it and choose 'View as Table...' "
                "to see and edit every item at once"
            )
            QMessageBox.information(
                self, APP_TITLE, f"'{key}' is a {vtype} with nested data - {hint}."
            )
            return

        current_text = "" if value is None else str(value)
        new_text, ok = QInputDialog.getText(
            self, "Edit value", f"Key: {key}\nCurrent type: {vtype}\n\nNew value:",
            text=current_text,
        )
        if not ok:
            return

        try:
            new_value = coerce_value(new_text, value)
        except ValueError as e:
            QMessageBox.critical(self, APP_TITLE, f"Couldn't apply that value:\n{e}")
            return

        self._push_undo(self._snapshot())
        container[key] = new_value
        item.setText(1, self._short_repr(new_value))
        self._set_dirty(True)
        self._set_status(f"Updated '{key}'")

    def add_key_to_selected(self):
        if self.profile.binary:
            QMessageBox.information(
                self, APP_TITLE,
                f"{self.profile.display_name}'s save format has a fixed structure - "
                "you can only edit existing values, not add or remove fields.",
            )
            return
        item = self.tree.currentItem()
        if item is None:
            QMessageBox.information(self, APP_TITLE, "Select a dict or list node first (or the root).")
            return
        container, key = self.node_lookup.get(item, (None, None))
        if key is None and container is None:
            target = self.data
        else:
            target = container[key]

        if isinstance(target, dict):
            new_key, ok = QInputDialog.getText(self, "Add key", "New key name:")
            if not ok or not new_key:
                return
            if new_key in target:
                QMessageBox.critical(self, APP_TITLE, "That key already exists.")
                return
            new_val_text, ok = QInputDialog.getText(self, "Add key", f"Value for '{new_key}':")
            if not ok:
                return
            self._push_undo(self._snapshot())
            target[new_key] = smart_parse(new_val_text)
        elif isinstance(target, list):
            new_val_text, ok = QInputDialog.getText(self, "Add item", "Value to append to the list:")
            if not ok:
                return
            self._push_undo(self._snapshot())
            target.append(smart_parse(new_val_text))
        else:
            QMessageBox.information(self, APP_TITLE, "Select a dict or list node to add into.")
            return

        self.rebuild_tree()
        self._set_dirty(True)
        self._set_status("Added new entry.")

    def delete_selected(self):
        if self.profile.binary:
            QMessageBox.information(
                self, APP_TITLE,
                f"{self.profile.display_name}'s save format has a fixed structure - "
                "you can only edit existing values, not add or remove fields.",
            )
            return
        item = self.tree.currentItem()
        if item is None:
            return
        container, key = self.node_lookup.get(item, (None, None))
        if container is None:
            QMessageBox.information(self, APP_TITLE, "You can't delete the root.")
            return
        if QMessageBox.question(
            self, APP_TITLE, f"Delete '{key}'? (You can Undo this, or restore from a .bak file.)"
        ) != QMessageBox.Yes:
            return
        self._push_undo(self._snapshot())
        try:
            if isinstance(container, (dict, list)):
                del container[key]
        except (KeyError, IndexError):
            pass
        self.rebuild_tree()
        self._set_dirty(True)
        self._set_status(f"Deleted '{key}'")


    def open_hades_suite(self):
        if self.profile.key in ("hades", "hades2"):
            from games.hades_window import HadesEditorWindow
            win = HadesEditorWindow(self, game_key=self.profile.key, initial_path=self.file_path)
            win.exec()
            if self.file_path and os.path.isfile(self.file_path):
                self.load_path(self.file_path)
    def open_inventory_editor(self):
        if self.data is None:
            return
        targets = self.profile.spawn_item_targets(self.data) if self.profile.spawn_item_targets else []
        if not targets:
            QMessageBox.information(self, APP_TITLE, "No inventory containers are available in this save.")
            return
        if getattr(self, "_inventory_editor_window", None) is None:
            self._inventory_editor_window = InventoryEditorWindow(self)
        else:
            self._inventory_editor_window._reload_targets()
        self._inventory_editor_window.show()
        self._inventory_editor_window.raise_()
        self._inventory_editor_window.activateWindow()

    # -------------------------------------------------------------- search

    def focus_search(self):
        self.search_edit.setFocus()

    def run_search(self):
        # Searches the underlying data directly (fast - it's just walking
        # nested dicts/lists in memory), not the tree widget - the tree
        # only has whichever branches have actually been expanded so far
        # (see the "tree building" section above), so searching the tree
        # itself would silently miss every match still hidden under a
        # collapsed, not-yet-materialized node.
        query = self.search_edit.text().strip().lower()
        if not query or self.data is None:
            return
        matches = []
        for path, container, key, value in self._iter_data_paths(self.data):
            key_text, value_text = self._match_text(container, key, value)
            if query in key_text.lower() or query in value_text.lower():
                matches.append((path, key_text, value_text))

        if getattr(self, "_search_dialog", None) is None:
            self._search_dialog = SearchResultsDialog(self)
        self._search_dialog.show_results(query, matches)
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()
        self._set_status(
            f"{len(matches)} match(es) for '{query}'." if matches else f"No match found for '{query}'."
        )

    def _iter_data_paths(self, container, prefix=()):
        """Yields (path, container, key, value) for every node in the save
        data, mirroring exactly which nodes _populate_children would create
        (including not recursing into a node a SpecialNode already renders
        as a decoded leaf) - so search results match what's actually in the
        tree once revealed."""
        if isinstance(container, dict):
            items = list(container.items())
        elif isinstance(container, list):
            items = list(enumerate(container))
        else:
            return
        for key, value in items:
            path = prefix + (key,)
            yield path, container, key, value
            if self.profile.find_special_node(container, key, value) is not None:
                continue
            if guess_type(value) in ("dict", "list"):
                yield from self._iter_data_paths(value, path)

    def _match_text(self, container, key, value):
        """The same (key, value) text a tree row for this node would show -
        must mirror _populate_children's display logic exactly (in
        particular: a dict/list shows its "{N keys}"/"[N items]" summary,
        never the raw str() of its full contents), or search could "find"
        matches buried in a container's contents that the visible row for
        that container never actually displays."""
        special = self.profile.find_special_node(container, key, value)
        if special is not None:
            try:
                return str(key), self._short_repr(special.decode(container, key, value))
            except Exception:
                pass
        vtype = guess_type(value)
        if vtype == "dict":
            return str(key), f"{{{len(value)} keys}}"
        if vtype == "list":
            return str(key), f"[{len(value)} items]"
        return str(key), self._short_repr(value)

    def _reveal(self, item):
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    # ---------------------------------------------------------- raw view

    def refresh_raw_from_tree(self):
        if self.data is None:
            self.raw_text.setPlainText("")
            return
        if self.profile.binary:
            # profile.dump() returns raw save bytes for binary formats, not
            # text - show a read-only JSON preview of the parsed data instead.
            text = json.dumps(self.data, indent=2, ensure_ascii=False, default=str)
        else:
            text = self.profile.dump(self.data)
        self.raw_text.setPlainText(text)

    def apply_raw_to_tree(self):
        if self.profile.binary:
            QMessageBox.information(
                self, APP_TITLE,
                f"{self.profile.display_name}'s save format is binary - the raw panel "
                "here is a read-only preview. Edit values via the tree instead.",
            )
            return
        text = self.raw_text.toPlainText()
        try:
            new_data = self.profile.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            QMessageBox.critical(self, APP_TITLE, f"Raw data is invalid, not applied:\n{e}")
            return
        self._push_undo(self._snapshot())
        self.data = new_data
        self.rebuild_tree()
        self.refresh_quick_edit()
        self._set_dirty(True)
        self._set_status("Applied raw edits to the tree.")

    # ------------------------------------------------------------- window

    def closeEvent(self, event):
        if self.dirty and QMessageBox.question(
            self, APP_TITLE, "You have unsaved changes. Quit without saving?"
        ) != QMessageBox.Yes:
            event.ignore()
            return
        event.accept()


def main():
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {APP_VERSION}")
    parser.add_argument("save_file", nargs="?", help="Save file to open immediately")
    parser.add_argument(
        "--game", choices=[p.key for p in list_games()], default=list_games()[0].key,
        help="Which game profile to start with"
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)

    icon_path = _resource_path("packaging", "icon.png")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    profile = get_game(args.game)
    window = SaveEditorWindow(profile)

    if args.save_file and os.path.isfile(args.save_file):
        window.load_path(args.save_file)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()