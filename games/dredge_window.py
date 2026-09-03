"""
DREDGE's actual editor window - split out from games/dredge.py so that
importing the game registry (games/__init__.py, and therefore anything
that just wants a GameProfile - the CLI, tests, etc.) never requires
PySide6 to be installed. Only actually opening this window does, and by
then the whole app is already running under PySide6 anyway (see
games/dredge.py's `launch()`, which imports this module lazily).

Everything else about DREDGE's save format and scope is documented in
games/dredge.py's own module docstring, not repeated here - this file is
purely the Qt-dependent half of that same feature.
"""

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lib import dredge_client as bridge
from lib.base import GAME_WINDOW_MIN, GAME_WINDOW_SIZE

CONTAINERS = ["inventory", "storage", "overflowStorage", "nonSpatialItems"]
VARIABLE_GROUPS = ["decimals", "integers", "floats", "strings", "booleans"]
CELL_PX = 28


def _rotate_dims(dims, rotation):
    """Port of upstream grid.mjs rotateDimensions: list of {x,y} cell offsets."""
    cells = [dict(c) for c in dims] if dims else [{"x": 0, "y": 0}]
    turns = (rotation % 360) // 90
    for _ in range(turns):
        cells = [{"x": c.get("y", 0), "y": -c.get("x", 0)} for c in cells]
    return cells


class _CatalogPickerDialog(QDialog):
    """A searchable picker over the real item catalog (name, id, and real
    footprint size) instead of asking the user to type a raw item id from
    memory."""

    def __init__(self, parent, rows, title="Choose an item"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 420)
        self._rows = rows  # [(name, item_id, size_label), ...]
        self.chosen_id = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self._populate)
        layout.addWidget(self.search_edit)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "ID", "Size"])
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 140)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *a: self._confirm())
        layout.addWidget(self.tree, stretch=1)

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
        for name, item_id, size in self._rows:
            if needle and needle not in name.lower() and needle not in item_id.lower():
                continue
            item = QTreeWidgetItem([name, item_id, size])
            self.tree.addTopLevelItem(item)

    def _confirm(self):
        item = self.tree.currentItem()
        if item is not None:
            self.chosen_id = item.text(1)
            self.accept()


class _SavesListDialog(QDialog):
    def __init__(self, parent, saves):
        super().__init__(parent)
        self.setWindowTitle("Discovered saves")
        self.resize(640, 320)
        self.chosen_path = None

        layout = QVBoxLayout(self)
        self.listw = QListWidget()
        for p in saves:
            self.listw.addItem(QListWidgetItem(str(p)))
        self.listw.itemDoubleClicked.connect(lambda *a: self._confirm())
        layout.addWidget(self.listw)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._confirm)
        button_row.addWidget(open_btn)
        layout.addLayout(button_row)

        self._saves = saves

    def _confirm(self):
        row = self.listw.currentRow()
        if row >= 0:
            self.chosen_path = str(self._saves[row])
            self.accept()


class _InventoryScene(QGraphicsScene):
    """Handles mouse press/move/release for dragging and double-click for
    rotating items on the grid; delegates the actual logic back to the
    owning window."""

    def __init__(self, window):
        super().__init__()
        self.window = window

    def mousePressEvent(self, event):
        self.window._on_canvas_press(event.scenePos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.window._drag_item is not None:
            self.window._on_canvas_drag(event.scenePos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.window._on_canvas_release(event.scenePos())
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.window._on_canvas_rotate(event.scenePos())
        super().mouseDoubleClickEvent(event)


class DredgeEditorWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("DREDGE Save Editor")
        self.resize(*GAME_WINDOW_SIZE)
        self.setMinimumSize(*GAME_WINDOW_MIN)

        self.save_path = None
        self.managed_dir = bridge.find_managed_dir()
        self.snapshot = None            # last bridge inspect() result
        self.pending_vars = {}          # {group: {key: value}}
        self.pending_ops = []           # list of inventory op dicts
        self.item_catalog = bridge.load_item_catalog()
        self.grid_configs = bridge.load_grid_configs()

        self._drag_item = None
        self._drag_preview = None  # (x, y) candidate cell while dragging, before it's committed

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_top_bar())
        layout.addWidget(self._build_body(), stretch=1)
        self.status = QLabel("")
        layout.addWidget(self.status)

        self._set_status(
            "Managed dir: " + (str(self.managed_dir) if self.managed_dir else
                                "NOT FOUND - set it manually before opening a save.")
        )

    # ------------------------------------------------------------- chrome

    def _build_top_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        open_btn = QPushButton("Open Save...")
        open_btn.clicked.connect(self.open_save)
        row.addWidget(open_btn)
        discover_btn = QPushButton("Discover Saves...")
        discover_btn.clicked.connect(self.discover_saves)
        row.addWidget(discover_btn)
        managed_btn = QPushButton("Managed Dir...")
        managed_btn.clicked.connect(self.pick_managed_dir)
        row.addWidget(managed_btn)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.reload_save)
        row.addWidget(reload_btn)

        self.path_label = QLabel("No save loaded")
        row.addWidget(self.path_label)

        row.addStretch(1)
        apply_btn = QPushButton("Save & Apply Patch")
        apply_btn.clicked.connect(self.apply_patch)
        row.addWidget(apply_btn)
        return bar

    def _build_body(self):
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_vars_tab(), "Variables")
        self.tabs.addTab(self._build_inventory_tab(), "Inventory")
        return self.tabs

    def _set_status(self, text):
        self.status.setText(text)

    # -------------------------------------------------------- open / load

    def discover_saves(self):
        saves = bridge.discover_saves()
        if not saves:
            QMessageBox.information(self, "DREDGE", "No saves found in the default DREDGE saves folder.")
            return
        dialog = _SavesListDialog(self, saves)
        if dialog.exec() == QDialog.Accepted and dialog.chosen_path:
            self._load(dialog.chosen_path)

    def open_save(self):
        default_dir = None
        saves = bridge.discover_saves()
        if saves:
            default_dir = str(saves[0].parent)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DREDGE save", default_dir or "",
            "DREDGE save files (*.bin);;All files (*.*)",
        )
        if path:
            self._load(path)

    def pick_managed_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select DREDGE's Managed folder (.../DREDGE_Data/Managed)"
        )
        if d:
            self.managed_dir = d
            self._set_status(f"Managed dir: {d}")

    def reload_save(self):
        if self.save_path:
            self._load(self.save_path)

    def _load(self, path):
        if not self.managed_dir:
            QMessageBox.critical(
                self, "DREDGE",
                "No Managed directory found or set. Use 'Managed Dir...' to point at "
                "your DREDGE install's .../DREDGE_Data/Managed (or .../Contents/Resources/Data/Managed on macOS).",
            )
            return
        try:
            self._set_status("Inspecting save (building the bridge on first run can take a minute)...")
            result = bridge.inspect_save(path, self.managed_dir)
        except bridge.DredgeBridgeError as exc:
            QMessageBox.critical(self, "DREDGE bridge error", str(exc))
            self._set_status("Inspect failed - see error dialog.")
            return
        self.save_path = path
        self.snapshot = result
        self.pending_vars = {}
        self.pending_ops = []
        self.path_label.setText(f"{result.get('fileName')} ({result.get('size')} bytes)")
        self._refresh_vars_tree()
        self._refresh_inventory()
        self._set_status(f"Loaded. lastSavedTime={result.get('lastSavedTime')} version={result.get('version')}")

    # ------------------------------------------------------------- vars UI

    def _build_vars_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.vars_tree = QTreeWidget()
        self.vars_tree.setColumnCount(3)
        self.vars_tree.setHeaderLabels(["Group", "Key", "Value"])
        self.vars_tree.setColumnWidth(0, 100)
        self.vars_tree.setColumnWidth(1, 260)
        self.vars_tree.setColumnWidth(2, 260)
        self.vars_tree.itemDoubleClicked.connect(self._edit_variable)
        layout.addWidget(self.vars_tree, stretch=1)
        layout.addWidget(QLabel(
            "Double-click a value to change it. Only keys that already exist in the save can be edited."
        ))
        return tab

    def _refresh_vars_tree(self):
        self.vars_tree.clear()
        if not self.snapshot:
            return
        variables = self.snapshot.get("variables", {})
        changed_brush = QBrush(QColor("#fff3b0"))
        for group in VARIABLE_GROUPS:
            for key, value in (variables.get(group) or {}).items():
                display = self.pending_vars.get(group, {}).get(key, value)
                item = QTreeWidgetItem([group, key, str(display)])
                item.setData(0, Qt.UserRole, (group, key))
                if key in self.pending_vars.get(group, {}):
                    for col in range(3):
                        item.setBackground(col, changed_brush)
                self.vars_tree.addTopLevelItem(item)

    def _edit_variable(self, item, column):
        group, key = item.data(0, Qt.UserRole)
        original = (self.snapshot.get("variables", {}).get(group) or {}).get(key)
        current = self.pending_vars.get(group, {}).get(key, original)
        if group == "booleans":
            new_value = not current
        else:
            prompt = f"New value for {group}.{key} (current: {current!r})"
            raw, ok = QInputDialog.getText(self, "Edit variable", prompt, text=str(current))
            if not ok:
                return
            try:
                if group == "strings":
                    new_value = raw
                elif group == "integers":
                    new_value = int(raw.strip())
                else:  # decimals, floats
                    new_value = float(raw.strip())
            except ValueError:
                QMessageBox.critical(self, "DREDGE", f"'{raw}' isn't a valid value for {group}.")
                return
        self.pending_vars.setdefault(group, {})[key] = new_value
        self._refresh_vars_tree()

    # -------------------------------------------------------- inventory UI

    def _build_inventory_tab(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)

        top = QWidget()
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(QLabel("Container:"))
        self.container_combo = QComboBox()
        self.container_combo.addItems(CONTAINERS)
        self.container_combo.currentTextChanged.connect(lambda *a: self._refresh_inventory())
        top_row.addWidget(self.container_combo)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        top_row.addWidget(remove_btn)
        dup_btn = QPushButton("Duplicate Selected...")
        dup_btn.clicked.connect(self._duplicate_selected)
        top_row.addWidget(dup_btn)
        spawn_btn = QPushButton("Spawn Item...")
        spawn_btn.clicked.connect(self._spawn_item)
        top_row.addWidget(spawn_btn)
        top_row.addStretch(1)
        outer.addWidget(top)

        splitter = QSplitter(Qt.Horizontal)

        self.scene = _InventoryScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(self.view.renderHints())
        splitter.addWidget(self.view)

        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        # A plain table, not a QTreeWidget - this is flat tabular data (no
        # nesting), and a tree view reserves indentation/expand-arrow space
        # in its first column that made the Index column cramped and easy
        # to misread once indexes hit double digits.
        self.item_table = QTableWidget()
        self.item_table.setColumnCount(7)
        self.item_table.setHorizontalHeaderLabels(["Index", "Name", "ID", "Size", "X", "Y", "Z"])
        for col, width in enumerate((55, 170, 130, 50, 40, 40, 40)):
            self.item_table.setColumnWidth(col, width)
        self.item_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.item_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.item_table.verticalHeader().setVisible(False)
        self.item_table.itemSelectionChanged.connect(self._redraw_grid)
        list_layout.addWidget(self.item_table)
        splitter.addWidget(list_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        # As in cedit.py's own splitter: stretch factors alone only control
        # how *extra* space is divided on resize, not the initial split - the
        # item table's own columns (55+170+130+50+40+40+40 = 525px) need
        # more room than a plain 60/40 of a modest starting width gives it.
        splitter.setSizes([650, 525])
        outer.addWidget(splitter, stretch=1)

        hint = QLabel(
            "Drag a square to move it - green while over free space, red if it would overlap another "
            "item, leave the grid, or land on a slot this boat's current hull tier / this container "
            "doesn't actually have (it snaps back on release). Double-click to rotate 90°. Shaded cells "
            "aren't usable at all. All of this needs data/dredge/manifest.json (real shapes and cargo "
            "layouts per hull-tier variable) - without it, items show as single cells on a plain rectangle."
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        return tab

    def _current_items(self, container=None):
        if not self.snapshot:
            return []
        container = container if container is not None else self.container_combo.currentText()
        if container == "nonSpatialItems":
            return self.snapshot.get("nonSpatialItems", [])
        return (self.snapshot.get(container) or {}).get("items", [])

    def _effective_xyz(self, container, index, item):
        """An item's x/y/z, honoring any not-yet-applied pending move op."""
        item_id = item.get("values", {}).get("id")
        for op in reversed(self.pending_ops):
            if op.get("container") == container and op.get("index") == index and op.get("id") == item_id \
                    and op.get("action") == "move":
                return op["x"], op["y"], op["z"]
        values = item.get("values", {})
        return values.get("x", 0), values.get("y", 0), values.get("z", 0)

    def _shape_size_label(self, item_id):
        dims = self._asset_info(item_id)["dimensions"]
        width = max(c["x"] for c in dims) - min(c["x"] for c in dims) + 1
        height = max(c["y"] for c in dims) - min(c["y"] for c in dims) + 1
        return f"{width}x{height}"

    def _asset_info(self, item_id):
        """Catalog entry for an item id, with the same permissive fallback
        upstream uses for items missing (or incomplete) in the catalog -
        unknown shape/type is assumed to be a 1-cell item that fits
        anywhere, same as upstream's itemAsset()."""
        entry = self.item_catalog.get(item_id) or {}
        return {
            "id": entry.get("id", item_id),
            "name": entry.get("name") or item_id,
            "sprite": entry.get("sprite"),
            "dimensions": entry.get("dimensions") or [{"x": 0, "y": 0}],
            "itemType": entry.get("itemType", -1),
            "itemSubtype": entry.get("itemSubtype", -1),
        }

    def _footprint(self, item_id, x, y, z):
        """Absolute grid cells an item occupies, using its real shape from the
        item catalog if we have one, else a 1-cell fallback."""
        dims = self._asset_info(item_id)["dimensions"]
        cells = _rotate_dims(dims, z)
        return [(x + c["x"], y + c["y"]) for c in cells]

    def _current_hull_tier(self):
        """The boat's cargo grid depends on this variable (see
        lib/dredge_client.grid_config_name_for) - pick up any not-yet-applied
        edit to it first, same as everywhere else pending edits are honored."""
        pending = self.pending_vars.get("integers", {}).get("hull-tier")
        if pending is not None:
            return pending
        return (self.snapshot.get("variables", {}).get("integers", {}) or {}).get("hull-tier", 1)

    def _grid_config_for(self, container):
        name = bridge.grid_config_name_for(container, self._current_hull_tier())
        return self.grid_configs.get(name) if name else None

    def _grid_size(self, container):
        config = self._grid_config_for(container)
        if config and config.get("rows") and config.get("columns"):
            return config["rows"], config["columns"]
        grid_info = self.snapshot.get(container) or {}
        return grid_info.get("rows") or 20, grid_info.get("columns") or 20

    def _occupied_cells(self, container, exclude_idx=None):
        """{(x, y): idx} of every cell other items currently occupy (honoring
        pending moves/removals), so placement checks see real occupied space -
        not just each item's top-left corner."""
        removed = {op["index"] for op in self.pending_ops
                   if op["action"] == "remove" and op["container"] == container}
        occupied = {}
        for idx, item in enumerate(self._current_items(container)):
            if idx in removed or idx == exclude_idx:
                continue
            x, y, z = self._effective_xyz(container, idx, item)
            item_id = item.get("values", {}).get("id", "?")
            for cell in self._footprint(item_id, x, y, z):
                occupied[cell] = idx
        return occupied

    def _placement_ok(self, container, idx, item_id, x, y, z):
        """Bounds + real-usable-cell + collision check (not just a rows x
        columns rectangle and not just each item's top-left corner), so
        drags/spawns/duplicates respect the boat's actual current hull-tier
        layout. Returns (ok, reason)."""
        rows, cols = self._grid_size(container)
        cells = self._footprint(item_id, x, y, z)
        for cx, cy in cells:
            if not (0 <= cx < cols and 0 <= cy < rows):
                return False, "out of bounds"
        config = self._grid_config_for(container)
        if config:
            asset = self._asset_info(item_id)
            for cx, cy in cells:
                if not bridge.cell_accepts(config, cx, cy, asset["itemType"], asset["itemSubtype"]):
                    return False, "not a usable slot here (blocked, or wrong item type for this cell)"
        occupied = self._occupied_cells(container, exclude_idx=idx)
        for cell in cells:
            if cell in occupied:
                return False, "space already occupied"
        return True, ""

    def _first_free_cell(self, container, item_id, exclude_idx=None):
        """Left-to-right, top-to-bottom scan for a spot this item's real
        footprint fits without overlapping anything else."""
        rows, cols = self._grid_size(container)
        for y in range(rows):
            for x in range(cols):
                ok, _ = self._placement_ok(container, exclude_idx, item_id, x, y, 0)
                if ok:
                    return x, y
        return None

    def _refresh_inventory(self):
        self.item_table.setRowCount(0)
        if not self.snapshot:
            self._redraw_grid()
            return
        container = self.container_combo.currentText()
        items = self._current_items()
        removed = {op["index"] for op in self.pending_ops
                   if op["action"] == "remove" and op["container"] == container}
        visible_items = [(idx, item) for idx, item in enumerate(items) if idx not in removed]
        self.item_table.setRowCount(len(visible_items))
        for row, (idx, item) in enumerate(visible_items):
            item_id = item.get("values", {}).get("id", "?")
            x, y, z = self._effective_xyz(container, idx, item) if container != "nonSpatialItems" else (0, 0, 0)
            name = self._asset_info(item_id)["name"]
            size = self._shape_size_label(item_id) if container != "nonSpatialItems" else "-"
            for col, text in enumerate((str(idx), name, item_id, size, str(x), str(y), str(z))):
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    cell.setData(Qt.UserRole, idx)
                self.item_table.setItem(row, col, cell)
        self._redraw_grid()

    def _selected_index(self):
        row = self.item_table.currentRow()
        if row < 0:
            return None
        cell = self.item_table.item(row, 0)
        return cell.data(Qt.UserRole) if cell is not None else None

    def _select_index(self, idx):
        for row in range(self.item_table.rowCount()):
            cell = self.item_table.item(row, 0)
            if cell is not None and cell.data(Qt.UserRole) == idx:
                self.item_table.setCurrentCell(row, 0)
                return

    def _redraw_grid(self):
        self.scene.clear()
        if not self.snapshot:
            return
        container = self.container_combo.currentText()
        if container == "nonSpatialItems":
            return
        grid_line = QColor("#d0d0d0")
        blocked_fill = QBrush(QColor("#ececec"))
        outline = QPen(QColor("#333333"))
        label_font = QFont()
        label_font.setPointSize(7)

        rows, cols = self._grid_size(container)
        self.scene.setSceneRect(0, 0, cols * CELL_PX, rows * CELL_PX)
        config = self._grid_config_for(container)
        if config:
            for y in range(rows):
                for x in range(cols):
                    if not bridge.cell_accepts(config, x, y, -1, -1):
                        self.scene.addRect(
                            x * CELL_PX, y * CELL_PX, CELL_PX, CELL_PX,
                            QPen(Qt.NoPen), blocked_fill,
                        )
        line_pen = QPen(grid_line)
        for r in range(rows + 1):
            self.scene.addLine(0, r * CELL_PX, cols * CELL_PX, r * CELL_PX, line_pen)
        for c in range(cols + 1):
            self.scene.addLine(c * CELL_PX, 0, c * CELL_PX, rows * CELL_PX, line_pen)

        removed = {op["index"] for op in self.pending_ops
                   if op["action"] == "remove" and op["container"] == container}
        selected_idx = self._selected_index()

        for idx, item in enumerate(self._current_items()):
            if idx in removed:
                continue
            item_id = item.get("values", {}).get("id", "?")
            if idx == self._drag_item and self._drag_preview is not None:
                x, y = self._drag_preview
                _, _, z = self._effective_xyz(container, idx, item)
                ok, _ = self._placement_ok(container, idx, item_id, x, y, z)
                color = QColor("#7fd18a") if ok else QColor("#e07a7a")  # green while draggable, red if it can't drop
            else:
                x, y, z = self._effective_xyz(container, idx, item)
                color = QColor("#5b8def") if idx == selected_idx else QColor("#e2c25a")
            cells = self._footprint(item_id, x, y, z)
            for cx, cy in cells:
                self.scene.addRect(
                    cx * CELL_PX + 1, cy * CELL_PX + 1, CELL_PX - 2, CELL_PX - 2,
                    outline, QBrush(color),
                )
            # Label on one of the shape's own painted cells, not the raw
            # (x, y) anchor - an item's dimensions aren't guaranteed to
            # include the (0, 0) offset, so the anchor cell itself can sit
            # outside the actual footprint (that's what made the label look
            # "detached" from the highlighted shape).
            label_cx, label_cy = min(cells)  # topmost-leftmost occupied cell
            text = self.scene.addSimpleText(item_id[:3], label_font)
            text.setPos(label_cx * CELL_PX + 3, label_cy * CELL_PX + 3)

    def _item_at_cell(self, container, col, row):
        for idx, item in enumerate(self._current_items()):
            item_id = item.get("values", {}).get("id", "?")
            x, y, z = self._effective_xyz(container, idx, item)
            if (col, row) in self._footprint(item_id, x, y, z):
                return idx
        return None

    def _cell_from_scene_pos(self, pos):
        return int(pos.x() // CELL_PX), int(pos.y() // CELL_PX)

    def _on_canvas_press(self, pos):
        container = self.container_combo.currentText()
        if container == "nonSpatialItems":
            return
        col, row = self._cell_from_scene_pos(pos)
        idx = self._item_at_cell(container, col, row)
        if idx is not None:
            self._drag_item = idx
            self._drag_preview = None
            self._select_index(idx)
        else:
            self._drag_item = None

    def _on_canvas_drag(self, pos):
        if self._drag_item is None:
            return
        self._drag_preview = self._cell_from_scene_pos(pos)
        self._redraw_grid()

    def _on_canvas_release(self, pos):
        if self._drag_item is not None and self._drag_preview is not None:
            self._commit_move(self._drag_item, *self._drag_preview, rotate=None)
        self._drag_item = None
        self._drag_preview = None
        self._redraw_grid()

    def _on_canvas_rotate(self, pos):
        container = self.container_combo.currentText()
        col, row = self._cell_from_scene_pos(pos)
        idx = self._item_at_cell(container, col, row)
        if idx is None:
            return
        item = self._current_items()[idx]
        x, y, z = self._effective_xyz(container, idx, item)
        self._commit_move(idx, x, y, rotate=(z + 90) % 360)

    def _commit_move(self, index, x, y, rotate):
        """Validates a proposed position/rotation against the grid's real
        bounds and other items' actual footprints before committing it as a
        pending move. Silently no-ops (leaves the item where it was) if the
        spot isn't actually free."""
        container = self.container_combo.currentText()
        item = self._current_items()[index]
        item_id = item.get("values", {}).get("id")
        cur_x, cur_y, cur_z = self._effective_xyz(container, index, item)
        new_x, new_y = max(0, x), max(0, y)
        new_z = cur_z if rotate is None else rotate
        if (new_x, new_y, new_z) == (cur_x, cur_y, cur_z):
            return
        ok, reason = self._placement_ok(container, index, item_id, new_x, new_y, new_z)
        if not ok:
            self._set_status(f"Can't place {item_id} there - {reason}.")
            return
        self.pending_ops = [op for op in self.pending_ops
                             if not (op["action"] == "move" and op["container"] == container
                                     and op["index"] == index and op["id"] == item_id)]
        self.pending_ops.append({
            "action": "move", "container": container, "index": index, "id": item_id,
            "x": new_x, "y": new_y, "z": new_z,
        })
        self._set_status(f"Queued move: {item_id} -> ({new_x}, {new_y}, {new_z}°).")
        self._refresh_inventory()

    def _remove_selected(self):
        index = self._selected_index()
        if index is None:
            return
        container = self.container_combo.currentText()
        item = self._current_items()[index]
        item_id = item.get("values", {}).get("id")
        if QMessageBox.question(
            self, "DREDGE", f"Remove {item_id} ({container}[{index}])?"
        ) != QMessageBox.Yes:
            return
        self.pending_ops = [op for op in self.pending_ops
                             if not (op["container"] == container and op["index"] == index)]
        self.pending_ops.append({"action": "remove", "container": container, "index": index, "id": item_id})
        self._refresh_inventory()

    def _duplicate_selected(self):
        index = self._selected_index()
        if index is None:
            return
        container = self.container_combo.currentText()
        item = self._current_items()[index]
        item_id = item.get("values", {}).get("id")
        name = self._asset_info(item_id)["name"]
        target, ok = QInputDialog.getItem(
            self, "Duplicate item",
            f"Duplicate {name} ({item_id}) into which container?",
            CONTAINERS, CONTAINERS.index(container) if container in CONTAINERS else 0, False,
        )
        if not ok or target not in CONTAINERS:
            return
        op = {"action": "duplicate", "container": container, "index": index, "id": item_id, "target": target}
        if target != "nonSpatialItems":
            spot = self._first_free_cell(target, item_id)
            if spot is None:
                QMessageBox.critical(self, "DREDGE", f"No free space for {item_id} in {target}.")
                return
            op["x"], op["y"], op["z"] = spot[0], spot[1], 0
        self.pending_ops.append(op)
        QMessageBox.information(self, "DREDGE", "Duplicate queued. It will appear after you Save & Apply Patch and reload.")

    def _pick_catalog_item(self, title="Choose an item"):
        rows = sorted(
            ((info.get("name") or item_id), item_id, self._shape_size_label(item_id))
            for item_id, info in self.item_catalog.items()
        )
        dialog = _CatalogPickerDialog(self, rows, title)
        if dialog.exec() == QDialog.Accepted:
            return dialog.chosen_id
        return None

    def _spawn_item(self):
        if not self.item_catalog:
            QMessageBox.information(
                self, "DREDGE",
                "No item catalog loaded (data/dredge/manifest.json is missing or empty), so cedit "
                "doesn't know any real item names/ids/shapes. Run the upstream project's "
                "tools/extract_game_assets.py against your local install and drop manifest.json there "
                "to enable spawning.",
            )
            return
        container = self.container_combo.currentText()
        if container == "nonSpatialItems":
            QMessageBox.critical(self, "DREDGE", "Can't spawn directly into cabin (non-spatial) items here.")
            return
        item_id = self._pick_catalog_item("Spawn item")
        if not item_id:
            return
        spot = self._first_free_cell(container, item_id)
        if spot is None:
            QMessageBox.critical(self, "DREDGE", f"No free space for {item_id} in {container}.")
            return
        self.pending_ops.append({
            "action": "spawn", "id": item_id, "target": container, "x": spot[0], "y": spot[1], "z": 0,
        })
        name = self._asset_info(item_id)["name"]
        QMessageBox.information(self, "DREDGE", f"Spawn of {name} queued. It will appear after you Save & Apply Patch and reload.")

    # -------------------------------------------------------------- apply

    def apply_patch(self):
        if not self.snapshot or not self.save_path:
            QMessageBox.information(self, "DREDGE", "Load a save first.")
            return
        if not self.pending_vars and not self.pending_ops:
            QMessageBox.information(self, "DREDGE", "No changes to apply.")
            return
        if QMessageBox.question(
            self, "DREDGE",
            "Make sure DREDGE is fully closed before writing to the save file. Continue?",
        ) != QMessageBox.Yes:
            return
        try:
            checked_vars = bridge.validate_patch(self.snapshot.get("variables", {}), self.pending_vars)
            checked_ops = bridge.validate_inventory_ops(self.snapshot, self.pending_ops, self.item_catalog)
        except ValueError as exc:
            QMessageBox.critical(self, "DREDGE", f"Patch rejected before touching the file: {exc}")
            return

        patch = {"variables": checked_vars, "inventoryOps": checked_ops}
        with tempfile.TemporaryDirectory(prefix="dredge-editor-") as tmpdir:
            patch_path = os.path.join(tmpdir, "patch.json")
            try:
                self._set_status("Applying patch via the DREDGE bridge...")
                result = bridge.edit_save(self.save_path, self.managed_dir, patch, patch_path)
            except bridge.DredgeBridgeError as exc:
                QMessageBox.critical(self, "DREDGE bridge error", str(exc))
                self._set_status("Apply failed - see error dialog. Nothing was written.")
                return

        backup_path = result.get("backupPath")
        QMessageBox.information(self, "DREDGE", f"Save updated.\nBackup written to:\n{backup_path}")
        self.snapshot = result.get("save", result)
        self.pending_vars = {}
        self.pending_ops = []
        self._refresh_vars_tree()
        self._refresh_inventory()
        self._set_status(f"Applied. Backup: {backup_path}")


def launch(parent):
    window = DredgeEditorWindow(parent)
    window.show()
    # Keep a reference on the parent so the window isn't garbage-collected
    # the instant `launch` returns.
    parent._dredge_window = window
