from __future__ import annotations

from typing import Callable, Any

import cv2
import numpy as np
import qtawesome as qta
from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..preview import to_qimage_array
from .constants import get_app_icon

class VisualCropHandleItem(QGraphicsRectItem):
    """Corner/edge resize handle for the visual crop rectangle."""

    CURSORS = {
        "nw": Qt.CursorShape.SizeFDiagCursor,
        "n": Qt.CursorShape.SizeVerCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor,
        "e": Qt.CursorShape.SizeHorCursor,
        "se": Qt.CursorShape.SizeFDiagCursor,
        "s": Qt.CursorShape.SizeVerCursor,
        "sw": Qt.CursorShape.SizeBDiagCursor,
        "w": Qt.CursorShape.SizeHorCursor,
    }

    def __init__(self, role: str, size: float = 10.0):
        super().__init__(QRectF(-size / 2, -size / 2, size, size))
        self.role = role
        self.size = size
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(QColor(0, 180, 255), 1.5))
        self.setCursor(QCursor(self.CURSORS[role]))
        self.setZValue(20)


class VisualCropBoxItem(QGraphicsRectItem):
    """Interactive draggable & resizable crop box overlaid on 16:9 source footage."""

    def __init__(self, rect: QRectF, max_bounds: QRectF, on_change_callback):
        super().__init__(rect)
        self.max_bounds = max_bounds
        self.on_change = on_change_callback
        self.setPen(QPen(QColor(0, 210, 255), 2.0))
        self.setBrush(QBrush(QColor(0, 180, 255, 35)))
        self.setZValue(10)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

        self._drag_mode: str | None = None
        self._drag_start_pos = QPointF()
        self._orig_rect = QRectF(rect)

        # 8 handles
        self.handles: dict[str, VisualCropHandleItem] = {}
        for role in ("nw", "n", "ne", "e", "se", "s", "sw", "w"):
            h = VisualCropHandleItem(role)
            self.handles[role] = h
        self._update_handle_positions()

    def _update_handle_positions(self):
        r = self.rect()
        positions = {
            "nw": QPointF(r.left(), r.top()),
            "n": QPointF(r.center().x(), r.top()),
            "ne": QPointF(r.right(), r.top()),
            "e": QPointF(r.right(), r.center().y()),
            "se": QPointF(r.right(), r.bottom()),
            "s": QPointF(r.center().x(), r.bottom()),
            "sw": QPointF(r.left(), r.bottom()),
            "w": QPointF(r.left(), r.center().y()),
        }
        for role, h in self.handles.items():
            h.setPos(positions[role])

    def mousePressEvent(self, event):
        pos = event.pos()
        self._drag_start_pos = event.scenePos()
        self._orig_rect = QRectF(self.rect())

        # Check handle click
        self._drag_mode = "move"
        for role, h in self.handles.items():
            if h.contains(h.mapFromScene(event.scenePos())):
                self._drag_mode = role
                break
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag_mode:
            return
        delta = event.scenePos() - self._drag_start_pos
        dx, dy = delta.x(), delta.y()
        r = QRectF(self._orig_rect)
        mb = self.max_bounds
        min_sz = 20.0

        if self._drag_mode == "move":
            new_left = max(mb.left(), min(mb.right() - r.width(), r.left() + dx))
            new_top = max(mb.top(), min(mb.bottom() - r.height(), r.top() + dy))
            r.moveTopLeft(QPointF(new_left, new_top))
        else:
            left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
            if "w" in self._drag_mode:
                left = max(mb.left(), min(right - min_sz, left + dx))
            if "e" in self._drag_mode:
                right = min(mb.right(), max(left + min_sz, right + dx))
            if "n" in self._drag_mode:
                top = max(mb.top(), min(bottom - min_sz, top + dy))
            if "s" in self._drag_mode:
                bottom = min(mb.bottom(), max(top + min_sz, bottom + dy))
            r = QRectF(left, top, right - left, bottom - top)

        self.setRect(r)
        self._update_handle_positions()
        if self.on_change:
            self.on_change(r)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_mode = None
        event.accept()


class VisualSourceCropDialog(QDialog):
    """Modal dialog displaying full uncropped 16:9 source frame with interactive crop tool."""

    def __init__(self, parent, frame: np.ndarray, layer_name: str, initial_crop: list[float], on_crop_applied):
        super().__init__(parent)
        self.setWindowTitle(f"Visual Source Crop — {layer_name.replace('_', ' ').title()}")
        self.setWindowIcon(get_app_icon())
        self.resize(1020, 680)
        self.setMinimumSize(780, 500)

        self.frame = frame
        self.layer_name = layer_name
        self.on_crop_applied = on_crop_applied

        src_h, src_w = frame.shape[:2]
        self.src_w = float(src_w)
        self.src_h = float(src_h)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header with guidance
        header = QHBoxLayout()
        title_lbl = QLabel(f"<b>Frame Source Crop:</b> {layer_name.replace('_', ' ').title()}")
        title_lbl.setStyleSheet("font-size: 13px;")
        header.addWidget(title_lbl)
        header.addStretch(1)
        header.addWidget(QLabel("Drag box to move · drag handles to resize (source: 16:9 gameplay)"))
        layout.addLayout(header)

        # Graphics Scene & View
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QBrush(QColor(16, 16, 20)))
        layout.addWidget(self.view, 1)

        # Source frame background
        pix = QPixmap.fromImage(to_qimage_array(frame))
        self.bg_item = QGraphicsPixmapItem(pix)
        self.bg_item.setZValue(0)
        self.scene.addItem(self.bg_item)
        self.scene.setSceneRect(0, 0, self.src_w, self.src_h)

        # Dimmed backdrop outside crop box
        self.dim_item = QGraphicsRectItem(0, 0, self.src_w, self.src_h)
        self.dim_item.setBrush(QBrush(QColor(0, 0, 0, 140)))
        self.dim_item.setPen(Qt.PenStyle.NoPen)
        self.dim_item.setZValue(5)
        self.dim_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.scene.addItem(self.dim_item)

        # Initial crop box geometry
        cx, cy, cw, ch = initial_crop
        box_rect = QRectF(cx * self.src_w, cy * self.src_h, cw * self.src_w, ch * self.src_h)
        bounds = QRectF(0, 0, self.src_w, self.src_h)

        self.crop_box = VisualCropBoxItem(box_rect, bounds, self._on_box_changed)
        self.scene.addItem(self.crop_box)
        for h in self.crop_box.handles.values():
            self.scene.addItem(h)

        # Bottom info and actions
        bottom_row = QHBoxLayout()
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet("font-family: monospace; font-size: 12px; font-weight: bold; color: #00d2ff;")
        bottom_row.addWidget(self.info_lbl)
        bottom_row.addStretch(1)

        full_btn = QPushButton(" Reset Full Frame")
        full_btn.setIcon(qta.icon("fa5s.expand", color="#dcdcdc"))
        full_btn.clicked.connect(self._reset_full)
        bottom_row.addWidget(full_btn)

        cancel_btn = QPushButton(" Cancel")
        cancel_btn.setIcon(qta.icon("fa5s.times", color="#dcdcdc"))
        cancel_btn.clicked.connect(self.reject)
        bottom_row.addWidget(cancel_btn)

        apply_btn = QPushButton(" Apply Crop")
        apply_btn.setIcon(qta.icon("fa5s.check", color="#ffffff"))
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet("font-weight: bold; background-color: #0078d4; color: white; padding: 6px 16px;")
        apply_btn.clicked.connect(self._apply)
        bottom_row.addWidget(apply_btn)

        layout.addLayout(bottom_row)

        self._on_box_changed(box_rect)
        QTimer.singleShot(50, self._fit_view)

    def _fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_view()

    def _on_box_changed(self, rect: QRectF):
        cx = max(0.0, min(1.0, rect.left() / self.src_w))
        cy = max(0.0, min(1.0, rect.top() / self.src_h))
        cw = max(0.005, min(1.0 - cx, rect.width() / self.src_w))
        ch = max(0.005, min(1.0 - cy, rect.height() / self.src_h))
        px_w = int(round(rect.width()))
        px_h = int(round(rect.height()))
        self.info_lbl.setText(
            f"Crop: X={cx*100:.1f}%, Y={cy*100:.1f}%  |  Size: {cw*100:.1f}% × {ch*100:.1f}% ({px_w}×{px_h} px)"
        )

    def _reset_full(self):
        full = QRectF(0, 0, self.src_w, self.src_h)
        self.crop_box.setRect(full)
        self.crop_box._update_handle_positions()
        self._on_box_changed(full)

    def _apply(self):
        r = self.crop_box.rect()
        cx = max(0.0, min(0.995, r.left() / self.src_w))
        cy = max(0.0, min(0.995, r.top() / self.src_h))
        cw = max(0.005, min(1.0 - cx, r.width() / self.src_w))
        ch = max(0.005, min(1.0 - cy, r.height() / self.src_h))
        if self.on_crop_applied:
            self.on_crop_applied([cx, cy, cw, ch])
        self.accept()
