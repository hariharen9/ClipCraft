from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

def _make_eye_icon(visible: bool, size: int = 16) -> QIcon:
    """Generate a clean vector eye icon (no cheap emojis)."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    color = QColor(220, 222, 230) if visible else QColor(110, 112, 122)
    p.setPen(QPen(color, 1.3))

    path = QPainterPath()
    path.moveTo(2.0, size / 2.0)
    path.quadTo(size / 2.0, 3.0, size - 2.0, size / 2.0)
    path.quadTo(size / 2.0, size - 3.0, 2.0, size / 2.0)
    p.drawPath(path)

    if visible:
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(size / 2.0 - 2.2, size / 2.0 - 2.2, 4.4, 4.4))
    else:
        p.setPen(QPen(QColor(230, 80, 80), 1.6))
        p.drawLine(3, size - 3, size - 3, 3)

    p.end()
    return QIcon(pm)


class LayerStackWidget(QWidget):
    """Visual list displaying layers ordered from top (front) to bottom (back), with eye toggles."""

    layer_selected = Signal(str)
    visibility_toggled = Signal(str, bool)
    reordered = Signal(list)  # list of layer names in top-to-bottom order
    add_text_requested = Signal()
    delete_layer_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setMaximumHeight(140)
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #18181c; border: 1px solid #323238; border-radius: 4px; }"
            "QListWidget::item { padding: 1px 4px; border-bottom: 1px solid #232328; }"
            "QListWidget::item:selected { background-color: #2b3d58; border-radius: 3px; }"
        )
        self.list_widget.itemSelectionChanged.connect(self._on_item_selection_changed)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.list_widget)

        # Move Up / Down helper buttons, Add Text, Delete
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.up_button = QPushButton("▲ Forward")
        self.up_button.setFixedHeight(24)
        self.up_button.setStyleSheet("font-size: 11px;")
        self.up_button.setToolTip("Move layer up in stack (closer to front)")
        self.up_button.clicked.connect(self.move_selected_up)
        btn_row.addWidget(self.up_button)

        self.down_button = QPushButton("▼ Backward")
        self.down_button.setFixedHeight(24)
        self.down_button.setStyleSheet("font-size: 11px;")
        self.down_button.setToolTip("Move layer down in stack (closer to back)")
        self.down_button.clicked.connect(self.move_selected_down)
        btn_row.addWidget(self.down_button)

        self.add_text_button = QPushButton("＋ Text")
        self.add_text_button.setFixedHeight(24)
        self.add_text_button.setStyleSheet("font-size: 11px; font-weight: bold; color: #e5c07b;")
        self.add_text_button.setToolTip("Add a new editable text layer to this template")
        self.add_text_button.clicked.connect(self.add_text_requested.emit)
        btn_row.addWidget(self.add_text_button)

        self.delete_button = QPushButton("🗑")
        self.delete_button.setFixedSize(24, 24)
        self.delete_button.setStyleSheet("font-size: 11px;")
        self.delete_button.setToolTip("Delete selected layer")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self.delete_button)
        layout.addLayout(btn_row)

        self._updating = False
        self._layers_cache: dict[str, Any] = {}

    def _on_delete_clicked(self) -> None:
        name = self.current_layer_name()
        if name and name not in ("background", "main"):
            self.delete_layer_requested.emit(name)

    def _create_item_widget(self, name: str, layer: dict[str, Any]) -> QWidget:
        widget = QWidget()
        w_layout = QHBoxLayout(widget)
        w_layout.setContentsMargins(2, 0, 4, 0)
        w_layout.setSpacing(6)

        visible = bool(layer.get("visible", True))
        eye_btn = QPushButton()
        eye_btn.setIcon(_make_eye_icon(visible))
        eye_btn.setIconSize(QSize(16, 16))
        eye_btn.setFixedSize(22, 22)
        eye_btn.setToolTip("Hide layer" if visible else "Show layer")
        eye_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
            "QPushButton:hover { background-color: #353540; border-radius: 3px; }"
        )
        eye_btn.clicked.connect(lambda checked=False, n=name: self._toggle_eye(n))
        w_layout.addWidget(eye_btn)

        # Clean text-based type indicator
        kind = layer.get("kind", "video")
        if kind == "video":
            badge_text = "[VID]"
            badge_color = "#78a0c8"
        elif kind == "text":
            badge_text = "[TXT]"
            badge_color = "#e5c07b"
        else:
            badge_text = "[IMG]"
            badge_color = "#98c379"
        kind_lbl = QLabel(badge_text)
        kind_lbl.setStyleSheet(f"color: {badge_color}; font-size: 10px; font-weight: bold;")
        kind_lbl.setFixedWidth(30)
        w_layout.addWidget(kind_lbl)

        # Name label
        title = name.replace("_", " ").title()
        name_lbl = QLabel(title)
        name_lbl.setStyleSheet("font-weight: 500; font-size: 12px; color: #eee;")
        w_layout.addWidget(name_lbl, 1)

        return widget

    def populate(self, layers: dict[str, Any], active_name: str | None = None):
        """Populate list from layers config. Top in list = highest Z-order (front)."""
        self._layers_cache = layers
        self._updating = True
        self.list_widget.clear()

        sorted_layers = sorted(
            [(k, v) for k, v in layers.items() if k != "background"],
            key=lambda pair: pair[1].get("z", 0),
            reverse=True
        )
        active_row = 0
        for row, (name, layer) in enumerate(sorted_layers):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSizeHint(QSize(0, 26))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, self._create_item_widget(name, layer))

            if active_name and name == active_name:
                active_row = row

        self._updating = False
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(active_row)

    def select_layer(self, name: str):
        if self._updating:
            return
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                if self.list_widget.currentRow() != row:
                    self._updating = True
                    self.list_widget.setCurrentRow(row)
                    self._updating = False
                break

    def current_layer_name(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_item_selection_changed(self):
        if self._updating:
            return
        name = self.current_layer_name()
        if hasattr(self, "delete_button"):
            self.delete_button.setEnabled(bool(name and name not in ("background", "main")))
        if name:
            self.layer_selected.emit(name)

    def _toggle_eye(self, name: str):
        layer = self._layers_cache.get(name, {})
        new_visible = not bool(layer.get("visible", True))
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                w = self.list_widget.itemWidget(item)
                if w:
                    btn = w.findChild(QPushButton)
                    if btn:
                        btn.setIcon(_make_eye_icon(new_visible))
                        btn.setToolTip("Hide layer" if new_visible else "Show layer")
                break
        self.visibility_toggled.emit(name, new_visible)

    def _on_rows_moved(self, parent, start, end, destination, row):
        if self._updating:
            return
        # After internal drag-drop, Qt may drop the custom widget on the moved item.
        # Ensure all items still have their widget attached.
        self._ensure_all_item_widgets()
        self._emit_reordered()

    def _ensure_all_item_widgets(self):
        for r in range(self.list_widget.count()):
            item = self.list_widget.item(r)
            if not self.list_widget.itemWidget(item):
                name = item.data(Qt.ItemDataRole.UserRole)
                layer = self._layers_cache.get(name, {})
                self.list_widget.setItemWidget(item, self._create_item_widget(name, layer))

    def _emit_reordered(self):
        order = []
        for r in range(self.list_widget.count()):
            it = self.list_widget.item(r)
            name = it.data(Qt.ItemDataRole.UserRole)
            if name:
                order.append(name)
        self.reordered.emit(order)

    def move_selected_up(self):
        """Move item up in list (closer to front/top Z) safely without losing widget."""
        row = self.list_widget.currentRow()
        if row <= 0:
            return
        names = [self.list_widget.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.list_widget.count())]
        selected_name = names[row]
        # Swap with predecessor
        names[row], names[row - 1] = names[row - 1], names[row]

        self._rebuild_from_names(names, selected_name)
        self._emit_reordered()

    def move_selected_down(self):
        """Move item down in list (closer to back/lower Z) safely without losing widget."""
        row = self.list_widget.currentRow()
        if row < 0 or row >= self.list_widget.count() - 1:
            return
        names = [self.list_widget.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.list_widget.count())]
        selected_name = names[row]
        # Swap with successor
        names[row], names[row + 1] = names[row + 1], names[row]

        self._rebuild_from_names(names, selected_name)
        self._emit_reordered()

    def _rebuild_from_names(self, names: list[str], selected_name: str):
        self._updating = True
        self.list_widget.clear()
        target_row = 0
        for r, name in enumerate(names):
            layer = self._layers_cache.get(name, {})
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSizeHint(QSize(0, 26))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, self._create_item_widget(name, layer))
            if name == selected_name:
                target_row = r
        self._updating = False
        self.list_widget.setCurrentRow(target_row)
