from __future__ import annotations

import copy
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSizeF, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QPixmap, QPainter, QCursor, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QProgressBar, QScrollArea, QSlider, QSpinBox, QSplitter, QStatusBar,
    QVBoxLayout, QWidget,
)

from .assets import ensure_assets
from .config import (
    available_templates, clone_config, image_content_info, load_config, load_state,
    migrate_legacy_config, resolve_asset, save_config, save_state, template_path,
)
from .preview import layer_preview_image, render_background, to_qimage_array
from .renderer import probe_video, run_render


HANDLE_SIZE = 6.0
MIN_LAYER_SIZE = 10.0
BG_DEFAULTS = {"blur": 22, "brightness": -0.08, "saturation": 0.82}


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


class RenderWorker(QThread):
    progress_signal = Signal(float, str)
    finished_signal = Signal(bool, str)

    def __init__(self, video: str, output: str, start: float, end: float,
                 config: dict[str, Any], config_path: Path, encoder: str):
        super().__init__()
        self.video = video
        self.output = output
        self.start_time = start
        self.end_time = end
        self.config = copy.deepcopy(config)
        self.config_path = config_path
        self.encoder = encoder

    def run(self):
        try:
            result = run_render(
                self.video, self.output, self.start_time, self.end_time,
                self.config, self.config_path, self.encoder,
                progress=lambda value, message: self.progress_signal.emit(value, message),
            )
            self.finished_signal.emit(True, str(result))
        except Exception as exc:  # The GUI displays the FFmpeg diagnostic to the user.
            self.finished_signal.emit(False, str(exc))


class FasTrackWindow(QMainWindow):
    def __init__(self, video_path: str | None, game: str | None = None, config_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("FasTrack Video Editor — Gaming Shorts")
        self.resize(1510, 940)
        self.setMinimumSize(1100, 720)
        state = load_state()
        self.config, self.config_path, self.game = self._resolve_template(game, config_path, state)
        ensure_assets(self.config, self.config_path)
        self.original_config = clone_config(self.config)
        self.template_name = str(self.config.get("name") or self.game.replace("_", " ").title())
        self.setWindowTitle(f"FasTrack Video Editor — {self.template_name}")
        remembered = str(state.get("source_dir", ""))
        self.source_dir = remembered if remembered and Path(remembered).is_dir() else str(Path.home())
        self.show_grips = bool(state.get("show_grips", True))
        self.video_path: str | None = None
        self.video_info: dict[str, Any] | None = None
        self.capture: cv2.VideoCapture | None = None
        self.current_frame: np.ndarray | None = None
        self.playhead = 0.0
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self._play_tick)
        self.pending_capture = False
        self.layer_items: dict[str, LayerItem] = {}
        self._bg_item = None
        self._playing = False
        self._play_speed = 1.0
        self._play_direction = 1
        self._play_clock: float | None = None
        self._read_backlog = 0.0
        self._frame_index = 0
        self._scrubbing = False
        self._reverse_buffer: list = []
        self.preview_sharp = bool(state.get("preview_sharp", True))
        self.preview_scale = 1.5 if self.preview_sharp else 1.0
        self.worker: RenderWorker | None = None
        self._undo_stack: list[tuple[str, dict[str, Any]]] = []
        self._redo_stack: list[tuple[str, dict[str, Any]]] = []
        self._pending_undo: tuple[str, dict[str, Any]] | None = None
        self._build_ui()
        undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_shortcut.activated.connect(self.undo)
        redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_shortcut.activated.connect(self.redo)
        space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        space_shortcut.activated.connect(self.toggle_play)
        if video_path:
            self.load_video(video_path)
        else:
            QTimer.singleShot(100, self.browse_video)

    def _resolve_template(self, game, config_path, state):
        """Explicit --config wins; then -g; then the last used template; else the first installed."""
        if config_path:
            config, path = load_config(config_path)
            game_id = (game or Path(config_path).stem).lower()
            return config, path, game_id
        migrate_legacy_config()
        installed = available_templates()
        if not installed:
            raise ValueError("No game templates found in the templates/ folder.")
        game_id = (game or str(state.get("last_template", "")) or "").lower()
        if game_id not in dict(installed):
            game_id = "valorant" if "valorant" in dict(installed) else installed[0][0]
        config, path = load_config(template_path(game_id))
        return config, path, game_id

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Footage"))
        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("Choose a Valorant recording…")
        file_row.addWidget(self.video_edit, 1)
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.browse_video)
        file_row.addWidget(self.browse_button)
        self.game_combo = QComboBox()
        for template_id, template_name in available_templates():
            self.game_combo.addItem(template_name, template_id)
        combo_index = self.game_combo.findData(self.game)
        if combo_index >= 0:
            self.game_combo.setCurrentIndex(combo_index)
        self.game_combo.setMinimumWidth(125)
        self.game_combo.currentIndexChanged.connect(self._switch_template)
        file_row.addWidget(QLabel("Template"))
        file_row.addWidget(self.game_combo)
        root.addLayout(file_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = self._build_left_panel()
        center = self._build_preview_panel()
        right = self._build_inspector_panel()
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setSizes([330, 740, 360])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready — choose a recording to begin")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(390)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 4, 0)

        trim_group = QGroupBox("Clip selection")
        trim_layout = QVBoxLayout(trim_group)
        self.frame_label = QLabel("00:00.000 / 00:00.000")
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        trim_layout.addWidget(self.frame_label)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 10000)
        self.position_slider.valueChanged.connect(self._position_changed)
        self.position_slider.sliderPressed.connect(self._start_scrub)
        self.position_slider.sliderReleased.connect(self._finish_scrub)
        trim_layout.addWidget(self.position_slider)
        play_row = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_play)
        play_row.addWidget(self.play_button)
        self.step_back_button = QPushButton("◀ Frame")
        self.step_back_button.setToolTip("Back 1 frame (Left arrow; Shift = 1 second)")
        self.step_back_button.clicked.connect(self._step_back)
        play_row.addWidget(self.step_back_button)
        self.step_fwd_button = QPushButton("Frame ▶")
        self.step_fwd_button.setToolTip("Forward 1 frame (Right arrow; Shift = 1 second)")
        self.step_fwd_button.clicked.connect(self._step_forward)
        play_row.addWidget(self.step_fwd_button)
        trim_layout.addLayout(play_row)
        io_row = QHBoxLayout()
        self.set_in_button = QPushButton("Set IN ◀")
        self.set_in_button.clicked.connect(self.set_in_from_playhead)
        io_row.addWidget(self.set_in_button)
        self.set_out_button = QPushButton("Set OUT ▶")
        self.set_out_button.clicked.connect(self.set_out_from_playhead)
        io_row.addWidget(self.set_out_button)
        trim_layout.addLayout(io_row)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed"))
        self.speed_combo = QComboBox()
        for speed_label, speed_value in (("0.25×", 0.25), ("0.5×", 0.5), ("1×", 1.0), ("2×", 2.0), ("4×", 4.0)):
            self.speed_combo.addItem(speed_label, speed_value)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(self._speed_changed)
        speed_row.addWidget(self.speed_combo)
        speed_row.addStretch(1)
        trim_layout.addLayout(speed_row)
        trim_form = QFormLayout()
        self.in_spin = QDoubleSpinBox()
        self.out_spin = QDoubleSpinBox()
        for spin in (self.in_spin, self.out_spin):
            spin.setRange(0, 24 * 60 * 60)
            spin.setDecimals(3)
            spin.setSingleStep(0.25)
            spin.setSuffix(" s")
        self.in_spin.valueChanged.connect(self._validate_trim)
        self.out_spin.valueChanged.connect(self._validate_trim)
        trim_form.addRow("IN point", self.in_spin)
        trim_form.addRow("OUT point", self.out_spin)
        trim_layout.addLayout(trim_form)
        layout.addWidget(trim_group)

        bg_group = QGroupBox("Background look")
        bg_form = QFormLayout(bg_group)
        bg_specs = (
            ("blur", "Blur", 1, 60, 1.0, 0),
            ("brightness", "Brightness", -50, 50, 0.01, 2),
            ("saturation", "Saturation", 0, 200, 0.01, 2),
        )
        self.bg_sliders: dict[str, tuple[QSlider, QLabel, float, int]] = {}
        for key, title, minimum, maximum, scale, decimals in bg_specs:
            current = float(self.config.get("background", {}).get(key, BG_DEFAULTS[key]))
            name_label = QLabel(title)
            name_label.setMinimumWidth(72)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setValue(int(round(current / scale)))
            slider.sliderPressed.connect(self._bg_interaction_started)
            slider.sliderReleased.connect(self._bg_interaction_finished)
            slider.valueChanged.connect(self._background_changed)
            value_label = QLabel(f"{current:.{decimals}f}")
            value_label.setMinimumWidth(48)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(value_label)
            bg_form.addRow(name_label, row)
            self.bg_sliders[key] = (slider, value_label, scale, decimals)
        layout.addWidget(bg_group)

        render_group = QGroupBox("Render settings")
        render_layout = QVBoxLayout(render_group)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output MP4 path")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_browse = QPushButton("…")
        output_browse.setMaximumWidth(36)
        output_browse.clicked.connect(self.browse_output)
        output_row.addWidget(output_browse)
        render_layout.addLayout(output_row)
        render_form = QFormLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(180, 4320)
        self.width_spin.setSingleStep(2)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(320, 7680)
        self.height_spin.setSingleStep(2)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(14, 30)
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItem("Auto (NVENC → CPU)", "auto")
        self.encoder_combo.addItem("NVIDIA NVENC", "nvenc")
        self.encoder_combo.addItem("CPU / x264", "cpu")
        self.width_spin.setValue(int(self.config["canvas"].get("width", 1080)))
        self.height_spin.setValue(int(self.config["canvas"].get("height", 1920)))
        self.fps_spin.setValue(int(self.config["canvas"].get("fps", 60)))
        self.quality_spin.setValue(int(self.config["canvas"].get("quality", 19)))
        render_form.addRow("Width", self.width_spin)
        render_form.addRow("Height", self.height_spin)
        render_form.addRow("FPS", self.fps_spin)
        render_form.addRow("Quality (lower = better)", self.quality_spin)
        render_form.addRow("Encoder", self.encoder_combo)
        render_layout.addLayout(render_form)
        self.render_button = QPushButton("Render Shorts")
        self.render_button.setMinimumHeight(42)
        self.render_button.clicked.connect(self.start_render)
        render_layout.addWidget(self.render_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        render_layout.addWidget(self.progress)
        self.render_status = QLabel("Ready to render")
        self.render_status.setWordWrap(True)
        render_layout.addWidget(self.render_status)
        layout.addWidget(render_group)
        layout.addStretch(1)
        return panel

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("Live composition preview"))
        header.addStretch(1)
        header.addWidget(QLabel("Drag to move · drag the grips to resize · Shift = keep aspect"))
        self.grips_check = QCheckBox("Resize grips")
        self.grips_check.setChecked(self.show_grips)
        self.grips_check.setToolTip("Show or hide the resize grips (resizing is still available via the position/size fields)")
        self.grips_check.stateChanged.connect(self._toggle_grips)
        header.addWidget(self.grips_check)
        self.sharp_check = QCheckBox("Sharp preview")
        self.sharp_check.setChecked(self.preview_sharp)
        self.sharp_check.setToolTip("Render the preview at 540×960 instead of 360×640 (a bit heavier during playback)")
        self.sharp_check.stateChanged.connect(self._toggle_sharp)
        header.addWidget(self.sharp_check)
        layout.addLayout(header)
        self.scene = QGraphicsScene(self)
        preview_w, preview_h = self._preview_size()
        self.scene.setSceneRect(0, 0, preview_w, preview_h)
        self.preview_view = QGraphicsView(self.scene)
        self.preview_view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.preview_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_view.setBackgroundBrush(QBrush(QColor(16, 18, 24)))
        self.preview_view.setFrameShape(QFrame.Shape.StyledPanel)
        layout.addWidget(self.preview_view, 1)
        hint = QLabel("Select a layer on the right, then edit its output rectangle and source crop. The crop preview updates on Apply.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return panel

    def _build_inspector_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 0, 0, 0)
        layer_group = QGroupBox("Layer editor")
        layer_layout = QVBoxLayout(layer_group)
        self.layer_combo = QComboBox()
        for name, layer in sorted(self.config["layers"].items(), key=lambda pair: pair[1].get("z", 0)):
            if name != "background":
                self.layer_combo.addItem(name.replace("_", " ").title(), name)
        self.layer_combo.currentIndexChanged.connect(self.select_layer)
        layer_layout.addWidget(self.layer_combo)
        self.visible_check = QCheckBox("Visible")
        self.visible_check.stateChanged.connect(self.toggle_layer_visible)
        layer_layout.addWidget(self.visible_check)

        self.asset_group = QGroupBox("Image asset")
        asset_layout = QHBoxLayout(self.asset_group)
        asset_layout.setContentsMargins(6, 4, 6, 4)
        self.asset_edit = QLineEdit()
        self.asset_edit.setReadOnly(True)
        self.asset_edit.setPlaceholderText("No asset")
        asset_layout.addWidget(self.asset_edit, 1)
        self.asset_button = QPushButton("Browse…")
        self.asset_button.setMaximumWidth(72)
        self.asset_button.clicked.connect(self.browse_asset)
        asset_layout.addWidget(self.asset_button)
        layer_layout.addWidget(self.asset_group)

        geometry_group = QGroupBox("Output position / size (% of canvas)")
        geometry_inner = QVBoxLayout(geometry_group)
        geometry_inner.setContentsMargins(6, 4, 6, 6)
        geometry_form = QFormLayout()
        self.geom_fields = {}
        for key, title in (("x", "X"), ("y", "Y"), ("w", "Width"), ("h", "Height")):
            spin = QDoubleSpinBox()
            spin.setRange(0.1 if key in ("w", "h") else -50.0, 150.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" %")
            self.geom_fields[key] = spin
            geometry_form.addRow(title, spin)
        geometry_inner.addLayout(geometry_form)
        self.snap_aspect_button = QPushButton("Snap to image aspect")
        self.snap_aspect_button.setToolTip("Fit the rectangle to the image's own aspect ratio, kept centered")
        self.snap_aspect_button.clicked.connect(self.snap_image_aspect)
        geometry_inner.addWidget(self.snap_aspect_button)
        layer_layout.addWidget(geometry_group)

        crop_group = QGroupBox("Source crop (% of original footage)")
        crop_form = QFormLayout(crop_group)
        self.crop_fields = {}
        for key, title in (("x", "Crop X"), ("y", "Crop Y"), ("w", "Crop width"), ("h", "Crop height")):
            spin = QDoubleSpinBox()
            spin.setRange(0.1 if key in ("w", "h") else 0.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" %")
            self.crop_fields[key] = spin
            crop_form.addRow(title, spin)
        layer_layout.addWidget(crop_group)
        apply_button = QPushButton("Apply to preview")
        apply_button.clicked.connect(self.apply_layer_changes)
        layer_layout.addWidget(apply_button)
        self.reset_crop_button = QPushButton("Reset to default")
        self.reset_crop_button.setToolTip("Reset source crop to config defaults")
        self.reset_crop_button.clicked.connect(self.reset_crop_to_default)
        layer_layout.addWidget(self.reset_crop_button)
        layout.addWidget(layer_group)

        actions_group = QGroupBox("Template")
        actions_layout = QVBoxLayout(actions_group)
        history_row = QHBoxLayout()
        self.undo_button = QPushButton("↶ Undo")
        self.undo_button.setToolTip("Undo the last canvas or layout change (Ctrl+Z)")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("↷ Redo")
        self.redo_button.setToolTip("Redo an undone change (Ctrl+Shift+Z)")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self.redo)
        history_row.addWidget(self.undo_button)
        history_row.addWidget(self.redo_button)
        actions_layout.addLayout(history_row)
        save_button = QPushButton("Save layout to template")
        save_button.clicked.connect(self.save_layout)
        actions_layout.addWidget(save_button)
        reset_button = QPushButton("Reset to saved layout")
        reset_button.clicked.connect(self.reset_layout)
        actions_layout.addWidget(reset_button)
        layout.addWidget(actions_group)
        layout.addStretch(1)
        return panel

    def browse_video(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose gameplay recording", self.source_dir,
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*.*)"
        )
        if filename:
            self.load_video(filename)

    def load_video(self, filename: str):
        path = Path(filename).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, "Video not found", str(path))
            return
        try:
            info = probe_video(path)
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise RuntimeError("OpenCV could not open this video. Try converting it to H.264 MP4 first.")
        except Exception as exc:
            QMessageBox.critical(self, "Could not load video", str(exc))
            return
        if self.capture is not None:
            self.capture.release()
        self.capture = capture
        self.video_path = str(path)
        self.video_info = info
        self.video_edit.setText(self.video_path)
        self._remember_source_dir(path.parent)
        duration = float(info["duration"])
        self.in_spin.blockSignals(True)
        self.out_spin.blockSignals(True)
        self.in_spin.setRange(0, max(0, duration))
        self.out_spin.setRange(0, max(0, duration))
        self.in_spin.setValue(0)
        self.out_spin.setValue(duration)
        self.in_spin.blockSignals(False)
        self.out_spin.blockSignals(False)
        self.playhead = 0
        self.position_slider.setValue(0)
        output = path.parent / "exports" / f"{path.stem}_{self.game}_short.mp4"
        self.output_edit.setText(str(output))
        if self._playing:
            self._stop_playback()
        self._frame_index = 0
        self._scrubbing = False
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, first_frame = self.capture.read()
        if ok:
            self.current_frame = first_frame
        self.refresh_canvas()
        self.statusBar().showMessage(
            f"Loaded {path.name} · {info['width']}×{info['height']} · {info['fps']:.2f} fps · {duration:.2f}s"
        )

    def _remember_source_dir(self, directory: Path) -> None:
        """Persist the folder of the last opened recording for the next session."""
        self.source_dir = str(directory)
        try:
            state = load_state()
            state["source_dir"] = self.source_dir
            save_state(state)
        except OSError:
            pass  # Remembering the folder must never block loading a video.

    def _position_changed(self, value: int):
        if not self.video_info:
            return
        duration = self.video_info["duration"]
        self.playhead = duration * value / 10000.0
        self._update_time_label()

    def _update_time_label(self):
        duration = self.video_info["duration"]
        frame = int(round(self.playhead * self._effective_fps()))
        self.frame_label.setText(
            f"{self._format_time(self.playhead)} / {self._format_time(duration)} · frame {frame}"
        )

    # -- playback engine ---------------------------------------------------

    def _effective_fps(self) -> float:
        fps = float((self.video_info or {}).get("fps", 0.0) or 0.0)
        if fps <= 0.0:
            return 30.0
        return max(1.0, min(240.0, fps))

    def _preview_size(self) -> tuple[int, int]:
        return int(360 * self.preview_scale), int(640 * self.preview_scale)

    def _seek_to_index(self, index: int) -> bool:
        """Random-access seek (scrub / stepping / loop) — used sparingly, never per playback tick."""
        if self.capture is None or not self.video_info:
            return False
        fps = self._effective_fps()
        total = max(1, int(round(float(self.video_info["duration"]) * fps)))
        index = max(0, min(total - 1, index))
        if index == self._frame_index and self.current_frame is not None:
            return False
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.capture.read()
        if not ok:
            return False
        self._frame_index = index
        self.current_frame = frame
        self.playhead = index / fps
        return True

    def _update_frame_layers(self) -> None:
        """Per-frame update: only the blurred backdrop and the video windows change.

        Image layers and grips are static scene items — rebuilding them per frame
        (the old behaviour) was what made playback crawl.
        """
        if self.current_frame is None:
            return
        canvas_w, canvas_h = self._preview_size()
        if self._bg_item is not None:
            background = render_background(self.current_frame, canvas_w, canvas_h, self.config)
            self._bg_item.setPixmap(QPixmap.fromImage(to_qimage_array(background)))
        for name, layer in self.config["layers"].items():
            if layer.get("kind") != "video" or not layer.get("visible", True):
                continue
            item = self.layer_items.get(name)
            if item is None:
                continue
            image, _ = layer_preview_image(name, layer, self.current_frame, canvas_w, canvas_h, self.config_path)
            if image is not None:
                item.set_frame_pixmap(QPixmap.fromImage(to_qimage_array(image)))

    def _sync_playhead_ui(self) -> None:
        if not self.video_info:
            return
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(int(self.playhead / max(self.video_info["duration"], 0.001) * 10000))
        self.position_slider.blockSignals(False)
        self._update_time_label()

    def _start_playback(self, direction: int = 1, reset_speed: bool = False) -> None:
        if self.capture is None or not self.video_info:
            return
        self._playing = True
        self._play_direction = 1 if direction >= 0 else -1
        if reset_speed:
            self._play_speed = 1.0
        self._play_clock = time.monotonic()
        self._read_backlog = 0.0
        self._reverse_buffer.clear()
        self.play_timer.start()
        self.play_button.setText("Ⅱ Pause" if self._play_direction > 0 else "◀ Rewind")

    def _stop_playback(self) -> None:
        self._playing = False
        self._reverse_buffer.clear()  # release decoded frames promptly
        self.play_timer.stop()
        self.play_button.setText("▶ Play")

    def toggle_play(self) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _play_tick(self):
        if not self._playing or self.capture is None or not self.video_info:
            self._stop_playback()
            return
        if self._scrubbing:
            self._play_clock = time.monotonic()  # don't accumulate time while the slider is held
            return
        if self._play_direction < 0:
            self._reverse_tick()
            return
        now = time.monotonic()
        if self._play_clock is None:
            self._play_clock = now
        # Real-time pacing: elapsed wall time × speed decides how many frames to read.
        self._read_backlog += (now - self._play_clock) * self._play_speed * self._effective_fps()
        self._play_clock = now
        count = min(int(self._read_backlog), 8)  # a burst must never freeze the UI
        self._read_backlog -= count
        fps = self._effective_fps()
        in_frame = int(round(self.in_spin.value() * fps))
        updated = False
        for _ in range(count):
            if self.playhead >= self.out_spin.value() - 1e-9:
                updated |= self._seek_to_index(in_frame)  # loop back to IN
                continue
            ok, frame = self.capture.read()
            if not ok:
                updated |= self._seek_to_index(in_frame)  # end of stream → loop
                continue
            self._frame_index += 1
            self.current_frame = frame
            self.playhead = self._frame_index / fps
            updated = True
        if updated:
            self._sync_playhead_ui()
            self._update_frame_layers()

    def _reverse_tick(self):
        """Shuttle backwards: display frames from a small decoded buffer, refilled by one seek per batch."""
        now = time.monotonic()
        if self._play_clock is None:
            self._play_clock = now
        self._read_backlog += (now - self._play_clock) * self._play_speed * self._effective_fps()
        self._play_clock = now
        fps = self._effective_fps()
        updated = False
        while self._read_backlog >= 1.0:
            if not self._reverse_buffer:
                if self._frame_index <= 0 or self.playhead <= self.in_spin.value() + 1e-9:
                    self._stop_playback()  # rewound to the IN point
                    break
                self._load_reverse_batch()
                if not self._reverse_buffer:
                    self._stop_playback()
                    break
            self.current_frame = self._reverse_buffer.pop()
            self._frame_index -= 1
            self.playhead = self._frame_index / fps
            self._read_backlog -= 1.0
            updated = True
        if updated:
            self._sync_playhead_ui()
            self._update_frame_layers()

    def _load_reverse_batch(self) -> None:
        """Decode the frames just before the playhead into _reverse_buffer (newest last)."""
        fps = self._effective_fps()
        frame_bytes = self.current_frame.nbytes if self.current_frame is not None else 6_200_000
        # ~0.25 s of footage per seek, capped by a ~96 MB working set for the batch.
        batch = int(min(max(round(self._play_speed * fps * 0.25), 4),
                        max(2, int(96_000_000 / max(frame_bytes, 1)))))
        anchor = max(0, self._frame_index - batch)
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, anchor)
        count = self._frame_index - anchor
        self._reverse_buffer.clear()
        for _ in range(count):
            ok, frame = self.capture.read()
            if not ok:
                break
            self._reverse_buffer.append(frame)

    def _shuttle_forward(self) -> None:
        if self._playing and self._play_direction > 0:
            self._play_speed = min(self._play_speed * 2.0, 4.0)
            self._play_clock = time.monotonic()
        else:
            self._start_playback(direction=1, reset_speed=True)
        self._sync_speed_combo()

    def _shuttle_reverse(self) -> None:
        if self.current_frame is None:
            return
        if self._playing and self._play_direction < 0:
            self._play_speed = min(self._play_speed * 2.0, 4.0)
            self._play_clock = time.monotonic()
        else:
            if self.playhead <= self.in_spin.value() + 1e-9:
                self.statusBar().showMessage("Already at the IN point — nothing to rewind")
                return
            self._start_playback(direction=-1, reset_speed=True)
        self._sync_speed_combo()

    def _sync_speed_combo(self) -> None:
        index = self.speed_combo.findData(self._play_speed)
        if index >= 0:
            self.speed_combo.blockSignals(True)
            self.speed_combo.setCurrentIndex(index)
            self.speed_combo.blockSignals(False)

    def _step_back(self) -> None:
        second = bool(QApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.step_frames(-int(round(self._effective_fps())) if second else -1)

    def _step_forward(self) -> None:
        second = bool(QApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.step_frames(int(round(self._effective_fps())) if second else 1)

    def step_frames(self, delta: int) -> None:
        """Move by whole frames; stepping pauses playback (standard editor behaviour)."""
        if self.capture is None or not self.video_info:
            return
        if self._playing:
            self._stop_playback()
        if self._seek_to_index(self._frame_index + delta):
            self._sync_playhead_ui()
            self._update_frame_layers()

    def _start_scrub(self) -> None:
        self._scrubbing = True

    def _finish_scrub(self) -> None:
        self._scrubbing = False
        self._play_clock = time.monotonic()
        self._read_backlog = 0.0
        if self._seek_to_index(int(round(self.playhead * self._effective_fps()))):
            self._sync_playhead_ui()
            self._update_frame_layers()

    def _speed_changed(self, index: int) -> None:
        self._play_speed = float(self.speed_combo.itemData(index) or 1.0)

    def _toggle_sharp(self, state: int) -> None:
        self.preview_sharp = state == int(Qt.CheckState.Checked.value)
        self.preview_scale = 1.5 if self.preview_sharp else 1.0
        try:
            app_state = load_state()
            app_state["preview_sharp"] = self.preview_sharp
            save_state(app_state)
        except OSError:
            pass
        self.refresh_canvas()

    def set_in_from_playhead(self):
        self.in_spin.setValue(min(self.playhead, max(0.0, self.out_spin.value() - 0.05)))
        self.statusBar().showMessage(f"IN set to {self._format_time(self.in_spin.value())}")

    def set_out_from_playhead(self):
        self.out_spin.setValue(max(self.playhead, self.in_spin.value() + 0.05))
        self.statusBar().showMessage(f"OUT set to {self._format_time(self.out_spin.value())}")

    def _validate_trim(self):
        if self.out_spin.value() <= self.in_spin.value():
            self.render_button.setEnabled(False)
            self.render_status.setText("OUT must be later than IN")
        else:
            self.render_button.setEnabled(self.video_path is not None)
            self.render_status.setText("Ready to render")

    def _active_layer_name(self) -> str:
        return str(self.layer_combo.currentData())

    def select_layer(self, _index: int = 0):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name, {})
        item = self.layer_items.get(name)
        for key, candidate in self.layer_items.items():
            candidate.setSelected(key == name)
        rect = layer.get("rect", [0, 0, 0.1, 0.1])
        for key, value in zip(("x", "y", "w", "h"), rect):
            self.geom_fields[key].blockSignals(True)
            self.geom_fields[key].setValue(float(value) * 100)
            self.geom_fields[key].blockSignals(False)
        is_video = layer.get("kind") == "video"
        crop = layer.get("crop", [0, 0, 1, 1])
        for key, value in zip(("x", "y", "w", "h"), crop):
            self.crop_fields[key].setEnabled(is_video)
            self.crop_fields[key].blockSignals(True)
            self.crop_fields[key].setValue(float(value) * 100)
            self.crop_fields[key].blockSignals(False)
        self.reset_crop_button.setEnabled(is_video)
        self.visible_check.blockSignals(True)
        self.visible_check.setChecked(bool(layer.get("visible", True)))
        self.visible_check.blockSignals(False)
        is_image = layer.get("kind") == "image"
        self.asset_group.setVisible(is_image)
        self.asset_edit.setText(str(layer.get("asset", "")) if is_image else "")
        self.snap_aspect_button.setEnabled(is_image)

    def browse_asset(self):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name, {})
        if layer.get("kind") != "image":
            return
        current = layer.get("asset", "")
        if current:
            start_dir = str((self.config_path.parent / current).resolve().parent)
        else:
            start_dir = str(self.config_path.parent)
        filename, _ = QFileDialog.getOpenFileName(
            self, f"Choose image for layer '{name}'", start_dir,
            "Image files (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)"
        )
        if not filename:
            return
        try:
            asset_path = str(Path(filename).relative_to(self.config_path.parent))
        except ValueError:
            asset_path = filename  # keep absolute if outside project dir
        self._snapshot(f"Replace image {name.replace('_', ' ')}")
        layer["asset"] = asset_path
        self.asset_edit.setText(asset_path)
        self._fit_layer_to_asset(name)
        self.refresh_canvas()
        self.statusBar().showMessage(f"Asset for '{name}' updated — rectangle matched to the image's aspect")

    def _fit_layer_to_asset(self, name: str) -> None:
        """Reshape the layer rectangle to the image's own aspect ratio, kept centered."""
        layer = self.config["layers"].get(name)
        if not layer or layer.get("kind") != "image":
            return
        asset = resolve_asset(self.config_path, layer.get("asset", ""))
        if not asset.is_file():
            return
        native_w, native_h, bbox = image_content_info(asset)
        if bbox:
            native_w, native_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if native_w <= 0 or native_h <= 0:
            return
        canvas_w = int(self.config["canvas"].get("width", 1080))
        canvas_h = int(self.config["canvas"].get("height", 1920))
        x, y, w, h = [float(v) for v in layer.get("rect", [0.1, 0.1, 0.2, 0.2])]
        pw, ph = w * canvas_w, h * canvas_h
        scale = min(pw / native_w, ph / native_h)
        dw, dh = max(2.0, native_w * scale), max(2.0, native_h * scale)
        layer["rect"] = [
            x + (pw - dw) / 2.0 / canvas_w,
            y + (ph - dh) / 2.0 / canvas_h,
            dw / canvas_w,
            dh / canvas_h,
        ]
        if self._active_layer_name() == name:
            for key, value in zip(("x", "y", "w", "h"), layer["rect"]):
                self.geom_fields[key].blockSignals(True)
                self.geom_fields[key].setValue(value * 100.0)
                self.geom_fields[key].blockSignals(False)

    def snap_image_aspect(self):
        name = self._active_layer_name()
        if self.config["layers"].get(name, {}).get("kind") != "image":
            self.statusBar().showMessage(f"Layer '{name}' is not an image layer")
            return
        self._snapshot(f"Snap aspect {name.replace('_', ' ')}")
        self._fit_layer_to_asset(name)
        self.refresh_canvas()
        self.statusBar().showMessage(f"{name} rectangle matched to the image's aspect ratio")

    def toggle_layer_visible(self, state: int):
        name = self._active_layer_name()
        visible = state == int(Qt.CheckState.Checked.value)
        self._snapshot(f"{'Show' if visible else 'Hide'} {name.replace('_', ' ')}")
        self.config["layers"][name]["visible"] = visible
        item = self.layer_items.get(name)
        if item:
            item.setVisible(visible)  # Child resize grips hide with the layer.

    def apply_layer_changes(self):
        name = self._active_layer_name()
        layer = self.config["layers"][name]
        self._snapshot(f"Edit {name.replace('_', ' ')}")
        rect = [self.geom_fields[k].value() / 100.0 for k in ("x", "y", "w", "h")]
        rect[2] = max(0.005, rect[2])
        rect[3] = max(0.005, rect[3])
        layer["rect"] = rect
        if layer.get("kind") == "video":
            crop = [self.crop_fields[k].value() / 100.0 for k in ("x", "y", "w", "h")]
            crop[2] = max(0.005, min(crop[2], 1.0 - crop[0]))
            crop[3] = max(0.005, min(crop[3], 1.0 - crop[1]))
            crop[0] = min(crop[0], 1.0 - crop[2])
            crop[1] = min(crop[1], 1.0 - crop[3])
            layer["crop"] = crop
        self.refresh_canvas()
        if layer.get("kind") == "image":
            self.statusBar().showMessage(
                f"Updated {name} layer — drag the corner to resize freely; hold Shift to keep the aspect ratio"
            )
        else:
            self.statusBar().showMessage(f"Updated {name} layer")

    def reset_crop_to_default(self):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name, {})
        if layer.get("kind") != "video":
            self.statusBar().showMessage(f"Layer '{name}' is not a video layer")
            return
        self._snapshot(f"Reset crop {name.replace('_', ' ')}")
        try:
            fresh_cfg, _ = load_config(self.config_path)
            default_crop = fresh_cfg.get("layers", {}).get(name, {}).get("crop")
        except Exception:
            default_crop = None
        if default_crop is None:
            default_crop = self.original_config.get("layers", {}).get(name, {}).get("crop", [0.0, 0.0, 1.0, 1.0])

        layer["crop"] = [float(v) for v in default_crop]
        for key, value in zip(("x", "y", "w", "h"), layer["crop"]):
            self.crop_fields[key].blockSignals(True)
            self.crop_fields[key].setValue(value * 100.0)
            self.crop_fields[key].blockSignals(False)
        self.refresh_canvas()
        self.statusBar().showMessage(f"Reset {name} crop to config defaults")

    # -- template switching ------------------------------------------------

    def _switch_template(self, index: int):
        game_id = str(self.game_combo.itemData(index) or "")
        if not game_id or game_id == self.game:
            return
        try:
            new_config, new_path = load_config(template_path(game_id))
        except Exception as exc:
            QMessageBox.critical(self, "Template error", str(exc))
            current = self.game_combo.findData(self.game)
            if current >= 0:
                self.game_combo.blockSignals(True)
                self.game_combo.setCurrentIndex(current)
                self.game_combo.blockSignals(False)
            return
        # A different game is a different layout: undo history starts fresh.
        self._pending_undo = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_undo_buttons()
        self.game = game_id
        self.config, self.config_path = new_config, new_path
        ensure_assets(self.config, self.config_path)
        self.template_name = str(self.config.get("name") or game_id.replace("_", " ").title())
        self.setWindowTitle(f"FasTrack Video Editor — {self.template_name}")
        self._remember_template(game_id)
        self._rebuild_layer_combo()
        if self.video_path:
            video = Path(self.video_path)
            self.output_edit.setText(str(video.parent / "exports" / f"{video.stem}_{game_id}_short.mp4"))
        self.refresh_canvas()
        self.statusBar().showMessage(f"Switched to the {self.template_name} template")

    def _remember_template(self, game_id: str) -> None:
        try:
            app_state = load_state()
            app_state["last_template"] = game_id
            save_state(app_state)
        except OSError:
            pass  # Remembering the template must never break switching.

    def _rebuild_layer_combo(self):
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for name, layer in sorted(self.config["layers"].items(), key=lambda pair: pair[1].get("z", 0)):
            if name != "background":
                self.layer_combo.addItem(name.replace("_", " ").title(), name)
        self.layer_combo.blockSignals(False)
        if self.layer_combo.count():
            self.layer_combo.setCurrentIndex(0)

    # -- canvas interaction controller ------------------------------------

    def _toggle_grips(self, state: int):
        visible = state == int(Qt.CheckState.Checked.value)
        self.show_grips = visible
        for item in self.layer_items.values():
            item.set_grips_visible(visible)
        try:
            app_state = load_state()
            app_state["show_grips"] = visible
            save_state(app_state)
        except OSError:
            pass  # Preference persistence must never break the toggle.
        if visible:
            self.statusBar().showMessage("Resize grips shown")
        else:
            self.statusBar().showMessage("Resize grips hidden — use the position/size fields to resize")

    def layer_selected(self, name: str):
        index = self.layer_combo.findData(name)
        if index >= 0 and index != self.layer_combo.currentIndex():
            self.layer_combo.setCurrentIndex(index)

    def layer_interaction_started(self, name: str, action: str):
        """Capture a pre-interaction snapshot so a committed drag can be undone."""
        self._pending_undo = (f"{action} {name.replace('_', ' ')}", clone_config(self.config))

    def layer_committed(self, name: str, item: LayerItem, action: str):
        ix, iy, iw, ih = item.geometry_tuple()
        preview_w, preview_h = self._preview_size()
        rect = [ix / preview_w, iy / preview_h, iw / preview_w, ih / preview_h]
        self.config["layers"][name]["rect"] = rect
        if self._active_layer_name() == name:
            for key, value in zip(("x", "y", "w", "h"), rect):
                self.geom_fields[key].blockSignals(True)
                self.geom_fields[key].setValue(value * 100)
                self.geom_fields[key].blockSignals(False)
        if self._pending_undo:
            self._push_undo(*self._pending_undo)
            self._pending_undo = None

    # -- undo / redo -------------------------------------------------------

    def _snapshot(self, label: str) -> None:
        """Push the current state onto the undo stack before a mutation."""
        self._push_undo(label, clone_config(self.config))

    def _push_undo(self, label: str, snapshot: dict[str, Any]) -> None:
        self._undo_stack.append((label, snapshot))
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_buttons()

    def _update_undo_buttons(self):
        self.undo_button.setEnabled(bool(self._undo_stack))
        self.redo_button.setEnabled(bool(self._redo_stack))

    def undo(self):
        if not self._undo_stack:
            return
        label, snapshot = self._undo_stack.pop()
        self._redo_stack.append((label, clone_config(self.config)))
        self._restore_snapshot(snapshot)
        self.statusBar().showMessage(f"Undid: {label}")

    def redo(self):
        if not self._redo_stack:
            return
        label, snapshot = self._redo_stack.pop()
        self._undo_stack.append((label, clone_config(self.config)))
        self._restore_snapshot(snapshot)
        self.statusBar().showMessage(f"Redid: {label}")

    def _restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.config = clone_config(snapshot)
        self.refresh_canvas()
        self._update_undo_buttons()

    # -- background look ---------------------------------------------------

    def _background_changed(self):
        background = self.config.setdefault("background", {})
        for key, (slider, value_label, scale, decimals) in self.bg_sliders.items():
            value = round(slider.value() * scale, 4)
            background[key] = value
            value_label.setText(f"{value:.{decimals}f}")
        if self._bg_item is not None and self.current_frame is not None:
            # Only the backdrop changes — layer items keep their state.
            preview_w, preview_h = self._preview_size()
            background_image = render_background(self.current_frame, preview_w, preview_h, self.config)
            self._bg_item.setPixmap(QPixmap.fromImage(to_qimage_array(background_image)))

    def _bg_interaction_started(self):
        self._pending_undo = ("Tweak background", clone_config(self.config))

    def _bg_interaction_finished(self):
        if self._pending_undo is None:
            return
        label, snapshot = self._pending_undo
        self._pending_undo = None
        if self.config.get("background", {}) != snapshot.get("background", {}):
            self._push_undo(label, snapshot)

    def _sync_background_controls(self):
        background = self.config.get("background", {})
        for key, (slider, value_label, scale, decimals) in self.bg_sliders.items():
            value = float(background.get(key, BG_DEFAULTS[key]))
            slider.blockSignals(True)
            slider.setValue(int(round(value / scale)))
            slider.blockSignals(False)
            value_label.setText(f"{value:.{decimals}f}")

    def refresh_canvas(self):
        if self.current_frame is None:
            return
        canvas_w, canvas_h = self._preview_size()
        self.scene.setSceneRect(0, 0, canvas_w, canvas_h)
        self._bg_item = None
        self.scene.clear()
        self.layer_items.clear()
        background = render_background(self.current_frame, canvas_w, canvas_h, self.config)
        bg_pixmap = QPixmap.fromImage(to_qimage_array(background))
        bg_item = QGraphicsPixmapItem(bg_pixmap)
        bg_item.setZValue(0)
        self.scene.addItem(bg_item)
        self._bg_item = bg_item
        sorted_layers = sorted(self.config["layers"].items(), key=lambda pair: pair[1].get("z", 0))
        for name, layer in sorted_layers:
            if name == "background" or not layer.get("visible", True):
                continue
            image, image_aspect = layer_preview_image(
                name, layer, self.current_frame, canvas_w, canvas_h, self.config_path
            )
            if image is None:
                continue
            pixmap = QPixmap.fromImage(to_qimage_array(image))
            x, y, w, h = layer.get("rect", [0, 0, 0.1, 0.1])
            px, py, pw, ph = x * canvas_w, y * canvas_h, w * canvas_w, h * canvas_h
            preserve_aspect = False
            aspect_ratio = None
            if layer.get("kind") == "image":
                aspect_ratio = image_aspect
                if layer.get("fit", "fill") == "contain":
                    # Only the opt-in contain mode centers an aspect-locked image inside the rect.
                    ih, iw = image.shape[:2]
                    px += (pw - iw) / 2.0
                    py += (ph - ih) / 2.0
                    pw, ph = float(iw), float(ih)
                    preserve_aspect = True
            item = LayerItem(name, pixmap, (px, py, pw, ph), self,
                             preserve_aspect=preserve_aspect, aspect_ratio=aspect_ratio,
                             grip_size=HANDLE_SIZE * self.preview_scale)
            item.set_grips_visible(self.show_grips)
            item.setZValue(float(layer.get("z", 10)))
            self.scene.addItem(item)
            self.layer_items[name] = item
        self.select_layer(self.layer_combo.currentIndex())
        self._sync_background_controls()
        self.preview_view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def browse_output(self):
        suggested = self.output_edit.text().strip() or str(Path.home() / "valorant_short.mp4")
        filename, _ = QFileDialog.getSaveFileName(self, "Save rendered short", suggested, "MP4 video (*.mp4)")
        if filename:
            if not filename.lower().endswith(".mp4"):
                filename += ".mp4"
            self.output_edit.setText(filename)

    def _sync_render_config(self):
        self.config["canvas"]["width"] = self.width_spin.value()
        self.config["canvas"]["height"] = self.height_spin.value()
        self.config["canvas"]["fps"] = self.fps_spin.value()
        self.config["canvas"]["quality"] = self.quality_spin.value()

    def start_render(self):
        if not self.video_path:
            QMessageBox.information(self, "Choose footage", "Load a video recording first.")
            return
        start, end = self.in_spin.value(), self.out_spin.value()
        if end <= start:
            QMessageBox.warning(self, "Invalid trim", "OUT must be later than IN.")
            return
        output = self.output_edit.text().strip()
        if not output:
            self.browse_output()
            output = self.output_edit.text().strip()
        if not output:
            return
        if not output.lower().endswith(".mp4"):
            output += ".mp4"
        self._sync_render_config()
        encoder = str(self.encoder_combo.currentData())
        self.render_button.setEnabled(False)
        self.game_combo.setEnabled(False)
        self.progress.setValue(0)
        self.render_status.setText("Starting FFmpeg…")
        self.worker = RenderWorker(
            self.video_path, output, start, end, self.config, self.config_path, encoder
        )
        self.worker.progress_signal.connect(self._render_progress)
        self.worker.finished_signal.connect(self._render_finished)
        self.worker.start()

    def _render_progress(self, value: float, message: str):
        self.progress.setValue(max(0, min(100, int(value))))
        self.render_status.setText(message)

    def _render_finished(self, success: bool, message: str):
        self.render_button.setEnabled(True)
        self.game_combo.setEnabled(True)
        if success:
            self.progress.setValue(100)
            self.render_status.setText("Render complete")
            self.statusBar().showMessage(f"Saved: {message}")
            action = self._render_complete_dialog(Path(message))
            if action == "open":
                self._open_output_folder(Path(message))
            elif action == "play":
                self._play_output(Path(message))
        else:
            self.render_status.setText("Render failed")
            QMessageBox.critical(self, "Render failed", message)

    def _render_complete_dialog(self, output_path: Path) -> str:
        """Show the completion dialog; returns "open", "play" or "close"."""
        box = QMessageBox(self)
        box.setWindowTitle("Render complete")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"Your short is ready: <b>{output_path.name}</b>")
        box.setInformativeText(str(output_path))
        open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        play_button = box.addButton("Play video", QMessageBox.ButtonRole.ActionRole)
        close_button = box.addButton("Close", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(close_button)
        box.exec()
        if box.clickedButton() is open_button:
            return "open"
        if box.clickedButton() is play_button:
            return "play"
        return "close"

    def _open_output_folder(self, output_path: Path) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", str(output_path)])
        except OSError as exc:
            QMessageBox.warning(self, "Could not open folder", str(exc))

    def _play_output(self, output_path: Path) -> None:
        try:
            os.startfile(str(output_path))  # type: ignore[attr-defined]  # Windows
        except OSError as exc:
            QMessageBox.warning(self, "Could not play the video", str(exc))

    def save_layout(self):
        self._sync_render_config()
        try:
            save_config(self.config, self.config_path)
            self.statusBar().showMessage(f"Layout saved to {self.config_path}")
            QMessageBox.information(self, "Saved", f"Template settings saved to:\n{self.config_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Could not save config", str(exc))

    def reset_layout(self):
        self._snapshot("Reset layout")
        try:
            self.config, self.config_path = load_config(self.config_path)
            ensure_assets(self.config, self.config_path)
            self.width_spin.setValue(int(self.config["canvas"].get("width", 1080)))
            self.height_spin.setValue(int(self.config["canvas"].get("height", 1920)))
            self.fps_spin.setValue(int(self.config["canvas"].get("fps", 60)))
            self.quality_spin.setValue(int(self.config["canvas"].get("quality", 19)))
            self.refresh_canvas()
            self.statusBar().showMessage("Restored the saved template layout")
        except Exception as exc:
            QMessageBox.critical(self, "Reset failed", str(exc))

    @staticmethod
    def _format_time(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours, rem = divmod(total_ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        secs, millis = divmod(rem, 1000)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
        return f"{minutes:02d}:{secs:02d}.{millis:03d}"

    def keyPressEvent(self, event):
        key = event.key()
        text_input = isinstance(self.focusWidget(), (QComboBox, QLineEdit, QDoubleSpinBox, QSlider, QSpinBox))
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if text_input:
                super().keyPressEvent(event)  # let number fields and sliders keep their arrows
                return
            direction = -1 if key == Qt.Key.Key_Left else 1
            step = int(round(self._effective_fps())) if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
            self.step_frames(direction * step)
            event.accept()
            return
        if key in (Qt.Key.Key_I, Qt.Key.Key_O, Qt.Key.Key_J, Qt.Key.Key_K, Qt.Key.Key_L):
            if text_input:
                super().keyPressEvent(event)  # typing in a field must keep working
                return
            if key == Qt.Key.Key_I:
                self.set_in_from_playhead()
            elif key == Qt.Key.Key_O:
                self.set_out_from_playhead()
            elif key == Qt.Key.Key_J:
                self._shuttle_reverse()
            elif key == Qt.Key.Key_K:
                self._stop_playback()
            else:
                self._shuttle_forward()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.play_timer.stop()
        if self.capture is not None:
            self.capture.release()
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "Render in progress", "Wait for the current render to finish before closing FasTrack.")
            event.ignore()
            return
        event.accept()


def launch_gui(video_path: str | None, game: str, config_path: str | Path | None = None):
    app = QApplication.instance() or QApplication([])
    window = FasTrackWindow(video_path, game, config_path)
    window.show()
    return app.exec()
