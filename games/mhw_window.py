"""
MHW's dedicated editor window - split out from games/mhw.py the same way
games/dredge_window.py is split from games/dredge.py, so importing the game
registry never requires PySide6 (see that module's own docstring for why).

Unlike DREDGE, MHW *does* have a working loads()/dumps() (games/mhw.py) and
could just use cedit's generic tree editor + generic Inventory Editor
window. This window exists anyway because MHW's item pouch/storage/
equipment arrays are big, flat, fixed-size, id-only tables that are painful
to browse as a raw tree, and because a name-based item picker for something
this data-heavy deserves to be front and center rather than buried behind
"Inventory Editor..." - so PROFILE.custom_launcher opens this instead of
the generic editor for MHW specifically (see cedit.py's switch_game()).

Everything here is a thin Qt front end over games/mhw.py's own tested
loads()/dumps()/_CONTAINER_LABELS - no save-format logic is duplicated.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QTabWidget, QAbstractItemView, QGroupBox,
    QListWidget, QListWidgetItem, QInputDialog, QCheckBox,
)

from lib.base import GAME_WINDOW_SIZE, GAME_WINDOW_MIN, backup_file
from games import mhw

_HUNTER_FIELDS = [
    ("name", "Name", str),
    ("hunter_rank", "Hunter Rank", int),
    ("master_rank", "Master Rank", int),
    ("zeni", "Zenny", int),
    ("research_points", "Research Points", int),
    ("hunter_rank_xp", "HR XP", int),
    ("master_rank_xp", "MR XP", int),
    ("playtime_seconds", "Playtime (seconds)", int),
    ("room_preference", "Room Preference", int),
]


class _CatalogPickerDialog(QDialog):
    """A searchable picker over games/mhw.py's item_catalog() - lets item
    pouch/storage slots be filled by real item name instead of a bare id
    the user would otherwise have to look up by hand."""

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

        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(lambda *a: self._confirm())
        layout.addWidget(self.listw, stretch=1)

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
        self.listw.clear()
        needle = filter_text.strip().lower()
        for name, item_id in self._rows:
            if needle and needle not in name.lower() and needle not in item_id:
                continue
            entry = QListWidgetItem(f"{name}  (id {item_id})")
            entry.setData(Qt.UserRole, item_id)
            self.listw.addItem(entry)

    def _confirm(self):
        item = self.listw.currentItem()
        if item is not None:
            self.chosen_id = item.data(Qt.UserRole)
            self.accept()


class _SlotTab(QWidget):
    """One hunter's whole editing surface: info form, a container picker,
    and that container's slot table."""

    def __init__(self, window, slot_idx):
        super().__init__()
        self.window = window
        self.slot_idx = slot_idx
        self._field_edits = {}
        self._container_key = mhw._CONTAINER_LABELS[0][1]

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_hunter_form())

        inner_tabs = QTabWidget()
        inner_tabs.addTab(self._build_inventory_tab(), "Item Pouch / Storage")
        inner_tabs.addTab(self._build_equipment_tab(), "Equipment")
        layout.addWidget(inner_tabs, stretch=1)

    def _build_inventory_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        container_row = QHBoxLayout()
        container_row.addWidget(QLabel("Container:"))
        self.container_combo = QComboBox()
        for label, key in mhw._CONTAINER_LABELS:
            self.container_combo.addItem(label, key)
        self.container_combo.currentIndexChanged.connect(self._on_container_changed)
        container_row.addWidget(self.container_combo, stretch=1)
        fill_btn = QPushButton("Fill Selected Slot (browse names)...")
        fill_btn.clicked.connect(self._fill_selected)
        container_row.addWidget(fill_btn)
        clear_btn = QPushButton("Clear Selected Slot")
        clear_btn.clicked.connect(self._clear_selected)
        container_row.addWidget(clear_btn)
        layout.addLayout(container_row)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Slot #", "Item", "Amount"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 260)
        layout.addWidget(self.table, stretch=1)

        self._populate_table()
        return page

    def _build_equipment_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        top_row = QHBoxLayout()
        self.show_all_equipment = QCheckBox("Show all 2500 slots (default: owned/equipped only)")
        self.show_all_equipment.stateChanged.connect(lambda _s: self._populate_equipment_table())
        top_row.addWidget(self.show_all_equipment, stretch=1)
        set_btn = QPushButton("Set Equipment (browse names)...")
        set_btn.clicked.connect(self._set_equipment_selected)
        top_row.addWidget(set_btn)
        clear_btn = QPushButton("Clear Selected")
        clear_btn.clicked.connect(self._clear_equipment_selected)
        top_row.addWidget(clear_btn)
        layout.addLayout(top_row)

        self.equipment_table = QTableWidget()
        self.equipment_table.setColumnCount(7)
        self.equipment_table.setHorizontalHeaderLabels(
            ["Slot #", "Category", "Item", "Level", "Points", "Decos", "Pendant"]
        )
        self.equipment_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.equipment_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.equipment_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.equipment_table.setColumnWidth(0, 55)
        self.equipment_table.setColumnWidth(1, 70)
        self.equipment_table.setColumnWidth(2, 260)
        self.equipment_table.itemChanged.connect(self._on_equipment_cell_changed)
        layout.addWidget(self.equipment_table, stretch=1)

        note = QLabel(
            "Level/Points/Decos/Pendant are editable directly in the table (double-click a "
            "cell). Decos are 3 comma-separated deco ids (-1 = empty)."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self._equipment_rows = []  # table row -> real index into the 2500-entry array
        self._populate_equipment_table()
        return page

    def _build_hunter_form(self):
        box = QGroupBox("Hunter Info")
        form = QFormLayout(box)
        for key, label, _kind in _HUNTER_FIELDS:
            edit = QLineEdit()
            edit.editingFinished.connect(lambda k=key: self._commit_hunter_field(k))
            form.addRow(label, edit)
            self._field_edits[key] = edit
        self._refresh_hunter_form()
        return box

    def _refresh_hunter_form(self):
        hunter = self._hunter()
        for key, _label, _kind in _HUNTER_FIELDS:
            self._field_edits[key].setText(str(hunter.get(key, "")))

    def _hunter(self):
        return self.window.data["slots"][self.slot_idx]["hunter"]

    def _commit_hunter_field(self, key):
        edit = self._field_edits[key]
        kind = dict((fk, k) for fk, _label, k in _HUNTER_FIELDS)[key]
        text = edit.text()
        hunter = self._hunter()
        try:
            hunter[key] = int(text) if kind is int else text
        except ValueError:
            self.window.set_status(f"'{text}' isn't a whole number - {key} left unchanged.")
            self._refresh_hunter_form()
            return
        self.window.mark_dirty()
        if key == "name":
            self.window.refresh_tab_titles()

    def _on_container_changed(self, _index):
        self._container_key = self.container_combo.currentData()
        self._populate_table()

    def _slots(self):
        target_key = f"{self.slot_idx}:{self._container_key}"
        return mhw._resolve_container(self.window.data, target_key)

    def _populate_table(self):
        slots = self._slots()
        self.table.setRowCount(len(slots))
        for i, entry in enumerate(slots):
            item_id = entry["id"]
            name = mhw.item_name(item_id) if item_id else None
            label = f"{name} (id {item_id})" if name else (f"id {item_id}" if item_id else "(empty)")
            self.table.setItem(i, 0, QTableWidgetItem(str(i)))
            self.table.setItem(i, 1, QTableWidgetItem(label))
            self.table.setItem(i, 2, QTableWidgetItem(str(entry["amount"]) if item_id else ""))

    def _fill_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self.window, "MHW Editor", "Select a slot first.")
            return
        catalog = mhw.item_catalog(self.window.data)
        picker = _CatalogPickerDialog(self.window, catalog, "Choose an item")
        if picker.exec() != QDialog.Accepted or picker.chosen_id is None:
            return
        quantity, ok = _ask_quantity(self.window)
        if not ok:
            return
        slots = self._slots()
        slots[row] = {"id": int(picker.chosen_id), "amount": quantity}
        self.window.mark_dirty()
        self._populate_table()
        self.table.selectRow(row)

    def _clear_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self.window, "MHW Editor", "Select a slot first.")
            return
        slots = self._slots()
        slots[row] = {"id": 0, "amount": 0}
        self.window.mark_dirty()
        self._populate_table()
        self.table.selectRow(row)

    def _equipment(self):
        return self.window.data["slots"][self.slot_idx]["equipment"]

    def _populate_equipment_table(self):
        equipment = self._equipment()
        show_all = self.show_all_equipment.isChecked()
        rows = [
            (i, e) for i, e in enumerate(equipment)
            if show_all or e["category"] != -1
        ]
        self._equipment_rows = [i for i, _e in rows]

        self.equipment_table.blockSignals(True)
        self.equipment_table.setRowCount(len(rows))
        for row, (real_idx, e) in enumerate(rows):
            name = mhw.equipment_name(e["category"], e["type"], e["id"]) if e["category"] != -1 else None
            item_label = f"{name} (id {e['id']})" if name else (f"id {e['id']}" if e["category"] != -1 else "(empty)")
            category_label = mhw.EQUIP_CATEGORY_NAMES.get(e["category"], str(e["category"]))

            slot_item = QTableWidgetItem(str(real_idx))
            slot_item.setFlags(slot_item.flags() & ~Qt.ItemIsEditable)
            self.equipment_table.setItem(row, 0, slot_item)

            cat_item = QTableWidgetItem(category_label)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsEditable)
            self.equipment_table.setItem(row, 1, cat_item)

            item_item = QTableWidgetItem(item_label)
            item_item.setFlags(item_item.flags() & ~Qt.ItemIsEditable)
            self.equipment_table.setItem(row, 2, item_item)

            self.equipment_table.setItem(row, 3, QTableWidgetItem(str(e["level"])))
            self.equipment_table.setItem(row, 4, QTableWidgetItem(str(e["points"])))
            self.equipment_table.setItem(row, 5, QTableWidgetItem(",".join(str(d) for d in e["decos"])))
            self.equipment_table.setItem(row, 6, QTableWidgetItem(str(e["pendant"])))
        self.equipment_table.blockSignals(False)

    def _on_equipment_cell_changed(self, item):
        row = item.row()
        col = item.column()
        if row >= len(self._equipment_rows) or col not in (3, 4, 5, 6):
            return
        real_idx = self._equipment_rows[row]
        entry = self._equipment()[real_idx]
        text = item.text().strip()
        try:
            if col == 3:
                entry["level"] = int(text)
            elif col == 4:
                entry["points"] = int(text)
            elif col == 6:
                entry["pendant"] = int(text)
            elif col == 5:
                parts = [p.strip() for p in text.split(",")]
                if len(parts) != 3:
                    raise ValueError("need exactly 3 comma-separated deco ids")
                entry["decos"] = [int(p) for p in parts]
        except ValueError as e:
            self.window.set_status(f"'{text}' isn't valid here ({e}) - reverted.")
            self._populate_equipment_table()
            return
        self.window.mark_dirty()

    def _set_equipment_selected(self):
        row = self.equipment_table.currentRow()
        if row < 0:
            QMessageBox.information(self.window, "MHW Editor", "Select an equipment slot first.")
            return
        catalog = mhw.equipment_catalog()
        picker = _CatalogPickerDialog(self.window, catalog, "Choose equipment")
        if picker.exec() != QDialog.Accepted or picker.chosen_id is None:
            return
        try:
            category_str, type_str, id_str = picker.chosen_id.split(":")
        except ValueError:
            return
        real_idx = self._equipment_rows[row]
        entry = self._equipment()[real_idx]
        entry["category"] = int(category_str)
        entry["type"] = int(type_str)
        entry["id"] = int(id_str)
        self.window.mark_dirty()
        self._populate_equipment_table()

    def _clear_equipment_selected(self):
        row = self.equipment_table.currentRow()
        if row < 0:
            QMessageBox.information(self.window, "MHW Editor", "Select an equipment slot first.")
            return
        real_idx = self._equipment_rows[row]
        self._equipment()[real_idx] = {
            "sort_index": -1, "category": -1, "type": -1, "id": 0,
            "level": 0, "points": 0, "decos": [-1, -1, -1], "pendant": -1,
        }
        self.window.mark_dirty()
        self._populate_equipment_table()

    def refresh(self):
        self._refresh_hunter_form()
        self._populate_table()
        self._populate_equipment_table()


def _ask_quantity(parent):
    value, ok = QInputDialog.getInt(parent, "Quantity", "How many?", 1, 1, 999999)
    return value, ok


class MHWEditorWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Monster Hunter World: Iceborne Editor")
        self.resize(*GAME_WINDOW_SIZE)
        self.setMinimumSize(*GAME_WINDOW_MIN)

        self.save_path = None
        self.data = None
        self.dirty = False
        self._slot_tabs = []

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_top_bar())
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)
        self.status = QLabel("Open a SAVEDATA1000 file to begin.")
        layout.addWidget(self.status)

    def _build_top_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        open_btn = QPushButton("Open Save...")
        open_btn.clicked.connect(self._open_save)
        row.addWidget(open_btn)
        self.path_label = QLabel("(no file open)")
        row.addWidget(self.path_label, stretch=1)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        save_as_btn = QPushButton("Save As...")
        save_as_btn.clicked.connect(self._save_as)
        row.addWidget(save_as_btn)
        return bar

    def set_status(self, text):
        self.status.setText(text)

    def mark_dirty(self):
        self.dirty = True

    def refresh_tab_titles(self):
        for i, tab in enumerate(self._slot_tabs):
            name = tab._hunter().get("name") or f"Hunter {i + 1}"
            self.tabs.setTabText(i, name)

    def _open_save(self):
        if self.dirty and QMessageBox.question(
            self, "MHW Editor", "Discard unsaved changes and open a different file?"
        ) != QMessageBox.Yes:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open MHW Save", "", "MHW save files (SAVEDATA1000);;All files (*.*)"
        )
        if not path:
            return
        try:
            raw = open(path, "rb").read()
            self.data = mhw.loads(raw)
        except Exception as e:
            QMessageBox.critical(self, "MHW Editor", f"Couldn't load this save:\n{e}")
            return

        self.save_path = path
        self.dirty = False
        self.path_label.setText(path)
        self.tabs.clear()
        self._slot_tabs = []
        for slot_idx in range(len(self.data["slots"])):
            tab = _SlotTab(self, slot_idx)
            self._slot_tabs.append(tab)
            self.tabs.addTab(tab, f"Hunter {slot_idx + 1}")
        self.refresh_tab_titles()
        self.set_status(f"Loaded {os.path.basename(path)}.")

    def _write(self, path):
        try:
            out_bytes = mhw.dumps(self.data)
        except Exception as e:
            QMessageBox.critical(self, "MHW Editor", f"Couldn't encode this save:\n{e}")
            return False
        if os.path.exists(path):
            try:
                backup_file(path)
            except Exception as e:
                if QMessageBox.question(
                    self, "MHW Editor",
                    f"Couldn't create a backup before saving:\n{e}\n\nSave anyway?"
                ) != QMessageBox.Yes:
                    return False
        try:
            with open(path, "wb") as f:
                f.write(out_bytes)
        except Exception as e:
            QMessageBox.critical(self, "MHW Editor", f"Couldn't write this file:\n{e}")
            return False
        self.dirty = False
        self.set_status(f"Saved to {os.path.basename(path)}.")
        return True

    def _save(self):
        if self.data is None:
            QMessageBox.information(self, "MHW Editor", "Open a save first.")
            return
        if not self.save_path:
            self._save_as()
            return
        self._write(self.save_path)

    def _save_as(self):
        if self.data is None:
            QMessageBox.information(self, "MHW Editor", "Open a save first.")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save MHW Save As", self.save_path or "SAVEDATA1000",
            "MHW save files (SAVEDATA1000);;All files (*.*)"
        )
        if not path:
            return
        if self._write(path):
            self.save_path = path
            self.path_label.setText(path)

    def closeEvent(self, event):
        if self.dirty and QMessageBox.question(
            self, "MHW Editor", "Discard unsaved changes and close?"
        ) != QMessageBox.Yes:
            event.ignore()
            return
        super().closeEvent(event)


def launch(parent):
    window = MHWEditorWindow(parent)
    window.show()
    return window
