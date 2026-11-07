from __future__ import annotations

import copy
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import qtawesome as qta
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, QSizeF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..assets import ensure_assets
from ..config import (
    available_templates,
    clone_config,
    image_content_info,
    load_config,
    load_state,
    migrate_legacy_config,
    resolve_asset,
    save_config,
    save_state,
    template_path,
)
from ..preview import layer_preview_image, render_background, to_qimage_array
from ..renderer import probe_video

from .canvas_items import HandleItem, LayerItem, SafeZoneOverlayItem
from .constants import (
    AUDIO_DEFAULTS,
    BG_DEFAULTS,
    BG_PRESETS,
    HANDLE_SIZE,
    MIN_LAYER_SIZE,
    RENDER_PRESETS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    format_token_time,
    _format_token_time,
)
from .crop_dialog import VisualSourceCropDialog
from .audio_dialog import AudioStudioDialog
from .layer_stack import LayerStackWidget, _make_eye_icon
from .transport_bar import TransportWidget
from .inspector import LayerInspectorWidget
from .worker import RenderWorker

class ClipCraftWindow(QMainWindow):
    def __init__(self, video_path: str | None, game: str | None = None, config_path: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("ClipCraft Video Editor — Gaming Shorts")
        self.resize(1510, 940)
        self.setMinimumSize(1100, 720)
        self.setAcceptDrops(True)
        state = load_state()
        self.config, self.config_path, self.game = self._resolve_template(game, config_path, state)
        ensure_assets(self.config, self.config_path)
        self.original_config = clone_config(self.config)
        self.template_name = str(self.config.get("name") or self.game.replace("_", " ").title())
        self.setWindowTitle(f"ClipCraft Video Editor — {self.template_name}")
        remembered = str(state.get("source_dir", ""))
        self.source_dir = remembered if remembered and Path(remembered).is_dir() else str(Path.home())
        self.show_grips = bool(state.get("show_grips", True))
        self.show_safe_zones = bool(state.get("show_safe_zones", False))
        self._safe_zone_item: SafeZoneOverlayItem | None = None
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
        audio_cfg = self.config.get("audio", {})
        self.audio_config: dict[str, Any] = dict(audio_cfg)
        self.bgm_path: str | None = self.audio_config.get("bgm_path")
        self.bgm_volume: float = float(self.audio_config.get("bgm_volume", AUDIO_DEFAULTS["bgm_volume"]))
        self.gameplay_volume: float = float(self.audio_config.get("gameplay_volume", AUDIO_DEFAULTS["gameplay_volume"]))
        self.auto_ducking: bool = bool(self.audio_config.get("auto_ducking", AUDIO_DEFAULTS["auto_ducking"]))
        self.audio_fade: bool = bool(self.audio_config.get("fade_in", AUDIO_DEFAULTS["fade_in"]) > 0 or self.audio_config.get("fade_out", AUDIO_DEFAULTS["fade_out"]) > 0)
        self._init_audio_playback()
        self.preview_sharp = bool(state.get("preview_sharp", True))
        self.preview_scale = 1.5 if self.preview_sharp else 1.0
        self.worker: RenderWorker | None = None
        self._undo_stack: list[tuple[str, dict[str, Any]]] = []
        self._redo_stack: list[tuple[str, dict[str, Any]]] = []
        self._pending_undo: tuple[str, dict[str, Any]] | None = None
        self._undo_commit_timer = QTimer(self)
        self._undo_commit_timer.setSingleShot(True)
        self._undo_commit_timer.timeout.connect(self._commit_pending_undo)
        self._updating_text_fields = False
        self._build_ui()
        undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_shortcut.activated.connect(self.undo)
        redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_shortcut.activated.connect(self.redo)
        qapp = QApplication.instance()
        if qapp:
            qapp.installEventFilter(self)
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
        self.video_edit.setReadOnly(True)
        self.video_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video_edit.setPlaceholderText("Choose a Valorant recording…")
        file_row.addWidget(self.video_edit, 1)
        self.browse_button = QPushButton(" Browse…")
        self.browse_button.setIcon(qta.icon("fa5s.folder-open", color="#dcdcdc"))
        self.browse_button.clicked.connect(self.browse_video)
        file_row.addWidget(self.browse_button)
        self.recent_button = QPushButton(" Recent ▾")
        self.recent_button.setIcon(qta.icon("fa5s.history", color="#dcdcdc"))
        self.recent_button.setToolTip("Quickly open recently used video files")
        self.recent_button.setMinimumWidth(88)
        self.recent_button.clicked.connect(self._show_recent_menu)
        file_row.addWidget(self.recent_button)
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
        self._rebuild_layer_combo()
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

        self.transport = TransportWidget()
        self.frame_label = self.transport.frame_label
        self.position_slider = self.transport.position_slider
        self.play_button = self.transport.play_button
        self.step_back_button = self.transport.step_back_button
        self.step_fwd_button = self.transport.step_fwd_button
        self.set_in_button = self.transport.set_in_button
        self.set_out_button = self.transport.set_out_button
        self.speed_combo = self.transport.speed_combo
        self.in_spin = self.transport.in_spin
        self.out_spin = self.transport.out_spin

        self.transport.play_toggled.connect(self.toggle_play)
        self.transport.step_back_requested.connect(self._step_back)
        self.transport.step_forward_requested.connect(self._step_forward)
        self.transport.set_in_requested.connect(self.set_in_from_playhead)
        self.transport.set_out_requested.connect(self.set_out_from_playhead)
        self.transport.position_changed.connect(self._position_changed)
        self.transport.scrub_started.connect(self._start_scrub)
        self.transport.scrub_finished.connect(self._finish_scrub)
        self.transport.speed_changed.connect(self._speed_changed)
        self.transport.in_out_changed.connect(self._on_in_out_changed)
        self.in_spin.valueChanged.connect(self._validate_trim)
        self.out_spin.valueChanged.connect(self._validate_trim)

        layout.addWidget(self.transport)

        bg_group = QGroupBox("Background look")
        bg_form = QFormLayout(bg_group)
        self.bg_preset_combo = QComboBox()
        self.bg_preset_combo.addItem("Custom", "")
        for p_name in BG_PRESETS:
            self.bg_preset_combo.addItem(p_name, p_name)
        self.bg_preset_combo.currentIndexChanged.connect(self._on_bg_preset_selected)
        bg_form.addRow("Preset", self.bg_preset_combo)
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

        # Sound & Music Studio
        audio_group = QGroupBox("Sound & Music")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(8, 8, 8, 8)
        audio_layout.setSpacing(6)

        self.audio_studio_btn = QPushButton(" 🎵 Audio & Music Studio…")
        self.audio_studio_btn.setFixedHeight(34)
        self.audio_studio_btn.setIcon(qta.icon("fa5s.sliders-h", color="#ffffff"))
        self.audio_studio_btn.setStyleSheet("""
            QPushButton {
                background-color: #242b38;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #3d5173;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #2f3d52;
                border-color: #0078d4;
            }
        """)
        self.audio_studio_btn.setToolTip("Open the Audio & Music Studio to trim music, set volume, and configure ducking")
        self.audio_studio_btn.clicked.connect(self.open_audio_studio)
        audio_layout.addWidget(self.audio_studio_btn)

        self.audio_badge_lbl = QLabel()
        self.audio_badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        audio_layout.addWidget(self.audio_badge_lbl)
        self._sync_audio_badge()

        layout.addWidget(audio_group)

        render_group = QGroupBox("Render settings")
        render_layout = QVBoxLayout(render_group)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output MP4 path")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_browse = QPushButton()
        output_browse.setIcon(qta.icon("fa5s.folder-open", color="#b0b0b0"))
        output_browse.setToolTip("Browse export destination")
        output_browse.setMaximumWidth(36)
        output_browse.clicked.connect(self.browse_output)
        output_row.addWidget(output_browse)
        render_layout.addLayout(output_row)

        pattern_row = QHBoxLayout()
        pattern_row.addWidget(QLabel("Pattern:"))
        self.pattern_combo = QComboBox()
        self.pattern_combo.setEditable(True)
        self.pattern_combo.setToolTip(
            "Tokens: {clip}, {game}, {in}, {out}, {dur}, {date}, {time}, {res}\n"
            "Example: {clip}_{game}_{in}-{out}"
        )
        self.pattern_combo.addItems([
            "{clip}_{game}_{in}-{out}",
            "{clip}_{game}_short",
            "{game}_{date}_{in}-{out}",
            "{clip}_short",
        ])
        state = load_state()
        saved_pat = state.get("output_pattern", "{clip}_{game}_{in}-{out}")
        self.pattern_combo.setEditText(saved_pat)
        self.pattern_combo.currentTextChanged.connect(self._on_pattern_changed)
        pattern_row.addWidget(self.pattern_combo, 1)
        self.refresh_name_btn = QPushButton()
        self.refresh_name_btn.setIcon(qta.icon("fa5s.sync-alt", color="#b0b0b0"))
        self.refresh_name_btn.setToolTip("Regenerate filename from pattern")
        self.refresh_name_btn.setFixedWidth(28)
        self.refresh_name_btn.clicked.connect(self._update_output_path)
        pattern_row.addWidget(self.refresh_name_btn)
        render_layout.addLayout(pattern_row)
        render_form = QFormLayout()
        self.render_preset_combo = QComboBox()
        self.render_preset_combo.addItem("Custom", "")
        for r_name in RENDER_PRESETS:
            self.render_preset_combo.addItem(r_name, r_name)
        self.render_preset_combo.currentIndexChanged.connect(self._on_render_preset_selected)
        render_form.addRow("Preset", self.render_preset_combo)
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
        self.render_button = QPushButton(" Render Shorts")
        self.render_button.setIcon(qta.icon("fa5s.film", color="#ffffff"))
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        return scroll

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
        self.safe_zones_check = QCheckBox("Safe zones")
        self.safe_zones_check.setChecked(self.show_safe_zones)
        self.safe_zones_check.setToolTip("Show or hide YouTube Shorts & TikTok mobile UI safe zone guides (off by default)")
        self.safe_zones_check.stateChanged.connect(self._toggle_safe_zones)
        header.addWidget(self.safe_zones_check)
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
        hint = QLabel("Select a layer on the right to tweak its position, size, and source crop live.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return panel

    def _build_inspector_panel(self) -> QWidget:
        self.inspector = LayerInspectorWidget()

        # Direct attribute references for seamless backwards compatibility
        self.layer_stack = self.inspector.layer_stack
        self.visible_check = self.inspector.visible_check
        self.opacity_slider = self.inspector.opacity_slider
        self.opacity_label = self.inspector.opacity_label
        self.text_group = self.inspector.text_group
        self.text_content_edit = self.inspector.text_content_edit
        self.font_combo = self.inspector.font_combo
        self.font_size_spin = self.inspector.font_size_spin
        self.font_bold_check = self.inspector.font_bold_check
        self.text_color_btn = self.inspector.text_color_btn
        self.stroke_color_btn = self.inspector.stroke_color_btn
        self.stroke_width_spin = self.inspector.stroke_width_spin
        self.text_align_combo = self.inspector.text_align_combo
        self.asset_group = self.inspector.asset_group
        self.asset_edit = self.inspector.asset_edit
        self.asset_button = self.inspector.asset_button
        self.geom_fields = self.inspector.geom_fields
        self.snap_aspect_button = self.inspector.snap_aspect_button
        self.crop_fields = self.inspector.crop_fields
        self.visual_crop_button = self.inspector.visual_crop_button
        self.reset_crop_button = self.inspector.reset_crop_button
        self.undo_button = self.inspector.undo_button
        self.redo_button = self.inspector.redo_button

        # Connect inspector signals
        self.inspector.layer_selected.connect(self._on_stack_layer_selected)
        self.inspector.visibility_toggled.connect(self._on_stack_visibility_toggled)
        self.inspector.reordered.connect(self._on_stack_reordered)
        self.inspector.add_text_requested.connect(self._add_text_layer)
        self.inspector.delete_layer_requested.connect(self._delete_layer)
        self.visible_check.stateChanged.connect(self.toggle_layer_visible)
        self.inspector.opacity_pressed.connect(self._opacity_slider_pressed)
        self.inspector.opacity_released.connect(self._opacity_slider_released)
        self.inspector.opacity_changed.connect(self._opacity_slider_changed)
        self.inspector.text_content_edited.connect(self._on_text_content_edited)
        self.inspector.text_prop_changed.connect(self._on_text_prop_changed)
        self.inspector.text_color_clicked.connect(self._choose_text_color)
        self.inspector.stroke_color_clicked.connect(self._choose_stroke_color)
        self.inspector.browse_asset_clicked.connect(self.browse_asset)
        self.inspector.snap_aspect_clicked.connect(self.snap_image_aspect)
        self.inspector.geometry_value_changed.connect(self._update_active_layer_geometry)
        self.inspector.geometry_editing_finished.connect(self._commit_pending_undo)
        self.inspector.crop_value_changed.connect(self._update_active_layer_crop)
        self.inspector.crop_editing_finished.connect(self._commit_pending_undo)
        self.inspector.visual_crop_clicked.connect(self.open_visual_crop_dialog)
        self.inspector.reset_crop_clicked.connect(self.reset_crop_to_default)
        self.inspector.undo_clicked.connect(self.undo)
        self.inspector.redo_clicked.connect(self.redo)
        self.inspector.save_layout_clicked.connect(self.save_layout)
        self.inspector.reset_layout_clicked.connect(self.reset_layout)

        return self.inspector

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    ext = Path(url.toLocalFile()).suffix.lower()
                    if ext in SUPPORTED_VIDEO_EXTENSIONS or ext in SUPPORTED_AUDIO_EXTENSIONS:
                        event.acceptProposedAction()
                        return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    ext = Path(url.toLocalFile()).suffix.lower()
                    if ext in SUPPORTED_VIDEO_EXTENSIONS or ext in SUPPORTED_AUDIO_EXTENSIONS:
                        event.acceptProposedAction()
                        return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    ext = path.suffix.lower()
                    if ext in SUPPORTED_AUDIO_EXTENSIONS and path.is_file():
                        event.acceptProposedAction()
                        self.set_bgm_track(str(path))
                        self.open_audio_studio()
                        return
                    elif ext in SUPPORTED_VIDEO_EXTENSIONS and path.is_file():
                        event.acceptProposedAction()
                        self.load_video(str(path))
                        return
        super().dropEvent(event)

    def _init_audio_playback(self) -> None:
        self._game_audio_player = QMediaPlayer(self)
        self._game_audio_output = QAudioOutput(self)
        self._game_audio_player.setAudioOutput(self._game_audio_output)
        self._game_audio_output.setVolume(min(1.0, max(0.0, self.gameplay_volume)))

        self._bgm_audio_player = QMediaPlayer(self)
        self._bgm_audio_output = QAudioOutput(self)
        self._bgm_audio_player.setAudioOutput(self._bgm_audio_output)
        self._bgm_audio_output.setVolume(min(1.0, max(0.0, self.bgm_volume)))

        # Backwards compatibility dummy controls
        self.bgm_label = QLineEdit(Path(self.bgm_path).name if self.bgm_path else "")
        self.bgm_vol_slider = QSlider()
        self.bgm_vol_slider.setValue(int(round(self.bgm_volume * 100)))
        self.gameplay_vol_slider = QSlider()
        self.gameplay_vol_slider.setValue(int(round(self.gameplay_volume * 100)))
        self.ducking_check = QCheckBox()
        self.ducking_check.setChecked(self.auto_ducking)
        self.audio_fade_check = QCheckBox()
        self.audio_fade_check.setChecked(self.audio_fade)

        self._sync_bgm_player()

    def _sync_bgm_player(self) -> None:
        if self.bgm_path and Path(self.bgm_path).is_file():
            self._bgm_audio_player.setSource(QUrl.fromLocalFile(str(Path(self.bgm_path).resolve())))
            self._bgm_audio_output.setVolume(min(1.0, max(0.0, self.bgm_volume)))
        else:
            self._bgm_audio_player.setSource(QUrl())

    def _sync_audio_badge(self) -> None:
        if not hasattr(self, "audio_badge_lbl"):
            return
        if self.bgm_path and Path(self.bgm_path).is_file():
            name = Path(self.bgm_path).name
            if len(name) > 22:
                name = name[:19] + "…"
            bgm_vol = int(round(self.bgm_volume * 100))
            self.audio_badge_lbl.setText(f"🎵 {name} ({bgm_vol}%)")
            self.audio_badge_lbl.setStyleSheet("font-size: 11px; color: #4CAF50;")
        else:
            game_vol = int(round(self.gameplay_volume * 100))
            self.audio_badge_lbl.setText(f"No BGM · Game: {game_vol}%")
            self.audio_badge_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")

    def open_audio_studio(self) -> None:
        self._stop_playback()
        clip_dur = max(0.0, self.out_spin.value() - self.in_spin.value())
        dlg = AudioStudioDialog(
            self,
            audio_config=self.audio_config,
            default_dir=self.source_dir,
            clip_duration=clip_dur,
        )
        dlg.audio_applied.connect(self._on_audio_studio_applied)
        dlg.exec()

    def _on_audio_studio_applied(self, new_cfg: dict[str, Any]) -> None:
        self.audio_config = dict(new_cfg)
        self.config["audio"] = self.audio_config
        self.bgm_path = self.audio_config.get("bgm_path")
        self.bgm_volume = float(self.audio_config.get("bgm_volume", AUDIO_DEFAULTS["bgm_volume"]))
        self.gameplay_volume = float(self.audio_config.get("gameplay_volume", AUDIO_DEFAULTS["gameplay_volume"]))
        self.auto_ducking = bool(self.audio_config.get("auto_ducking", AUDIO_DEFAULTS["auto_ducking"]))
        self.audio_fade = bool(self.audio_config.get("fade_in", 0) > 0 or self.audio_config.get("fade_out", 0) > 0)

        # Sync dummy controls for backwards compatibility
        self.bgm_vol_slider.setValue(int(round(self.bgm_volume * 100)))
        self.gameplay_vol_slider.setValue(int(round(self.gameplay_volume * 100)))
        self.ducking_check.setChecked(self.auto_ducking)
        self.audio_fade_check.setChecked(self.audio_fade)
        if self.bgm_path:
            self.bgm_label.setText(Path(self.bgm_path).name)
        else:
            self.bgm_label.clear()

        self._sync_bgm_player()
        if hasattr(self, "_game_audio_output"):
            self._game_audio_output.setVolume(min(1.0, max(0.0, self.gameplay_volume)))
        self._sync_audio_badge()
        self.statusBar().showMessage("Audio & Music settings applied", 3000)

    def browse_bgm(self):
        self.open_audio_studio()

    def set_bgm_track(self, filename: str):
        path = Path(filename).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, "Audio not found", str(path))
            return
        self.bgm_path = str(path)
        self.audio_config["bgm_path"] = self.bgm_path
        self._sync_bgm_player()
        self._sync_audio_badge()
        self.statusBar().showMessage(f"Loaded background music: {path.name}", 4000)

    def clear_bgm(self):
        self.bgm_path = None
        self.audio_config["bgm_path"] = None
        self._sync_bgm_player()
        self._sync_audio_badge()
        self.statusBar().showMessage("Background music removed", 3000)

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
        self._remember_recent_file(path)

        if self._game_audio_player:
            if info.get("has_audio"):
                self._game_audio_player.setSource(QUrl.fromLocalFile(str(path)))
                self._game_audio_output.setVolume(min(1.0, max(0.0, self.gameplay_volume)))
                self._game_audio_player.setPosition(0)
            else:
                self._game_audio_player.setSource(QUrl())
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
        self._update_output_path()
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

    def _remember_recent_file(self, video_path: Path) -> None:
        """Persist video path in the recent files list (top 10)."""
        resolved_str = str(video_path.resolve())
        try:
            state = load_state()
            recent: list[str] = state.get("recent_files", [])
            # Remove if already exists to bump to front
            if resolved_str in recent:
                recent.remove(resolved_str)
            recent.insert(0, resolved_str)
            # Keep at most 10 recent files
            state["recent_files"] = recent[:10]
            save_state(state)
        except OSError:
            pass

    def _show_recent_menu(self) -> None:
        """Show dropdown popup menu of recent files under the Recent button."""
        state = load_state()
        recent_files: list[str] = state.get("recent_files", [])
        menu = QMenu(self)

        valid_count = 0
        for f_str in recent_files:
            f_path = Path(f_str)
            if not f_path.is_file():
                continue
            valid_count += 1
            action = menu.addAction(f_path.name)
            action.setToolTip(f_str)
            action.triggered.connect(lambda checked=False, p=f_str: self.load_video(p))

        if valid_count == 0:
            empty_action = menu.addAction("No recent files")
            empty_action.setEnabled(False)
        else:
            menu.addSeparator()
            clear_action = menu.addAction("Clear Recent Files")
            clear_action.triggered.connect(self._clear_recent_files)

        menu.exec(self.recent_button.mapToGlobal(QPointF(0, self.recent_button.height()).toPoint()))

    def _clear_recent_files(self) -> None:
        try:
            state = load_state()
            state["recent_files"] = []
            save_state(state)
            self.statusBar().showMessage("Recent files cleared")
        except OSError:
            pass

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
        self._sync_audio_position()
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
        self.transport.set_playing(True, self._play_direction)
        if self._play_direction >= 0:
            self._start_audio_playback()
        else:
            self._stop_audio_playback()

    def _stop_playback(self) -> None:
        self._playing = False
        self._reverse_buffer.clear()  # release decoded frames promptly
        self.play_timer.stop()
        self.transport.set_playing(False)
        self._stop_audio_playback()

    def _start_audio_playback(self) -> None:
        # Gameplay audio
        if getattr(self, "_game_audio_player", None) and self.video_info and self.video_info.get("has_audio"):
            pos_ms = max(0, int(self.playhead * 1000))
            self._game_audio_player.setPosition(pos_ms)
            self._game_audio_output.setVolume(min(1.0, max(0.0, self.gameplay_volume)))
            self._game_audio_player.setPlaybackRate(self._play_speed)
            self._game_audio_player.play()

        # Background music
        if getattr(self, "_bgm_audio_player", None) and self.bgm_path and Path(self.bgm_path).is_file():
            bgm_start = float(self.audio_config.get("bgm_start", 0.0))
            bgm_end = float(self.audio_config.get("bgm_end", 0.0))
            rel = max(0.0, self.playhead - self.in_spin.value())
            pos_sec = bgm_start + rel
            dur_sec = (self._bgm_audio_player.duration() / 1000.0) if self._bgm_audio_player.duration() > 0 else 0.0
            if bgm_end > bgm_start:
                loop_len = bgm_end - bgm_start
                if loop_len > 0:
                    pos_sec = bgm_start + (rel % loop_len)
            elif dur_sec > 0:
                pos_sec = pos_sec % dur_sec
            self._bgm_audio_player.setPosition(int(pos_sec * 1000))
            self._bgm_audio_output.setVolume(min(1.0, max(0.0, self.bgm_volume)))
            self._bgm_audio_player.setPlaybackRate(self._play_speed)
            self._bgm_audio_player.play()

    def _stop_audio_playback(self) -> None:
        if getattr(self, "_game_audio_player", None):
            self._game_audio_player.pause()
        if getattr(self, "_bgm_audio_player", None):
            self._bgm_audio_player.pause()

    def _sync_audio_position(self) -> None:
        if getattr(self, "_game_audio_player", None):
            pos_ms = max(0, int(self.playhead * 1000))
            self._game_audio_player.setPosition(pos_ms)
        if getattr(self, "_bgm_audio_player", None) and self.bgm_path and Path(self.bgm_path).is_file():
            bgm_start = float(self.audio_config.get("bgm_start", 0.0))
            bgm_end = float(self.audio_config.get("bgm_end", 0.0))
            rel = max(0.0, self.playhead - self.in_spin.value())
            pos_sec = bgm_start + rel
            dur_sec = (self._bgm_audio_player.duration() / 1000.0) if self._bgm_audio_player.duration() > 0 else 0.0
            if bgm_end > bgm_start:
                loop_len = bgm_end - bgm_start
                if loop_len > 0:
                    pos_sec = bgm_start + (rel % loop_len)
            elif dur_sec > 0:
                pos_sec = pos_sec % dur_sec
            self._bgm_audio_player.setPosition(int(pos_sec * 1000))

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
        if hasattr(self, "_game_audio_player") and self._game_audio_player:
            self._game_audio_player.setPlaybackRate(self._play_speed)
        if hasattr(self, "_bgm_audio_player") and self._bgm_audio_player:
            self._bgm_audio_player.setPlaybackRate(self._play_speed)
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
        if hasattr(self, "_game_audio_player") and self._game_audio_player:
            self._game_audio_player.setPlaybackRate(self._play_speed)
        if hasattr(self, "_bgm_audio_player") and self._bgm_audio_player:
            self._bgm_audio_player.setPlaybackRate(self._play_speed)

    def _toggle_safe_zones(self, state: int) -> None:
        self.show_safe_zones = state == int(Qt.CheckState.Checked.value)
        try:
            app_state = load_state()
            app_state["show_safe_zones"] = self.show_safe_zones
            save_state(app_state)
        except OSError:
            pass
        if self._safe_zone_item is not None:
            self._safe_zone_item.setVisible(self.show_safe_zones)
        else:
            self.refresh_canvas()
        self.statusBar().showMessage("Safe-zone guides enabled (YouTube Shorts / TikTok)" if self.show_safe_zones else "Safe-zone guides hidden")

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
        name = self.layer_stack.current_layer_name()
        if name:
            return name
        for k in self.config.get("layers", {}):
            if k != "background":
                return k
        return "main"

    def select_layer(self, _index: int = 0):
        self._commit_pending_undo()
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
        if hasattr(self, 'visual_crop_button'):
            self.visual_crop_button.setEnabled(is_video and self.current_frame is not None)
        self.visible_check.blockSignals(True)
        self.visible_check.setChecked(bool(layer.get("visible", True)))
        self.visible_check.blockSignals(False)
        opacity = float(layer.get("opacity", 1.0))
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(round(opacity * 100)))
        self.opacity_slider.blockSignals(False)
        self.opacity_label.setText(f"{int(round(opacity * 100))}%")
        is_image = layer.get("kind") == "image"
        self.asset_group.setVisible(is_image)
        self.asset_edit.setText(str(layer.get("asset", "")) if is_image else "")
        self.snap_aspect_button.setEnabled(is_image)

        is_text = layer.get("kind") == "text"
        if hasattr(self, "text_group"):
            self.text_group.setVisible(is_text)
            if is_text:
                self._updating_text_fields = True
                self.text_content_edit.setText(str(layer.get("text", "Text Layer")))
                font_fam = str(layer.get("font", "Impact"))
                idx = self.font_combo.findText(font_fam, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self.font_combo.setCurrentIndex(idx)
                self.font_size_spin.setValue(int(layer.get("font_size", 48)))
                self.font_bold_check.setChecked(bool(layer.get("bold", True)))
                self.stroke_width_spin.setValue(int(layer.get("stroke_width", 3)))
                align_str = str(layer.get("align", "center")).title()
                a_idx = self.text_align_combo.findText(align_str)
                if a_idx >= 0:
                    self.text_align_combo.setCurrentIndex(a_idx)
                self._style_color_btn(self.text_color_btn, str(layer.get("color", "#FFFFFF")), "Color")
                self._style_color_btn(self.stroke_color_btn, str(layer.get("stroke_color", "#000000")), "Stroke")
                self._updating_text_fields = False

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

    def _opacity_slider_pressed(self):
        self._commit_pending_undo()
        name = self._active_layer_name()
        self._pending_undo = (f"Opacity {name.replace('_', ' ')}", clone_config(self.config))

    def _opacity_slider_released(self):
        self._commit_pending_undo()

    def _opacity_slider_changed(self, value: int):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name)
        if not layer:
            return
        if self._pending_undo is None:
            self._pending_undo = (f"Opacity {name.replace('_', ' ')}", clone_config(self.config))
        opacity = max(0.0, min(1.0, value / 100.0))
        layer["opacity"] = opacity
        self.opacity_label.setText(f"{value}%")
        item = self.layer_items.get(name)
        if item is not None:
            item.setOpacity(opacity)
        self._undo_commit_timer.start(800)

    def toggle_layer_visible(self, state: int):
        name = self._active_layer_name()
        visible = state == int(Qt.CheckState.Checked.value)
        self._snapshot(f"{'Show' if visible else 'Hide'} {name.replace('_', ' ')}")
        self.config["layers"][name]["visible"] = visible
        item = self.layer_items.get(name)
        if item:
            item.setVisible(visible)  # Child resize grips hide with the layer.
        if hasattr(self, 'layer_stack'):
            self.layer_stack.populate(self.config.get('layers', {}), name)

    def _commit_pending_undo(self):
        if self._undo_commit_timer.isActive():
            self._undo_commit_timer.stop()
        if self._pending_undo is None:
            return
        label, snapshot = self._pending_undo
        self._pending_undo = None
        if self.config != snapshot:
            self._push_undo(label, snapshot)

    def _update_active_layer_geometry(self):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name)
        if not layer:
            return
        if self._pending_undo is None:
            self._pending_undo = (f"Edit {name.replace('_', ' ')}", clone_config(self.config))
        x = self.geom_fields["x"].value() / 100.0
        y = self.geom_fields["y"].value() / 100.0
        w = max(0.005, self.geom_fields["w"].value() / 100.0)
        h = max(0.005, self.geom_fields["h"].value() / 100.0)
        layer["rect"] = [x, y, w, h]

        item = self.layer_items.get(name)
        if item is not None:
            cw, ch = self._preview_size()
            px, py, pw, ph = x * cw, y * ch, w * cw, h * ch
            if layer.get("kind") == "image" and layer.get("fit", "fill") == "contain":
                image, _ = layer_preview_image(name, layer, self.current_frame, cw, ch, self.config_path)
                if image is not None:
                    ih, iw = image.shape[:2]
                    px += (pw - iw) / 2.0
                    py += (ph - ih) / 2.0
                    pw, ph = float(iw), float(ih)
            item.set_pos_size(px, py, pw, ph)
        self._undo_commit_timer.start(800)

    def _update_active_layer_crop(self):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name)
        if not layer or layer.get("kind") != "video":
            return
        if self._pending_undo is None:
            self._pending_undo = (f"Crop {name.replace('_', ' ')}", clone_config(self.config))
        cx = self.crop_fields["x"].value() / 100.0
        cy = self.crop_fields["y"].value() / 100.0
        cw = max(0.005, min(self.crop_fields["w"].value() / 100.0, 1.0 - cx))
        ch = max(0.005, min(self.crop_fields["h"].value() / 100.0, 1.0 - cy))
        cx = min(cx, 1.0 - cw)
        cy = min(cy, 1.0 - ch)
        layer["crop"] = [cx, cy, cw, ch]

        item = self.layer_items.get(name)
        if item is not None and self.current_frame is not None:
            cw, ch = self._preview_size()
            image, _ = layer_preview_image(name, layer, self.current_frame, cw, ch, self.config_path)
            if image is not None:
                item.set_frame_pixmap(QPixmap.fromImage(to_qimage_array(image)))
        self._undo_commit_timer.start(800)

    def apply_layer_changes(self):
        """Apply changes and commit undo immediately."""
        self._update_active_layer_geometry()
        self._update_active_layer_crop()
        self._commit_pending_undo()

    def open_visual_crop_dialog(self):
        name = self._active_layer_name()
        layer = self.config["layers"].get(name)
        if not layer or layer.get("kind") != "video":
            return
        if self.current_frame is None:
            QMessageBox.information(self, "No video", "Load a gameplay recording first to crop visually.")
            return

        initial_crop = layer.get("crop", [0.0, 0.0, 1.0, 1.0])

        def on_applied(new_crop: list[float]):
            self._snapshot(f"Visual crop {name.replace('_', ' ')}")
            layer["crop"] = new_crop
            for key, val in zip(("x", "y", "w", "h"), new_crop):
                self.crop_fields[key].blockSignals(True)
                self.crop_fields[key].setValue(val * 100.0)
                self.crop_fields[key].blockSignals(False)

            # Fast update preview item
            item = self.layer_items.get(name)
            if item is not None and self.current_frame is not None:
                cw, ch = self._preview_size()
                image, _ = layer_preview_image(name, layer, self.current_frame, cw, ch, self.config_path)
                if image is not None:
                    item.set_frame_pixmap(QPixmap.fromImage(to_qimage_array(image)))
            self.statusBar().showMessage(f"Applied visual crop for '{name}': {new_crop[2]*100:.1f}% × {new_crop[3]*100:.1f}%")

        dlg = VisualSourceCropDialog(self, self.current_frame, name, initial_crop, on_applied)
        dlg.exec()

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
        self.setWindowTitle(f"ClipCraft Video Editor — {self.template_name}")
        self._remember_template(game_id)
        self._rebuild_layer_combo()
        self._update_output_path()
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
        active = self.layer_stack.current_layer_name()
        self.layer_stack.populate(self.config.get("layers", {}), active)
        self.select_layer()

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
        self.layer_stack.select_layer(name)
        self.select_layer()
    def _on_stack_layer_selected(self, name: str):
        self.select_layer()

    def _on_stack_visibility_toggled(self, name: str, visible: bool):
        self._snapshot("Show " + name.replace("_", " ") if visible else "Hide " + name.replace("_", " "))
        self.config["layers"][name]["visible"] = visible
        item = self.layer_items.get(name)
        if item:
            item.setVisible(visible)
        if self._active_layer_name() == name:
            self.visible_check.blockSignals(True)
            self.visible_check.setChecked(visible)
            self.visible_check.blockSignals(False)

    def _on_stack_reordered(self, top_to_bottom_order: list[str]):
        """Reassign Z values based on list ordering (top item = highest Z)."""
        self._snapshot("Reorder layers")
        for idx, name in enumerate(reversed(top_to_bottom_order)):
            z_val = (idx + 1) * 10
            self.config["layers"][name]["z"] = z_val
            item = self.layer_items.get(name)
            if item:
                item.setZValue(float(z_val))
        self.statusBar().showMessage("Layer stacking order updated")


    def layer_interaction_started(self, name: str, action: str):
        """Capture a pre-interaction snapshot so a committed drag can be undone."""
        self._commit_pending_undo()
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
        self._commit_pending_undo()
        if not self._undo_stack:
            return
        label, snapshot = self._undo_stack.pop()
        self._redo_stack.append((label, clone_config(self.config)))
        self._restore_snapshot(snapshot)
        self.statusBar().showMessage(f"Undid: {label}")

    def redo(self):
        self._commit_pending_undo()
        if not self._redo_stack:
            return
        label, snapshot = self._redo_stack.pop()
        self._undo_stack.append((label, clone_config(self.config)))
        self._restore_snapshot(snapshot)
        self.statusBar().showMessage(f"Redid: {label}")

    def _restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.config = clone_config(snapshot)
        self._rebuild_layer_combo()
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

    def _on_bg_preset_selected(self, index: int) -> None:
        p_name = self.bg_preset_combo.itemData(index)
        if not p_name or p_name not in BG_PRESETS:
            return
        preset = BG_PRESETS[p_name]
        self._snapshot(f"Apply background preset: {p_name}")
        background = self.config.setdefault("background", {})
        for key, val in preset.items():
            background[key] = val
        self._sync_background_controls()
        self.refresh_canvas()
        self.statusBar().showMessage(f"Applied background preset: {p_name}")

    def _on_render_preset_selected(self, index: int) -> None:
        p_name = self.render_preset_combo.itemData(index)
        if not p_name or p_name not in RENDER_PRESETS:
            return
        preset = RENDER_PRESETS[p_name]
        self.fps_spin.blockSignals(True)
        self.quality_spin.blockSignals(True)
        self.encoder_combo.blockSignals(True)

        self.fps_spin.setValue(int(preset["fps"]))
        self.quality_spin.setValue(int(preset["quality"]))
        enc_idx = self.encoder_combo.findData(preset["encoder"])
        if enc_idx >= 0:
            self.encoder_combo.setCurrentIndex(enc_idx)

        self.fps_spin.blockSignals(False)
        self.quality_spin.blockSignals(False)
        self.encoder_combo.blockSignals(False)

        # Update canvas config
        canvas = self.config.setdefault("canvas", {})
        canvas["fps"] = int(preset["fps"])
        canvas["quality"] = int(preset["quality"])
        canvas["encoder"] = preset["encoder"]

        self.statusBar().showMessage(f"Applied render preset: {p_name} (FPS={preset['fps']}, Quality={preset['quality']})")

    def _sync_background_controls(self):
        background = self.config.get("background", {})
        for key, (slider, value_label, scale, decimals) in self.bg_sliders.items():
            value = float(background.get(key, BG_DEFAULTS[key]))
            slider.blockSignals(True)
            slider.setValue(int(round(value / scale)))
            slider.blockSignals(False)
            value_label.setText(f"{value:.{decimals}f}")

        # Check if current background matches any preset
        if hasattr(self, "bg_preset_combo"):
            matched_preset = ""
            for p_name, p_vals in BG_PRESETS.items():
                if all(abs(float(background.get(k, BG_DEFAULTS[k])) - v) < 0.005 for k, v in p_vals.items()):
                    matched_preset = p_name
                    break
            idx = self.bg_preset_combo.findData(matched_preset)
            self.bg_preset_combo.blockSignals(True)
            self.bg_preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.bg_preset_combo.blockSignals(False)

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
            item.setOpacity(max(0.0, min(1.0, float(layer.get("opacity", 1.0)))))
            self.scene.addItem(item)
            self.layer_items[name] = item
        safe_item = SafeZoneOverlayItem(canvas_w, canvas_h)
        safe_item.setVisible(self.show_safe_zones)
        self.scene.addItem(safe_item)
        self._safe_zone_item = safe_item
        if hasattr(self, 'layer_stack'):
            self.layer_stack.populate(self.config.get('layers', {}), self._active_layer_name())
        self.select_layer()
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
        self.config["audio"] = dict(self.audio_config)

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
            self.video_path, output, start, end, self.config, self.config_path, encoder,
            audio_config=self.config.get("audio")
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

    # -- Filename Auto-Naming & Tokens (#9) ----------------------------------

    def _on_pattern_changed(self, text: str) -> None:
        try:
            state = load_state()
            state["output_pattern"] = text.strip()
            save_state(state)
        except OSError:
            pass
        self._update_output_path()

    def _on_in_out_changed(self, _val: float) -> None:
        self._update_output_path()

    def _compute_output_filename(self, pattern: str | None = None) -> str:
        if not pattern:
            pattern = self.pattern_combo.currentText().strip() or "{clip}_{game}_{in}-{out}"
        clip = Path(self.video_path).stem if self.video_path else "clip"
        game = self.game if hasattr(self, "game") else "short"
        in_val = self.in_spin.value() if hasattr(self, "in_spin") else 0.0
        out_val = self.out_spin.value() if hasattr(self, "out_spin") else 0.0
        in_str = _format_token_time(in_val)
        out_str = _format_token_time(out_val)
        dur_str = _format_token_time(max(0.0, out_val - in_val))
        now = time.strftime("%Y-%m-%d")
        now_time = time.strftime("%H%M%S")
        canvas = self.config.get("canvas", {})
        res_str = f"{canvas.get('width', 1080)}x{canvas.get('height', 1920)}"

        name = pattern
        name = name.replace("{clip}", clip)
        name = name.replace("{game}", game)
        name = name.replace("{in}", in_str)
        name = name.replace("{out}", out_str)
        name = name.replace("{dur}", dur_str)
        name = name.replace("{date}", now)
        name = name.replace("{time}", now_time)
        name = name.replace("{res}", res_str)
        if not name.lower().endswith(".mp4"):
            name += ".mp4"
        return name

    def _update_output_path(self) -> None:
        if not getattr(self, "video_path", None):
            return
        video_p = Path(self.video_path)
        pattern = self.pattern_combo.currentText().strip() or "{clip}_{game}_{in}-{out}"
        filename = self._compute_output_filename(pattern)
        out_dir = video_p.parent / "exports"
        self.output_edit.setText(str(out_dir / filename))


    # -- Editable Text Layers (#17) -----------------------------------------

    def _add_text_layer(self) -> None:
        layers = self.config.get("layers", {})
        idx = 1
        while f"text_{idx}" in layers:
            idx += 1
        layer_name = f"text_{idx}"
        max_z = max((l.get("z", 0) for l in layers.values()), default=10)
        self._snapshot(f"Add text layer {layer_name}")
        layers[layer_name] = {
            "kind": "text",
            "text": "Your Text Here",
            "font": "Impact",
            "font_size": 48,
            "bold": True,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": 3,
            "align": "center",
            "rect": [0.1, 0.45, 0.8, 0.08],
            "z": max_z + 10,
            "opacity": 1.0,
            "visible": True,
        }
        self.layer_stack.populate(self.config.get("layers", {}), layer_name)
        self.select_layer()
        self.refresh_canvas()
        self.statusBar().showMessage(f"Added text layer '{layer_name}'")

    def _delete_layer(self, name: str) -> None:
        if name in ("background", "main"):
            return
        self._snapshot(f"Delete layer {name.replace('_', ' ')}")
        self.config.get("layers", {}).pop(name, None)
        self.layer_stack.populate(self.config.get("layers", {}))
        self.select_layer()
        self.refresh_canvas()
        self.statusBar().showMessage(f"Deleted layer '{name}'")

    def _on_text_content_edited(self, text: str) -> None:
        name = self._active_layer_name()
        layer = self.config.get("layers", {}).get(name, {})
        if layer.get("kind") != "text":
            return
        if self._pending_undo is None:
            self._pending_undo = (f"Edit text {name}", clone_config(self.config))
        layer["text"] = text
        self.refresh_canvas()
        self._undo_commit_timer.start(800)

    def _on_text_prop_changed(self) -> None:
        if getattr(self, "_updating_text_fields", False):
            return
        name = self._active_layer_name()
        layer = self.config.get("layers", {}).get(name, {})
        if layer.get("kind") != "text":
            return
        self._snapshot(f"Change text styling {name}")
        layer["font"] = self.font_combo.currentText()
        layer["font_size"] = self.font_size_spin.value()
        layer["bold"] = self.font_bold_check.isChecked()
        layer["stroke_width"] = self.stroke_width_spin.value()
        layer["align"] = self.text_align_combo.currentText().lower()
        self.refresh_canvas()

    def _choose_text_color(self) -> None:
        name = self._active_layer_name()
        layer = self.config.get("layers", {}).get(name, {})
        current = QColor(layer.get("color", "#FFFFFF"))
        color = QColorDialog.getColor(current, self, "Choose Text Color")
        if color.isValid():
            hex_str = color.name().upper()
            self._snapshot(f"Text color {name}")
            layer["color"] = hex_str
            self._style_color_btn(self.text_color_btn, hex_str, "Color")
            self.refresh_canvas()

    def _choose_stroke_color(self) -> None:
        name = self._active_layer_name()
        layer = self.config.get("layers", {}).get(name, {})
        current = QColor(layer.get("stroke_color", "#000000"))
        color = QColorDialog.getColor(current, self, "Choose Stroke Color")
        if color.isValid():
            hex_str = color.name().upper()
            self._snapshot(f"Stroke color {name}")
            layer["stroke_color"] = hex_str
            self._style_color_btn(self.stroke_color_btn, hex_str, "Stroke")
            self.refresh_canvas()

    def _style_color_btn(self, btn: QPushButton, hex_color: str, label: str) -> None:
        col = QColor(hex_color)
        lum = (0.299 * col.red() + 0.587 * col.green() + 0.114 * col.blue())
        text_col = "#000" if lum > 140 else "#fff"
        btn.setText(label)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_color}; color: {text_col}; "
            f"border: 1px solid #555; border-radius: 3px; font-weight: bold; font-size: 11px; }}"
        )

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if self.isActiveWindow() and (watched is self or self.isAncestorOf(watched)):
                key = event.key()
                modifiers = event.modifiers()
                shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

                # 1. Output file edit: user is typing a filename
                if watched is getattr(self, "output_edit", None):
                    return super().eventFilter(watched, event)

                # 2. Spin boxes: Left/Right moves cursor in number text; Up/Down steps number
                is_spin = isinstance(watched, (QSpinBox, QDoubleSpinBox)) or isinstance(
                    getattr(watched, "parent", lambda: None)(), (QSpinBox, QDoubleSpinBox)
                )
                if is_spin:
                    if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
                        return super().eventFilter(watched, event)

                # 3. Combo boxes: Left/Right/Up/Down navigates options
                is_combo = isinstance(watched, QComboBox) or isinstance(
                    getattr(watched, "parent", lambda: None)(), QComboBox
                )
                if is_combo:
                    if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
                        return super().eventFilter(watched, event)

                # 4. Background look & opacity sliders: Left/Right nudges slider unless Shift is held
                bg_slider_widgets = [s for s, _, _, _ in getattr(self, "bg_sliders", {}).values()]
                if watched in bg_slider_widgets or watched is getattr(self, "opacity_slider", None):
                    if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not shift:
                        return super().eventFilter(watched, event)

                # --- Video editor hotkeys ---
                if key == Qt.Key.Key_Space:
                    self.toggle_play()
                    return True
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    direction = -1 if key == Qt.Key.Key_Left else 1
                    step = int(round(self._effective_fps())) if shift else 1
                    self.step_frames(direction * step)
                    return True
                if key == Qt.Key.Key_I:
                    self.set_in_from_playhead()
                    return True
                if key == Qt.Key.Key_O:
                    self.set_out_from_playhead()
                    return True
                if key == Qt.Key.Key_J:
                    self._shuttle_reverse()
                    return True
                if key == Qt.Key.Key_K:
                    self._stop_playback()
                    return True
                if key == Qt.Key.Key_L:
                    self._shuttle_forward()
                    return True

        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        qapp = QApplication.instance()
        if qapp:
            qapp.removeEventFilter(self)
        self.play_timer.stop()
        self._stop_audio_playback()
        if hasattr(self, "_game_audio_player") and self._game_audio_player:
            self._game_audio_player.stop()
        if hasattr(self, "_bgm_audio_player") and self._bgm_audio_player:
            self._bgm_audio_player.stop()
        if self.capture is not None:
            self.capture.release()
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "Render in progress", "Wait for the current render to finish before closing ClipCraft.")
            event.ignore()
            return
        event.accept()


def launch_gui(video_path: str | None, game: str, config_path: str | Path | None = None):
    app = QApplication.instance() or QApplication([])
    window = ClipCraftWindow(video_path, game, config_path)
    window.show()
    return app.exec()
