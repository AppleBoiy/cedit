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

import os
import sys
import json
import copy
import argparse

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QKeySequence, QIcon, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTreeWidget, QTreeWidgetItem,
    QPlainTextEdit, QSplitter, QFileDialog, QMessageBox, QInputDialog,
    QGroupBox, QAbstractItemView, QMenu,
    QTableWidget, QTableWidgetItem, QDialog, QCheckBox,
    QListWidget, QListWidgetItem, QGridLayout, QSizePolicy, QHeaderView,
)

from games import list_games, get_game
from lib.base import (
    backup_file,
    atomic_write_text,
    atomic_write_bytes,
    guess_type,
    coerce_value,
    smart_parse,
    get_by_path,
    set_by_path,
    MAIN_WINDOW_SIZE,
    MAIN_WINDOW_MIN,
)

APP_TITLE = "cedit"

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


class ListTableDialog(QDialog):
    """Spreadsheet-style view for a list whose items are dicts (an
    inventory, a character roster, a capture list, ...). Paging through
    hundreds of "{5 keys}" tree rows one expand-click at a time doesn't
    scale - this shows every item as one row with its fields as columns,
    so the whole list can be scanned and edited at once.

    Edits are written straight into the live list/dict objects as they're
    made (same underlying data cedit.py's tree already points at), so
    nothing extra needs to be synced back afterward except refreshing the
    tree's own display of that branch."""

    def __init__(self, parent_window, list_value, profile, title="List"):
        super().__init__(parent_window)
        self.profile = profile
        self.list_value = list_value
        self.dirty = False
        self.show_internal = False  # hide "_"-prefixed bookkeeping columns by default
        self.setWindowTitle(title)
        self.resize(920, 560)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit)
        self.internal_check = QCheckBox("Show internal (_) fields")
        self.internal_check.toggled.connect(self._toggle_internal)
        top.addWidget(self.internal_check)
        top.addStretch(1)
        if not profile.binary:
            add_btn = QPushButton("Add Row")
            add_btn.clicked.connect(self._add_row)
            top.addWidget(add_btn)
            del_btn = QPushButton("Delete Selected Row")
            del_btn.clicked.connect(self._delete_row)
            top.addWidget(del_btn)
        layout.addLayout(top)

        self.columns = self._compute_columns()
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns) + 1)
        self.table.setHorizontalHeaderLabels(["#"] + self.columns)
        self.table.horizontalHeader().setMaximumSectionSize(260)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.table, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._populate()

    def _compute_columns(self):
        """Union of every dict item's keys, in first-seen order, plus a
        "(value)" column if the list also has non-dict items mixed in.
        "_"-prefixed keys (offset/bookkeeping internals, e.g. Octopath's
        "_offsets") are skipped unless "Show internal fields" is checked -
        they're never editable and their values are usually big nested
        dicts, so showing them by default just crowds out the real columns."""
        columns = []
        seen = set()
        has_scalar = False
        for item in self.list_value:
            if isinstance(item, dict):
                for k in item.keys():
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
        """Mirrors the main tree's own display convention: a nested
        dict/list shows its "{N keys}"/"[N items]" summary, never a raw
        str() of its full contents - a cell showing the whole thing inline
        is neither readable nor safely editable as plain text."""
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
                # Not directly editable here - double-click opens a nested
                # table (for a list) or shows an info message (for a dict),
                # same escape hatch the main tree offers.
                cell = QTableWidgetItem(self._display_for(display))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                cell.setData(Qt.UserRole + 1, (row, key))  # nested-drill-down marker
                return cell
            cell = QTableWidgetItem(self._short(display))
            if self.profile.is_read_only(item, key, value) or str(key).startswith("_"):
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            cell.setData(Qt.UserRole, (row, key))
            return cell
        # non-dict list item - only the "(value)" column applies to it
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
        """Handles the nested-drill-down marker set on dict/list-valued
        cells (see _make_cell) - a plain click-to-edit doesn't make sense
        for a nested container, so double-click either opens a further
        table (for a nested list) or points the user at the field name to
        expand in the main tree (for a nested dict)."""
        payload = cell.data(Qt.UserRole + 1)
        if not payload:
            return
        row_index, key = payload
        item = self.list_value[row_index]
        value = item.get(key)
        if isinstance(value, list) and value and any(isinstance(v, dict) for v in value):
            dialog = ListTableDialog(self, value, self.profile, title=f"{key} ({len(value)} items)")
            dialog.exec()
            if dialog.dirty:
                self.dirty = True
                self._populate()
        elif isinstance(value, (dict, list)):
            QMessageBox.information(
                self, APP_TITLE,
                f"'{key}' is a nested {'dict' if isinstance(value, dict) else 'list'} without a "
                "table-friendly shape here - expand row "
                f"{row_index}'s entry in the main tree instead to edit it.",
            )

    def _on_item_changed(self, cell):
        col = cell.column()
        if col == 0:
            return
        payload = cell.data(Qt.UserRole)
        if not payload:
            return
        row_index, dict_key = payload
        if dict_key is None:
            original = self.list_value[row_index]
            try:
                new_value = coerce_value(cell.text(), original)
            except ValueError as e:
                QMessageBox.critical(self, APP_TITLE, f"Couldn't apply value:\n{e}")
                self._populate()
                return
            self.list_value[row_index] = new_value
        else:
            item = self.list_value[row_index]
            original = item.get(dict_key)
            special = self.profile.find_special_node(item, dict_key, original)
            try:
                if special:
                    item[dict_key] = special.encode(item, dict_key, cell.text())
                else:
                    item[dict_key] = coerce_value(cell.text(), original)
            except ValueError as e:
                QMessageBox.critical(self, APP_TITLE, f"Couldn't apply value:\n{e}")
                self._populate()
                return
        self.dirty = True

    def _add_row(self):
        template = {}
        if self.list_value and isinstance(self.list_value[0], dict):
            template = {k: None for k in self.list_value[0].keys()}
        self.list_value.append(template)
        self.dirty = True
        self.columns = self._compute_columns()
        self.table.setColumnCount(len(self.columns) + 1)
        self.table.setHorizontalHeaderLabels(["#"] + self.columns)
        self._populate()

    def _delete_row(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.list_value):
            return
        if QMessageBox.question(self, APP_TITLE, f"Delete row {row}?") != QMessageBox.Yes:
            return
        del self.list_value[row]
        self.dirty = True
        self._populate()

    def _apply_filter(self, text):
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row, False)
                continue
            match = any(
                self.table.item(row, col) and needle in self.table.item(row, col).text().lower()
                for col in range(self.table.columnCount())
            )
            self.table.setRowHidden(row, not match)


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
    and typing an id into the spawn field previews its name live. A game
    with no such catalog just shows ids everywhere instead - nothing here
    ever fabricates or guesses a name.
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
                with open(path, "r", encoding="utf-8-sig") as f:
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
        if not isinstance(value, list) or not value:
            return
        if not any(isinstance(v, dict) for v in value):
            return  # a plain list of scalars gets no extra benefit from a table view
        menu = QMenu(self)
        action = menu.addAction("View as Table...")
        action.triggered.connect(lambda: self._open_list_table(item, value))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

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
            if isinstance(container, dict):
                del container[key]
            elif isinstance(container, list):
                del container[key]
        except (KeyError, IndexError):
            pass
        self.rebuild_tree()
        self._set_dirty(True)
        self._set_status(f"Deleted '{key}'")

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


def _resource_path(*parts):
    """Resolve a path that works both running from source and from a
    PyInstaller-built app bundle (which unpacks bundled data under
    sys._MEIPASS instead of next to this script)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def main():
    parser = argparse.ArgumentParser(description=APP_TITLE)
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
