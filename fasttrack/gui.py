from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSizeF
from PySide6.QtGui import QColor, QBrush, QPen, QPixmap, QPainter, QCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QProgressBar, QScrollArea, QSlider, QSpinBox, QSplitter, QStatusBar,
    QVBoxLayout, QWidget,
)

from .assets import ensure_assets
from .config import clone_config, load_config, save_config
from .preview import layer_preview_image, render_background, to_qimage_array
from .renderer import probe_video, run_render


class LayerItem(QGraphicsPixmapItem):
    """A canvas layer with drag and bottom-right resize interaction."""

    def __init__(self, name: str, pixmap: QPixmap, rect: tuple[float, float, float, float], on_change,
                 preserve_aspect: bool = False, aspect_ratio: float | None = None):
        super().__init__(pixmap)
        self.name = name
        self.on_change = on_change
        self._source_pixmap = pixmap
        self._resizing = False
        self._last_scene_pos = None
        self._min_size = 12
        self._preserve_aspect = preserve_aspect
        self._aspect_ratio = aspect_ratio
        self.setPos(rect[0], rect[1])
        self.setZValue(10)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))

    def set_source_pixmap(self, pixmap: QPixmap, keep_size: bool = True) -> None:
        self._source_pixmap = pixmap
        if keep_size:
            size = self.pixmap().size()
            self.setPixmap(pixmap.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.setPixmap(pixmap)

    def set_layer_size(self, width: float, height: float) -> None:
        width_i = max(self._min_size, int(round(width)))
        if self._preserve_aspect and self._aspect_ratio:
            height_i = max(2, int(round(width_i / self._aspect_ratio)))
        else:
            height_i = max(self._min_size, int(round(height)))
        self.setPixmap(self._source_pixmap.scaled(
            width_i, height_i, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.update()

    def mousePressEvent(self, event):
        p = event.pos()
        bounds = self.boundingRect()
        self._resizing = p.x() >= bounds.width() - 18 and p.y() >= bounds.height() - 18
        self._last_scene_pos = event.scenePos()
        self.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._last_scene_pos is None:
            event.ignore()
            return
        delta = event.scenePos() - self._last_scene_pos
        self._last_scene_pos = event.scenePos()
        if self._resizing:
            current = self.boundingRect()
            scene = self.scene()
            max_w = scene.sceneRect().width() - self.x() if scene else current.width() + delta.x()
            max_h = scene.sceneRect().height() - self.y() if scene else current.height() + delta.y()
            new_w = min(max_w, current.width() + delta.x())
            if self._preserve_aspect and self._aspect_ratio:
                # Corner resize keeps the image's original aspect ratio.
                new_w = max(self._min_size, min(new_w, max_h * self._aspect_ratio))
                self.set_layer_size(new_w, new_w / self._aspect_ratio)
            else:
                self.set_layer_size(new_w, min(max_h, current.height() + delta.y()))
        else:
            scene = self.scene()
            if scene:
                scene_rect = scene.sceneRect()
                new_x = max(0, min(scene_rect.width() - self.boundingRect().width(), self.x() + delta.x()))
                new_y = max(0, min(scene_rect.height() - self.boundingRect().height(), self.y() + delta.y()))
                self.setPos(new_x, new_y)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._last_scene_pos = None
        self._resizing = False
        self.on_change(self.name, self)
        event.accept()

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor(40, 235, 220), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.drawRect(self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5))
            handle = self.boundingRect()
            painter.setPen(QPen(QColor(10, 25, 35), 1))
            painter.setBrush(QBrush(QColor(40, 235, 220)))
            painter.drawRect(handle.right() - 8, handle.bottom() - 8, 8, 8)


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


class FastTrackWindow(QMainWindow):
    def __init__(self, video_path: str | None, game: str = "valorant", config_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("FastTrack Video Editor — Gaming Shorts")
        self.resize(1510, 940)
        self.setMinimumSize(1100, 720)
        self.config, self.config_path = load_config(config_path)
        if game.lower() != "valorant":
            raise ValueError(f"Template '{game}' is not installed yet. The first template is valorant.")
        ensure_assets(self.config, self.config_path)
        self.original_config = clone_config(self.config)
        self.game = game
        self.video_path: str | None = None
        self.video_info: dict[str, Any] | None = None
        self.capture: cv2.VideoCapture | None = None
        self.current_frame: np.ndarray | None = None
        self.playhead = 0.0
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(33)
        self.play_timer.timeout.connect(self._play_tick)
        self.pending_capture = False
        self.layer_items: dict[str, LayerItem] = {}
        self.worker: RenderWorker | None = None
        self._build_ui()
        if video_path:
            self.load_video(video_path)
        else:
            QTimer.singleShot(100, self.browse_video)

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
        self.game_combo.addItem("Valorant", "valorant")
        self.game_combo.setMinimumWidth(125)
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
        self.position_slider.sliderReleased.connect(self._capture_at_playhead)
        trim_layout.addWidget(self.position_slider)
        play_row = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_play)
        play_row.addWidget(self.play_button)
        self.set_in_button = QPushButton("Set IN ◀")
        self.set_in_button.clicked.connect(self.set_in_from_playhead)
        play_row.addWidget(self.set_in_button)
        self.set_out_button = QPushButton("Set OUT ▶")
        self.set_out_button.clicked.connect(self.set_out_from_playhead)
        play_row.addWidget(self.set_out_button)
        trim_layout.addLayout(play_row)
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
        header.addWidget(QLabel("Drag to move · drag cyan corner to resize"))
        layout.addLayout(header)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, 360, 640)
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
        geometry_form = QFormLayout(geometry_group)
        self.geom_fields = {}
        for key, title in (("x", "X"), ("y", "Y"), ("w", "Width"), ("h", "Height")):
            spin = QDoubleSpinBox()
            spin.setRange(0.1 if key in ("w", "h") else -50.0, 150.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" %")
            self.geom_fields[key] = spin
            geometry_form.addRow(title, spin)
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
        save_button = QPushButton("Save layout to config.json")
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
            self, "Choose gameplay recording", str(Path.home()),
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
        output = path.parent / "exports" / f"{path.stem}_valorant_short.mp4"
        self.output_edit.setText(str(output))
        self._capture_at_playhead()
        self.statusBar().showMessage(
            f"Loaded {path.name} · {info['width']}×{info['height']} · {info['fps']:.2f} fps · {duration:.2f}s"
        )

    def _position_changed(self, value: int):
        if not self.video_info:
            return
        duration = self.video_info["duration"]
        self.playhead = duration * value / 10000.0
        self.frame_label.setText(f"{self._format_time(self.playhead)} / {self._format_time(duration)}")

    def _capture_at_playhead(self):
        if self.capture is None:
            return
        self.capture.set(cv2.CAP_PROP_POS_MSEC, self.playhead * 1000.0)
        ok, frame = self.capture.read()
        if ok:
            self.current_frame = frame
            self.refresh_canvas()

    def _play_tick(self):
        if not self.video_info:
            return
        step = 1.0 / max(1.0, min(60.0, self.video_info.get("fps", 30.0) or 30.0))
        self.playhead += step
        if self.playhead >= self.out_spin.value():
            self.playhead = self.in_spin.value()
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(int(self.playhead / max(self.video_info["duration"], 0.001) * 10000))
        self.position_slider.blockSignals(False)
        self._position_changed(self.position_slider.value())
        self._capture_at_playhead()

    def toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play_button.setText("▶ Play")
        else:
            self.play_button.setText("Ⅱ Pause")
            self.play_timer.start()

    def set_in_from_playhead(self):
        self.in_spin.setValue(min(self.playhead, max(0.0, self.out_spin.value() - 0.05)))

    def set_out_from_playhead(self):
        self.out_spin.setValue(max(self.playhead, self.in_spin.value() + 0.05))

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
        layer["asset"] = asset_path
        self.asset_edit.setText(asset_path)
        self.refresh_canvas()
        self.statusBar().showMessage(f"Asset for '{name}' updated — click Save to persist")

    def toggle_layer_visible(self, state: int):
        name = self._active_layer_name()
        visible = state == int(Qt.CheckState.Checked.value)
        self.config["layers"][name]["visible"] = visible
        item = self.layer_items.get(name)
        if item:
            item.setVisible(visible)

    def apply_layer_changes(self):
        name = self._active_layer_name()
        layer = self.config["layers"][name]
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
        if layer.get("kind") == "image" and layer.get("fit", "contain") != "fill":
            self.statusBar().showMessage(
                f"Updated {name} layer — images keep their original aspect ratio inside the rectangle"
            )
        else:
            self.statusBar().showMessage(f"Updated {name} layer")

    def reset_crop_to_default(self):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name, {})
        if layer.get("kind") != "video":
            self.statusBar().showMessage(f"Layer '{name}' is not a video layer")
            return
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

    def _layer_dragged(self, name: str, item: LayerItem):
        rect = [item.x() / 360.0, item.y() / 640.0,
                item.boundingRect().width() / 360.0, item.boundingRect().height() / 640.0]
        self.config["layers"][name]["rect"] = rect
        if self._active_layer_name() == name:
            for key, value in zip(("x", "y", "w", "h"), rect):
                self.geom_fields[key].blockSignals(True)
                self.geom_fields[key].setValue(value * 100)
                self.geom_fields[key].blockSignals(False)

    def refresh_canvas(self):
        if self.current_frame is None:
            return
        self.scene.clear()
        self.layer_items.clear()
        canvas_w, canvas_h = 360, 640
        background = render_background(self.current_frame, canvas_w, canvas_h, self.config)
        bg_pixmap = QPixmap.fromImage(to_qimage_array(background))
        bg_item = QGraphicsPixmapItem(bg_pixmap)
        bg_item.setZValue(0)
        self.scene.addItem(bg_item)
        sorted_layers = sorted(self.config["layers"].items(), key=lambda pair: pair[1].get("z", 0))
        for name, layer in sorted_layers:
            if name == "background" or not layer.get("visible", True):
                continue
            image = layer_preview_image(
                name, layer, self.current_frame, canvas_w, canvas_h, self.config_path
            )
            if image is None:
                continue
            pixmap = QPixmap.fromImage(to_qimage_array(image))
            x, y, w, h = layer.get("rect", [0, 0, 0.1, 0.1])
            px, py, pw, ph = x * canvas_w, y * canvas_h, w * canvas_w, h * canvas_h
            preserve_aspect = False
            aspect_ratio = None
            if layer.get("kind") == "image" and layer.get("fit", "contain") != "fill":
                # The preview hugs the aspect-correct image, centered inside the configured rect.
                ih, iw = image.shape[:2]
                px += (pw - iw) / 2.0
                py += (ph - ih) / 2.0
                pw, ph = float(iw), float(ih)
                preserve_aspect = True
                aspect_ratio = iw / ih if ih else None
            item = LayerItem(name, pixmap, (px, py, pw, ph), self._layer_dragged,
                             preserve_aspect=preserve_aspect, aspect_ratio=aspect_ratio)
            item.setZValue(float(layer.get("z", 10)))
            self.scene.addItem(item)
            self.layer_items[name] = item
        self.select_layer(self.layer_combo.currentIndex())
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
        if success:
            self.progress.setValue(100)
            self.render_status.setText("Render complete")
            self.statusBar().showMessage(f"Saved: {message}")
            QMessageBox.information(self, "Render complete", f"Your short is ready:\n{message}")
        else:
            self.render_status.setText("Render failed")
            QMessageBox.critical(self, "Render failed", message)

    def save_layout(self):
        self._sync_render_config()
        try:
            save_config(self.config, self.config_path)
            self.statusBar().showMessage(f"Layout saved to {self.config_path}")
            QMessageBox.information(self, "Saved", f"Template settings saved to:\n{self.config_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Could not save config", str(exc))

    def reset_layout(self):
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

    def closeEvent(self, event):
        self.play_timer.stop()
        if self.capture is not None:
            self.capture.release()
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "Render in progress", "Wait for the current render to finish before closing FastTrack.")
            event.ignore()
            return
        event.accept()


def launch_gui(video_path: str | None, game: str, config_path: str | Path | None = None):
    app = QApplication.instance() or QApplication([])
    window = FastTrackWindow(video_path, game, config_path)
    window.show()
    return app.exec()
