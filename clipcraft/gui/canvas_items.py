from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem

from .constants import HANDLE_SIZE, MIN_LAYER_SIZE

if TYPE_CHECKING:
    from .main_window import ClipCraftWindow

class HandleItem(QGraphicsRectItem):
    """A resize grip pinned to an edge or corner of a LayerItem.

    Handles are dedicated scene items, so they stay clickable regardless of how
    much transparent padding the layer artwork has. Roles: nw, n, ne, e, se, s, sw, w.
    """

    CURSORS = {
        "nw": Qt.CursorShape.SizeFDiagCursor, "ne": Qt.CursorShape.SizeBDiagCursor,
        "se": Qt.CursorShape.SizeFDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
        "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
        "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
    }

    def __init__(self, layer: "LayerItem", role: str, grip_size: float = HANDLE_SIZE):
        super().__init__(QRectF(-grip_size / 2, -grip_size / 2, grip_size, grip_size))
        self.grip_size = grip_size
        self.layer = layer
        self.role = role
        self._drag_start = None
        self.setBrush(QBrush(QColor(248, 250, 252, 230)))
        self.setPen(QPen(QColor(30, 200, 190), 1.0))
        self.setCursor(QCursor(self.CURSORS[role]))
        self.setAcceptHoverEvents(True)
        self.setZValue(5)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(40, 235, 220)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(248, 250, 252, 230)))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        layer = self.layer
        self._drag_start = (*layer.geometry_tuple(), event.scenePos())
        layer.setSelected(True)
        layer.begin_interaction("Resize")
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start is None:
            event.ignore()
            return
        self.layer.resize_from_handle(
            self.role, self._drag_start, event.scenePos(),
            bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
        )
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_start is None:
            event.ignore()
            return
        self._drag_start = None
        self.layer.commit("Resize")
        event.accept()


class SafeZoneOverlayItem(QGraphicsItem):
    """Semi-transparent guide overlay showing mobile UI dead-zones (YouTube Shorts & TikTok)."""

    def __init__(self, width: float, height: float):
        super().__init__()
        self.w = float(width)
        self.h = float(height)
        self.setZValue(9999.0)  # Always floats on top of all layers
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # Transparent to mouse interaction

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.w, self.h)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.w, self.h

        # Modern semi-transparent cyan / blue mobile safe zone styling
        border_pen = QPen(QColor(0, 220, 255, 160), 1.0, Qt.PenStyle.DashLine)
        fill_brush = QColor(0, 180, 255, 25)

        # 1. Top Bar Deadzone (Header, Search, Sound title) ~ 11%
        top_h = h * 0.11
        painter.setPen(border_pen)
        painter.setBrush(fill_brush)
        painter.drawRect(QRectF(0.0, 0.0, w, top_h))

        # 2. Bottom Captions & Profile Deadzone ~ 20%
        bot_h = h * 0.20
        bot_y = h - bot_h
        painter.drawRect(QRectF(0.0, bot_y, w, bot_h))

        # 3. Right Engagement Actions (Like, Comments, Share, Audio disc) ~ 19%
        right_w = w * 0.19
        right_x = w - right_w
        action_y = h * 0.35
        action_h = h * 0.44
        painter.drawRect(QRectF(right_x, action_y, right_w, action_h))

        # Labels
        painter.setPen(QColor(0, 230, 255, 210))
        font = painter.font()
        font.setPointSize(max(7, int(8 * (w / 360.0))))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)

        painter.drawText(
            QRectF(8.0, 2.0, w - 16.0, top_h - 4.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "TOP BAR (SEARCH / AUDIO)",
        )
        painter.drawText(
            QRectF(8.0, bot_y + 2.0, w - right_w - 12.0, bot_h - 4.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "BOTTOM (TITLE / CAPTIONS / PROFILE)",
        )
        painter.drawText(
            QRectF(right_x + 2.0, action_y + 4.0, right_w - 4.0, action_h - 8.0),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            "ACTIONS\n(LIKE / SHARE)",
        )

class LayerItem(QGraphicsPixmapItem):
    """A canvas layer: drag the body to move, drag a grip to resize.

    All geometry lives in preview-canvas pixels (360x640 scene units) and is written
    back to the config as normalized values through the window controller.
    """

    HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

    def __init__(self, name: str, pixmap: QPixmap, rect: tuple[float, float, float, float],
                 controller, preserve_aspect: bool = False, aspect_ratio: float | None = None,
                 grip_size: float = HANDLE_SIZE):
        super().__init__(pixmap)
        self.name = name
        self.controller = controller
        self._source_pixmap = pixmap
        self._preserve_aspect = preserve_aspect
        self._aspect_ratio = aspect_ratio
        self._min_size = MIN_LAYER_SIZE
        self._moving = False
        self._move_step = None
        self._interaction_rect = None
        # Qt pads selectable pixmap items' boundingRect by 1px, so the true layer
        # geometry is tracked here and never derived from boundingRect().
        self._geo = QRectF(0.0, 0.0, max(2.0, float(rect[2])), max(2.0, float(rect[3])))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        # The whole rectangle is interactive, including transparent PNG regions.
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        self.setZValue(10)
        self._handles = {role: HandleItem(self, role, grip_size) for role in self.HANDLES}
        for handle in self._handles.values():
            handle.setParentItem(self)
        self.set_pos_size(*rect)

    def set_frame_pixmap(self, pixmap: QPixmap) -> None:
        """Playback: swap in the next decoded frame without touching geometry or grips."""
        self._source_pixmap = pixmap
        self.setPixmap(pixmap)

    def set_grips_visible(self, visible: bool) -> None:
        for handle in self._handles.values():
            handle.setVisible(visible)

    # -- geometry ---------------------------------------------------------

    def geometry_tuple(self) -> tuple[float, float, float, float]:
        """(x, y, width, height) in scene pixels, free of Qt's selectable-item padding."""
        return self.x(), self.y(), self._geo.width(), self._geo.height()

    def set_pos_size(self, x: float, y: float, width: float, height: float) -> None:
        width = max(self._min_size, width)
        height = max(self._min_size, height)
        self._geo = QRectF(0.0, 0.0, width, height)
        self.setPos(x, y)
        self.setPixmap(self._source_pixmap.scaled(
            max(2, int(round(width))), max(2, int(round(height))),
            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self.update_handles()

    def update_handles(self) -> None:
        w = self._geo.width()
        h = self._geo.height()
        anchors = {
            "nw": (0.0, 0.0), "n": (w / 2, 0.0), "ne": (w, 0.0), "e": (w, h / 2),
            "se": (w, h), "s": (w / 2, h), "sw": (0.0, h), "w": (0.0, h / 2),
        }
        for role, (ax, ay) in anchors.items():
            self._handles[role].setPos(ax, ay)

    def resize_from_handle(self, role: str, start, scene_pos, shift_held: bool = False) -> None:
        x0, y0, w0, h0, grab = start
        min_s = self._min_size
        dx = scene_pos.x() - grab.x()
        dy = scene_pos.y() - grab.y()
        left, top = x0, y0
        right, bottom = x0 + w0, y0 + h0

        if "e" in role:
            right = max(left + min_s, right + dx)
        if "s" in role:
            bottom = max(top + min_s, bottom + dy)
        if "w" in role:
            left = min(right - min_s, left + dx)
        if "n" in role:
            top = min(bottom - min_s, top + dy)

        lock = self._preserve_aspect or shift_held
        if lock:
            # Contain-mode layers keep the image's native aspect ratio; Shift keeps
            # whatever proportions the rectangle currently has.
            if self._preserve_aspect and self._aspect_ratio:
                aspect = self._aspect_ratio
            elif h0 > 0:
                aspect = w0 / h0
            else:
                aspect = None
            if aspect:
                if role in ("e", "w"):
                    # Vertical center stays put while the width drives the scale.
                    h = (right - left) / aspect
                    cy = y0 + h0 / 2
                    top, bottom = cy - h / 2, cy + h / 2
                elif role in ("n", "s"):
                    # Horizontal center stays put while the height drives the scale.
                    w = (bottom - top) * aspect
                    cx = x0 + w0 / 2
                    left, right = cx - w / 2, cx + w / 2
                elif role in ("se", "sw"):
                    # Corner grips keep the opposite corner anchored.
                    bottom = top + (right - left) / aspect
                else:  # nw, ne
                    top = bottom - (right - left) / aspect

        scene = self.scene()
        if scene:
            bounds = scene.sceneRect()
            left = max(bounds.left(), left)
            top = max(bounds.top(), top)
            right = min(bounds.right(), right)
            bottom = min(bounds.bottom(), bottom)
        self.set_pos_size(left, top, right - left, bottom - top)

    # -- interaction ------------------------------------------------------

    def begin_interaction(self, action: str) -> None:
        self._interaction_rect = self.geometry_tuple()
        if self.controller:
            self.controller.layer_interaction_started(self.name, action)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._moving = True
        self._move_step = event.scenePos()
        self.setSelected(True)
        self.begin_interaction("Move")
        if self.controller:
            self.controller.layer_selected(self.name)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._moving or self._move_step is None:
            event.ignore()
            return
        delta = event.scenePos() - self._move_step
        self._move_step = event.scenePos()
        x, y, w, h = self.geometry_tuple()
        scene = self.scene()
        if scene:
            bounds = scene.sceneRect()
            x = max(bounds.left(), min(bounds.right() - w, x + delta.x()))
            y = max(bounds.top(), min(bounds.bottom() - h, y + delta.y()))
        else:
            x, y = x + delta.x(), y + delta.y()
        self.setPos(x, y)
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self._moving:
            event.ignore()
            return
        self._moving = False
        self._move_step = None
        self.commit("Move")
        event.accept()

    def commit(self, action: str) -> None:
        current = self.geometry_tuple()
        changed = self._interaction_rect is not None and any(
            abs(a - b) > 0.05 for a, b in zip(self._interaction_rect, current)
        )
        self._interaction_rect = None
        if changed and self.controller:
            self.controller.layer_committed(self.name, self, action)

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor(40, 235, 220), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.drawRect(self._geo.adjusted(0.5, 0.5, -0.5, -0.5))
