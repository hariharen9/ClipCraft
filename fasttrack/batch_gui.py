"""FasTrack Batch Render — trim and render multiple clips with live 9:16 preview.

Allows adding multiple recordings, setting IN/OUT times visually, seeing an instant
live render preview according to the selected layout template (Valorant, General, etc.),
and batch-rendering all clips.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QDoubleSpinBox, QComboBox, QProgressBar, QFileDialog,
    QGroupBox, QMessageBox, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QPointF
from PySide6.QtGui import (
    QPixmap, QImage, QIcon, QColor, QPainter, QPen, QPolygonF,
    QKeyEvent, QDragEnterEvent, QDropEvent,
)

from fasttrack.renderer import probe_video, run_render
from fasttrack.config import (
    load_config, template_path, available_templates, clone_config,
    load_state, save_state, resolve_asset, contain_fit,
)
from fasttrack.assets import ensure_assets
from fasttrack.preview import to_qimage_array, render_background, normalized_crop, fit_cover, fit_contain


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


def _fmt_time(t: float) -> str:
    """Format seconds as M:SS.mmm."""
    t = max(0.0, t)
    mins = int(t) // 60
    secs = t - mins * 60
    return f"{mins}:{secs:06.3f}"


# ── Data ────────────────────────────────────────────────────────────


@dataclass
class BatchJob:
    """One clip in the batch queue."""

    video_path: Path
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    in_time: float = 0.0
    out_time: float = 0.0
    output_path: Path = field(default_factory=lambda: Path())
    status: str = "ready"  # ready | rendering | done | error
    error_msg: str = ""

    @property
    def clip_duration(self) -> float:
        return max(0.0, self.out_time - self.in_time)

    @property
    def display_name(self) -> str:
        return self.video_path.name

    def status_icon(self) -> str:
        return {
            "ready": "⏳", "rendering": "⟳", "done": "✅", "error": "❌",
        }.get(self.status, "?")


# ── Custom Widgets ──────────────────────────────────────────────────


class TrimTimeline(QWidget):
    """Custom painted timeline showing a scrubber with visual IN/OUT region."""

    seeked = Signal(float)  # emits time in seconds

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.duration = 0.0
        self.position = 0.0
        self.in_time = 0.0
        self.out_time = 0.0
        self.setMinimumHeight(44)
        self.setMaximumHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self._dragging = False
        self._margin = 12

    def set_range(self, duration: float, in_t: float, out_t: float):
        self.duration = max(0.0, duration)
        self.in_time = in_t
        self.out_time = out_t
        self.update()

    def set_position(self, t: float):
        self.position = max(0.0, min(self.duration, t))
        self.update()

    def set_in_out(self, in_t: float, out_t: float):
        self.in_time = in_t
        self.out_time = out_t
        self.update()

    def _time_to_x(self, t: float) -> float:
        if self.duration <= 0:
            return float(self._margin)
        return self._margin + (t / self.duration) * (self.width() - 2 * self._margin)

    def _x_to_time(self, x: float) -> float:
        track_w = self.width() - 2 * self._margin
        if track_w <= 0 or self.duration <= 0:
            return 0.0
        frac = (x - self._margin) / track_w
        return max(0.0, min(self.duration, frac * self.duration))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        m = self._margin
        tw = w - 2 * m
        track_y, track_h = 16, 12

        # Track background
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(48, 48, 54))
        p.drawRoundedRect(m, track_y, tw, track_h, 4, 4)

        if self.duration > 0:
            in_x = self._time_to_x(self.in_time)
            out_x = self._time_to_x(self.out_time)

            # Selected IN–OUT region
            p.setBrush(QColor(0, 140, 255, 150))
            p.drawRoundedRect(
                int(in_x), track_y, max(1, int(out_x - in_x)), track_h, 3, 3,
            )

            # IN marker (green triangle)
            p.setBrush(QColor(76, 175, 80))
            p.drawPolygon(QPolygonF([
                QPointF(in_x - 5, track_y - 4),
                QPointF(in_x + 5, track_y - 4),
                QPointF(in_x, track_y + 4),
            ]))

            # OUT marker (red triangle)
            p.setBrush(QColor(244, 67, 54))
            p.drawPolygon(QPolygonF([
                QPointF(out_x - 5, track_y - 4),
                QPointF(out_x + 5, track_y - 4),
                QPointF(out_x, track_y + 4),
            ]))

            # Playhead (white line + circle)
            px = self._time_to_x(self.position)
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.drawLine(QPointF(px, track_y - 5), QPointF(px, track_y + track_h + 5))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(QPointF(px, track_y + track_h / 2.0), 5, 5)

        # Endpoint time labels
        p.setPen(QColor(160, 160, 160))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(m, h - 2, _fmt_time(0))
        dur_text = _fmt_time(self.duration)
        p.drawText(w - m - p.fontMetrics().horizontalAdvance(dur_text), h - 2, dur_text)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.seeked.emit(self._x_to_time(event.position().x()))

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.seeked.emit(self._x_to_time(event.position().x()))

    def mouseReleaseEvent(self, event):
        self._dragging = False


# ── Render Worker ───────────────────────────────────────────────────


class BatchRenderWorker(QThread):
    """Renders batch jobs sequentially in a background thread."""

    job_started = Signal(int)                # job index
    job_progress = Signal(int, float, str)   # index, 0-100, message
    job_finished = Signal(int, bool, str)    # index, success, error_msg
    all_finished = Signal(int, int)          # done_count, error_count

    def __init__(
        self,
        jobs: list[BatchJob],
        config: dict[str, Any],
        config_path: Path,
        encoder: str,
    ):
        super().__init__()
        self.jobs = jobs
        self.config = config
        self.config_path = config_path
        self.encoder = encoder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        done, errors = 0, 0
        for i, job in enumerate(self.jobs):
            if self._cancelled:
                break
            if job.status == "done":
                done += 1
                continue
            self.job_started.emit(i)
            try:
                cfg = clone_config(self.config)

                def progress_cb(value: float, msg: str, idx=i):
                    self.job_progress.emit(idx, value, msg)

                run_render(
                    job.video_path, job.output_path,
                    job.in_time, job.out_time,
                    cfg, self.config_path, self.encoder,
                    progress_cb,
                )
                done += 1
                self.job_finished.emit(i, True, "")
            except Exception as exc:
                errors += 1
                self.job_finished.emit(i, False, str(exc))
        self.all_finished.emit(done, errors)


# ── Main Window ─────────────────────────────────────────────────────


class BatchWindow(QMainWindow):
    """Batch trim & render window with live 9:16 layout preview."""

    def __init__(self, game: str | None = None, config_path: str | None = None):
        super().__init__()
        self.setWindowTitle("FasTrack — Batch Render Studio")
        self.setMinimumSize(1100, 700)
        self.resize(1340, 820)

        icon_path = Path(__file__).resolve().parent.parent / "assets" / "fastrack.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._ui_state = load_state()

        # ── Template resolution ─────────────────────────────────────
        self._game = game or self._ui_state.get("last_template") or "valorant"
        self._config: dict[str, Any] = {}
        self._config_path: Path = Path()
        self._load_active_template(self._game, config_path)

        # ── Internal state ──────────────────────────────────────────
        self._jobs: list[BatchJob] = []
        self._active_index: int = -1
        self._capture: cv2.VideoCapture | None = None
        self._current_frame: np.ndarray | None = None
        self._playing = False
        self._render_worker: BatchRenderWorker | None = None
        self._cached_image_layers: list[dict[str, Any]] = []

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(33)  # ~30 fps preview
        self._play_timer.timeout.connect(self._play_tick)

        # ── Build UI ────────────────────────────────────────────────
        self._build_ui()
        self._cache_template_assets()
        self._update_buttons()
        self.setAcceptDrops(True)

    def _load_active_template(self, game_id: str, custom_path: str | None = None):
        """Loads and prepares the specified template JSON."""
        if custom_path:
            self._config, self._config_path = load_config(custom_path)
            self._game = Path(custom_path).stem.lower()
        else:
            tmpl = template_path(game_id)
            if not tmpl.is_file():
                # Fallback to first available
                avail = available_templates()
                if avail:
                    game_id = avail[0][0]
                    tmpl = template_path(game_id)
            self._config, self._config_path = load_config(tmpl)
            self._game = game_id

        ensure_assets(self._config, self._config_path)
        self._ui_state["last_template"] = self._game
        save_state(self._ui_state)

    # ================================================================
    #  UI CONSTRUCTION
    # ================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Main horizontal splitter: [Queue (Left) | Source Editor (Center) | Render Preview (Right)]
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(6)
        main_splitter.addWidget(self._build_queue_panel())
        main_splitter.addWidget(self._build_source_panel())
        main_splitter.addWidget(self._build_preview_panel())

        main_splitter.setStretchFactor(0, 3)  # Queue
        main_splitter.setStretchFactor(1, 7)  # Source Editor
        main_splitter.setStretchFactor(2, 4)  # Render Preview
        main_splitter.setSizes([260, 680, 360])
        root.addWidget(main_splitter, 1)

        root.addWidget(self._build_render_bar())

    # -- Left: clip queue -----------------------------------------------

    def _build_queue_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)

        header = QLabel("📁  Clip Queue")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 0;")
        vbox.addWidget(header)

        self._job_list = QListWidget()
        self._job_list.setSelectionMode(QListWidget.SingleSelection)
        self._job_list.currentRowChanged.connect(self._on_job_selected)
        self._job_list.setStyleSheet(
            "QListWidget { background-color: #1e1e24; border: 1px solid #333; border-radius: 4px; }"
            "QListWidget::item { padding: 6px 4px; border-bottom: 1px solid #2a2a32; }"
            "QListWidget::item:selected { background-color: #2b384e; }"
        )
        vbox.addWidget(self._job_list, 1)

        btns = QHBoxLayout()
        self._add_btn = QPushButton("+ Add Videos")
        self._add_btn.clicked.connect(self._add_videos_dialog)
        btns.addWidget(self._add_btn)

        self._remove_btn = QPushButton("✕ Remove")
        self._remove_btn.clicked.connect(self._remove_selected)
        btns.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_all)
        btns.addWidget(self._clear_btn)

        vbox.addLayout(btns)
        return panel

    # -- Center: source video editor (Scrubber, Trim, Controls) ---------

    def _build_source_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(4, 0, 4, 0)
        vbox.setSpacing(6)

        # Video frame display
        self._frame_label = QLabel("Select a clip from the queue\nor drag & drop videos here")
        self._frame_label.setAlignment(Qt.AlignCenter)
        self._frame_label.setMinimumSize(360, 240)
        self._frame_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._frame_label.setStyleSheet(
            "background-color: #151518; border-radius: 4px; border: 1px solid #28282c; color: #777; font-size: 14px;"
        )
        vbox.addWidget(self._frame_label, 1)

        # Current time display
        self._time_label = QLabel("0:00.000 / 0:00.000")
        self._time_label.setAlignment(Qt.AlignCenter)
        self._time_label.setStyleSheet("font-size: 13px; font-family: monospace; font-weight: bold; color: #ccc;")
        vbox.addWidget(self._time_label)

        # Custom timeline
        self._timeline = TrimTimeline()
        self._timeline.seeked.connect(self._seek_to)
        vbox.addWidget(self._timeline)

        # Playback controls
        play_row = QHBoxLayout()
        play_row.setSpacing(6)
        play_row.addStretch()

        self._prev_clip_btn = QPushButton("⏮")
        self._prev_clip_btn.setFixedSize(36, 30)
        self._prev_clip_btn.setToolTip("Previous clip in queue")
        self._prev_clip_btn.clicked.connect(self._prev_clip)
        play_row.addWidget(self._prev_clip_btn)

        self._step_back_btn = QPushButton("◀")
        self._step_back_btn.setFixedSize(36, 30)
        self._step_back_btn.setToolTip("Step back 1 frame (Left)")
        self._step_back_btn.clicked.connect(lambda: self._step_frames(-1))
        play_row.addWidget(self._step_back_btn)

        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setFixedSize(96, 32)
        self._play_btn.setToolTip("Play / Pause (Space)")
        self._play_btn.clicked.connect(self._toggle_play)
        play_row.addWidget(self._play_btn)

        self._step_fwd_btn = QPushButton("▶")
        self._step_fwd_btn.setFixedSize(36, 30)
        self._step_fwd_btn.setToolTip("Step forward 1 frame (Right)")
        self._step_fwd_btn.clicked.connect(lambda: self._step_frames(1))
        play_row.addWidget(self._step_fwd_btn)

        self._next_clip_btn = QPushButton("⏭")
        self._next_clip_btn.setFixedSize(36, 30)
        self._next_clip_btn.setToolTip("Next clip in queue")
        self._next_clip_btn.clicked.connect(self._next_clip)
        play_row.addWidget(self._next_clip_btn)

        play_row.addStretch()
        vbox.addLayout(play_row)

        # IN / OUT row
        io_row = QHBoxLayout()
        io_row.setSpacing(6)
        io_row.addStretch()

        io_row.addWidget(QLabel("IN:"))
        self._in_spin = QDoubleSpinBox()
        self._in_spin.setDecimals(3)
        self._in_spin.setSuffix(" s")
        self._in_spin.setRange(0, 86400)
        self._in_spin.setFixedWidth(100)
        self._in_spin.valueChanged.connect(self._on_in_changed)
        io_row.addWidget(self._in_spin)

        self._set_in_btn = QPushButton("Set IN [I]")
        self._set_in_btn.setFixedWidth(86)
        self._set_in_btn.clicked.connect(self._set_in_from_playhead)
        io_row.addWidget(self._set_in_btn)

        io_row.addSpacing(16)

        io_row.addWidget(QLabel("OUT:"))
        self._out_spin = QDoubleSpinBox()
        self._out_spin.setDecimals(3)
        self._out_spin.setSuffix(" s")
        self._out_spin.setRange(0, 86400)
        self._out_spin.setFixedWidth(100)
        self._out_spin.valueChanged.connect(self._on_out_changed)
        io_row.addWidget(self._out_spin)

        self._set_out_btn = QPushButton("Set OUT [O]")
        self._set_out_btn.setFixedWidth(86)
        self._set_out_btn.clicked.connect(self._set_out_from_playhead)
        io_row.addWidget(self._set_out_btn)

        io_row.addSpacing(16)
        self._clip_dur_label = QLabel("Clip: 0.000 s")
        self._clip_dur_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        io_row.addWidget(self._clip_dur_label)
        io_row.addStretch()

        vbox.addLayout(io_row)
        return panel

    # -- Right: live vertical 9:16 layout preview & template selector ---

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(4, 0, 4, 0)
        vbox.setSpacing(6)

        top_row = QHBoxLayout()
        top_lbl = QLabel("📱  Render Preview")
        top_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_row.addWidget(top_lbl)
        top_row.addStretch()
        vbox.addLayout(top_row)

        # 9:16 vertical render preview canvas
        self._render_preview_label = QLabel("9:16 Vertical Output Preview")
        self._render_preview_label.setAlignment(Qt.AlignCenter)
        self._render_preview_label.setMinimumSize(220, 390)
        self._render_preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._render_preview_label.setStyleSheet(
            "background-color: #0d0d10; border-radius: 6px; border: 2px solid #2a2a30; color: #666; font-size: 12px;"
        )
        vbox.addWidget(self._render_preview_label, 1)

        # Template & Layout Box below preview
        tmpl_group = QGroupBox("Layout Template")
        tmpl_layout = QVBoxLayout(tmpl_group)
        tmpl_layout.setContentsMargins(8, 8, 8, 8)
        tmpl_layout.setSpacing(6)

        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("Game / Preset:"))
        self._template_combo = QComboBox()
        self._populate_templates()
        self._template_combo.currentIndexChanged.connect(self._on_template_selected)
        t_row.addWidget(self._template_combo, 1)
        tmpl_layout.addLayout(t_row)

        self._template_info_lbl = QLabel("")
        self._template_info_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self._template_info_lbl.setWordWrap(True)
        tmpl_layout.addWidget(self._template_info_lbl)
        self._update_template_info_label()

        vbox.addWidget(tmpl_group)
        return panel

    # -- Bottom: render bar ---------------------------------------------

    def _build_render_bar(self) -> QWidget:
        bar = QGroupBox()
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(8, 6, 8, 6)

        hbox.addWidget(QLabel("Encoder:"))
        self._encoder_combo = QComboBox()
        self._encoder_combo.addItems(["Auto (NVENC → CPU)", "NVENC (GPU)", "CPU (x264)"])
        self._encoder_combo.setFixedWidth(160)
        hbox.addWidget(self._encoder_combo)

        hbox.addSpacing(16)

        self._render_btn = QPushButton("🚀  Render All")
        self._render_btn.setFixedHeight(36)
        self._render_btn.setMinimumWidth(160)
        self._render_btn.setStyleSheet("font-weight: bold; font-size: 13px; background-color: #0078d4; color: white;")
        self._render_btn.clicked.connect(self._start_render)
        hbox.addWidget(self._render_btn)

        self._cancel_btn = QPushButton("⬛  Cancel")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._cancel_render)
        hbox.addWidget(self._cancel_btn)

        hbox.addSpacing(16)

        prog_col = QVBoxLayout()
        prog_col.setSpacing(2)

        row1 = QHBoxLayout()
        self._current_label = QLabel("")
        self._current_label.setStyleSheet("font-size: 11px; color: #aaa;")
        row1.addWidget(self._current_label, 0)
        self._job_progress = QProgressBar()
        self._job_progress.setFixedHeight(15)
        self._job_progress.setTextVisible(True)
        row1.addWidget(self._job_progress, 1)
        prog_col.addLayout(row1)

        row2 = QHBoxLayout()
        self._overall_label = QLabel("Overall:")
        self._overall_label.setStyleSheet("font-size: 11px; color: #aaa;")
        row2.addWidget(self._overall_label, 0)
        self._overall_progress = QProgressBar()
        self._overall_progress.setFixedHeight(15)
        self._overall_progress.setTextVisible(True)
        row2.addWidget(self._overall_progress, 1)
        prog_col.addLayout(row2)

        hbox.addLayout(prog_col, 1)
        return bar

    # ================================================================
    #  TEMPLATE HANDLING
    # ================================================================

    def _populate_templates(self):
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        templates = available_templates()
        selected_idx = 0
        for i, (game_id, display_name) in enumerate(templates):
            self._template_combo.addItem(display_name, game_id)
            if game_id.lower() == self._game.lower():
                selected_idx = i
        self._template_combo.setCurrentIndex(selected_idx)
        self._template_combo.blockSignals(False)

    def _on_template_selected(self, index: int):
        if index < 0:
            return
        game_id = self._template_combo.currentData()
        if not game_id:
            return
        self._load_active_template(game_id)
        self._cache_template_assets()
        self._update_template_info_label()

        # Update default export paths for jobs that haven't rendered
        for job in self._jobs:
            if job.status == "ready":
                job.output_path = job.video_path.parent / "exports" / f"{job.video_path.stem}_{self._game}_short.mp4"

        # Redraw preview if we have an active frame
        if self._current_frame is not None:
            self._display_render_preview(self._current_frame)

    def _update_template_info_label(self):
        layers = self._config.get("layers", {})
        vid_count = sum(1 for l in layers.values() if l.get("kind") == "video" and l.get("visible", True))
        img_count = sum(1 for l in layers.values() if l.get("kind") == "image" and l.get("visible", True))
        self._template_info_lbl.setText(
            f"Active: {self._config.get('name', self._game)}  •  {vid_count} video layers, {img_count} graphics"
        )

    def _cache_template_assets(self):
        """Pre-decode and cache static image layers to keep 9:16 preview fast."""
        self._cached_image_layers.clear()
        layers = self._config.get("layers", {})
        for name, layer in sorted(layers.items(), key=lambda p: p[1].get("z", 0)):
            if layer.get("kind") == "image" and layer.get("visible", True):
                asset_path = resolve_asset(self._config_path, layer.get("asset", ""))
                if not asset_path.is_file():
                    continue
                try:
                    pil_img = Image.open(asset_path).convert("RGBA")
                    bbox = pil_img.getchannel("A").getbbox()
                    if bbox and bbox != (0, 0, pil_img.width, pil_img.height):
                        pil_img = pil_img.crop(bbox)
                    self._cached_image_layers.append({
                        "name": name,
                        "layer": layer,
                        "pil_img": pil_img,
                    })
                except Exception:
                    pass

    # ================================================================
    #  JOB MANAGEMENT
    # ================================================================

    def _add_videos_dialog(self):
        start_dir = self._ui_state.get("source_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Video Clips", start_dir,
            "Videos (*.mp4 *.mkv *.mov *.avi *.webm);;All Files (*)",
        )
        if paths:
            self._add_paths([Path(p) for p in paths])

    def _add_paths(self, paths: list[Path]):
        added, errors = 0, []
        self.setCursor(Qt.WaitCursor)
        try:
            for p in paths:
                p = p.resolve()
                if p.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                if any(j.video_path == p for j in self._jobs):
                    continue
                try:
                    info = probe_video(p)
                except Exception as exc:
                    errors.append(f"{p.name}: {exc}")
                    continue
                job = BatchJob(
                    video_path=p,
                    duration=info["duration"],
                    width=info["width"],
                    height=info["height"],
                    fps=info["fps"],
                    in_time=0.0,
                    out_time=info["duration"],
                    output_path=p.parent / "exports" / f"{p.stem}_{self._game}_short.mp4",
                )
                self._jobs.append(job)
                self._sync_list_item(len(self._jobs) - 1)
                added += 1
            if paths:
                self._ui_state["source_dir"] = str(paths[0].parent)
                save_state(self._ui_state)
        finally:
            self.unsetCursor()

        if errors:
            QMessageBox.warning(self, "Some files could not be added", "\n".join(errors))
        self._update_buttons()
        if added > 0 and self._active_index < 0:
            self._job_list.setCurrentRow(len(self._jobs) - added)

    def _sync_list_item(self, index: int):
        job = self._jobs[index]
        text = (
            f"{job.status_icon()}  {job.display_name}\n"
            f"    {job.width}×{job.height}  •  {_fmt_time(job.duration)}\n"
            f"    IN {_fmt_time(job.in_time)} → OUT {_fmt_time(job.out_time)}"
            f"  ({job.clip_duration:.1f}s)"
        )
        if job.status == "error":
            text += f"\n    ❌ {job.error_msg[:80]}"

        if index < self._job_list.count():
            item = self._job_list.item(index)
            item.setText(text)
        else:
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, 74))
            self._job_list.addItem(item)

        palette = {
            "ready": QColor(220, 220, 220),
            "rendering": QColor(100, 180, 255),
            "done": QColor(100, 200, 100),
            "error": QColor(255, 100, 100),
        }
        item.setForeground(palette.get(job.status, QColor(220, 220, 220)))

    def _remove_selected(self):
        row = self._job_list.currentRow()
        if row < 0 or row >= len(self._jobs):
            return
        if self._active_index == row:
            self._release_capture()
            self._active_index = -1
            self._frame_label.setPixmap(QPixmap())
            self._frame_label.setText("Select a clip from the queue")
            self._render_preview_label.setPixmap(QPixmap())
            self._render_preview_label.setText("9:16 Vertical Output Preview")
        self._jobs.pop(row)
        self._job_list.takeItem(row)
        if self._active_index > row:
            self._active_index -= 1
        self._update_buttons()

    def _clear_all(self):
        if not self._jobs:
            return
        answer = QMessageBox.question(
            self, "Clear All", f"Remove all {len(self._jobs)} clips from the queue?",
        )
        if answer != QMessageBox.Yes:
            return
        self._stop_play()
        self._release_capture()
        self._jobs.clear()
        self._job_list.clear()
        self._active_index = -1
        self._frame_label.setPixmap(QPixmap())
        self._frame_label.setText("Select a clip from the queue\nor drag & drop videos here")
        self._render_preview_label.setPixmap(QPixmap())
        self._render_preview_label.setText("9:16 Vertical Output Preview")
        self._update_buttons()

    # ================================================================
    #  VIDEO PREVIEW & 9:16 LIVE COMPOSITION
    # ================================================================

    def _on_job_selected(self, row: int):
        if row < 0 or row >= len(self._jobs) or row == self._active_index:
            return
        self._stop_play()
        self._release_capture()
        self._active_index = row
        job = self._jobs[row]

        cap = cv2.VideoCapture(str(job.video_path))
        if not cap.isOpened():
            QMessageBox.warning(self, "Error", f"Cannot open: {job.video_path.name}")
            return
        self._capture = cap

        self._in_spin.blockSignals(True)
        self._out_spin.blockSignals(True)
        self._in_spin.setRange(0, job.duration)
        self._out_spin.setRange(0, job.duration)
        self._in_spin.setValue(job.in_time)
        self._out_spin.setValue(job.out_time)
        self._in_spin.blockSignals(False)
        self._out_spin.blockSignals(False)

        self._timeline.set_range(job.duration, job.in_time, job.out_time)
        self._update_clip_label()
        self._update_buttons()
        self._seek_to(job.in_time)

    def _release_capture(self):
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._current_frame = None

    def _seek_to(self, t: float):
        if self._capture is None or self._active_index < 0:
            return
        job = self._jobs[self._active_index]
        t = max(0.0, min(job.duration, t))
        self._capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = self._capture.read()
        if ok and frame is not None:
            self._current_frame = frame
            self._display_frame(frame)
            self._display_render_preview(frame)
        self._timeline.set_position(t)
        self._time_label.setText(f"{_fmt_time(t)} / {_fmt_time(job.duration)}")

    def _display_frame(self, frame: np.ndarray):
        """Displays source 16:9 gameplay frame."""
        qimg = to_qimage_array(frame)
        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(
            self._frame_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._frame_label.setPixmap(scaled)

    def _display_render_preview(self, frame: np.ndarray):
        """Composes and renders the live 9:16 vertical short layout preview."""
        pw = max(180, min(360, self._render_preview_label.width()))
        ph = max(320, int(round(pw * 16 / 9)))
        if ph > self._render_preview_label.height():
            ph = max(320, self._render_preview_label.height() - 8)
            pw = int(round(ph * 9 / 16))

        # 1. Render blurred background
        comp = render_background(frame, pw, ph, self._config)

        # 2. Render video layers in z-order
        layers = self._config.get("layers", {})
        for name, layer in sorted(layers.items(), key=lambda p: p[1].get("z", 0)):
            if layer.get("kind") == "video" and name != "background" and layer.get("visible", True):
                rect = layer.get("rect", [0, 0, 1, 1])
                x = int(round(float(rect[0]) * pw))
                y = int(round(float(rect[1]) * ph))
                w = max(2, int(round(float(rect[2]) * pw)))
                h = max(2, int(round(float(rect[3]) * ph)))

                crop = layer.get("crop", [0, 0, 1, 1])
                cropped = normalized_crop(frame, crop)
                fit = layer.get("fit", "cover")
                layer_img = fit_contain(cropped, w, h) if fit == "contain" else fit_cover(cropped, w, h)

                opacity = float(layer.get("opacity", 1.0))
                # Alpha blend into composition
                x0, y0 = max(0, x), max(0, y)
                x1, y1 = min(pw, x + w), min(ph, y + h)
                src_x0 = x0 - x
                src_y0 = y0 - y
                src_w = x1 - x0
                src_h = y1 - y0

                if src_w > 0 and src_h > 0:
                    roi = comp[y0:y1, x0:x1]
                    sub = layer_img[src_y0:src_y0 + src_h, src_x0:src_x0 + src_w]
                    if opacity < 0.99:
                        comp[y0:y1, x0:x1] = cv2.addWeighted(sub, opacity, roi, 1.0 - opacity, 0)
                    else:
                        comp[y0:y1, x0:x1] = sub

        # Convert to QImage for PIL alpha rendering of logos/text
        qimg = to_qimage_array(comp)
        pix = QPixmap.fromImage(qimg)

        # 3. Draw static image layers on QPainter with high quality
        if self._cached_image_layers:
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            for item in self._cached_image_layers:
                layer = item["layer"]
                pil_img: Image.Image = item["pil_img"]
                rect = layer.get("rect", [0, 0, 0.1, 0.1])
                x = int(round(float(rect[0]) * pw))
                y = int(round(float(rect[1]) * ph))
                w = max(2, int(round(float(rect[2]) * pw)))
                h = max(2, int(round(float(rect[3]) * ph)))

                if layer.get("fit", "fill") == "contain":
                    cw, ch = contain_fit(pil_img.width, pil_img.height, w, h)
                    x += (w - cw) // 2
                    y += (h - ch) // 2
                    w, h = cw, ch

                resized_pil = pil_img.resize((w, h), Image.Resampling.LANCZOS)
                layer_qimg = to_qimage_array(np.array(resized_pil))
                opacity = float(layer.get("opacity", 1.0))
                painter.setOpacity(opacity)
                painter.drawImage(x, y, layer_qimg)
            painter.end()

        self._render_preview_label.setPixmap(pix)

    def _playhead_time(self) -> float:
        if self._capture is None:
            return 0.0
        return self._capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

    # ================================================================
    #  PLAYBACK
    # ================================================================

    def _toggle_play(self):
        if self._playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self):
        if self._capture is None or self._active_index < 0:
            return
        self._playing = True
        self._play_btn.setText("⏸  Pause")
        self._play_timer.start()

    def _stop_play(self):
        self._playing = False
        self._play_timer.stop()
        self._play_btn.setText("▶  Play")

    def _play_tick(self):
        if self._capture is None or self._active_index < 0:
            self._stop_play()
            return
        job = self._jobs[self._active_index]
        ok, frame = self._capture.read()
        t = self._capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if not ok or t >= job.out_time:
            self._seek_to(job.in_time)  # loop back to IN
            return
        self._current_frame = frame
        self._display_frame(frame)
        self._display_render_preview(frame)
        self._timeline.set_position(t)
        self._time_label.setText(f"{_fmt_time(t)} / {_fmt_time(job.duration)}")

    def _step_frames(self, count: int):
        if self._capture is None or self._active_index < 0:
            return
        self._stop_play()
        job = self._jobs[self._active_index]
        fps = job.fps if job.fps > 0 else 30.0
        t = self._playhead_time() + count / fps
        self._seek_to(max(0.0, min(job.duration, t)))

    def _prev_clip(self):
        if self._active_index > 0:
            self._job_list.setCurrentRow(self._active_index - 1)

    def _next_clip(self):
        if self._active_index < len(self._jobs) - 1:
            self._job_list.setCurrentRow(self._active_index + 1)

    # ================================================================
    #  IN / OUT POINTS
    # ================================================================

    def _set_in_from_playhead(self):
        if self._active_index < 0:
            return
        job = self._jobs[self._active_index]
        t = min(self._playhead_time(), job.out_time - 0.05)
        self._in_spin.setValue(max(0.0, t))

    def _set_out_from_playhead(self):
        if self._active_index < 0:
            return
        job = self._jobs[self._active_index]
        t = max(self._playhead_time(), job.in_time + 0.05)
        self._out_spin.setValue(min(job.duration, t))

    def _on_in_changed(self, value: float):
        if self._active_index < 0:
            return
        job = self._jobs[self._active_index]
        job.in_time = value
        self._timeline.set_in_out(job.in_time, job.out_time)
        self._sync_list_item(self._active_index)
        self._update_clip_label()
        self._update_buttons()

    def _on_out_changed(self, value: float):
        if self._active_index < 0:
            return
        job = self._jobs[self._active_index]
        job.out_time = value
        self._timeline.set_in_out(job.in_time, job.out_time)
        self._sync_list_item(self._active_index)
        self._update_clip_label()
        self._update_buttons()

    def _update_clip_label(self):
        if self._active_index < 0:
            self._clip_dur_label.setText("Clip: —")
            return
        dur = self._jobs[self._active_index].clip_duration
        self._clip_dur_label.setText(f"Clip: {dur:.3f} s")

    # ================================================================
    #  BATCH RENDER
    # ================================================================

    def _encoder_choice(self) -> str:
        return ["auto", "nvenc", "cpu"][self._encoder_combo.currentIndex()]

    def _start_render(self):
        renderable = [j for j in self._jobs if j.status in ("ready", "error")]
        if not renderable:
            QMessageBox.information(self, "Nothing to render", "No clips are ready to render.")
            return
        for j in renderable:
            if j.clip_duration < 0.1:
                QMessageBox.warning(
                    self, "Invalid trim",
                    f"{j.display_name}: clip is too short ({j.clip_duration:.3f}s).\n"
                    "Make sure OUT is at least 0.1 s after IN.",
                )
                return

        self._stop_play()
        self._render_btn.setVisible(False)
        self._cancel_btn.setVisible(True)
        self._add_btn.setEnabled(False)
        self._remove_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)
        self._template_combo.setEnabled(False)
        self._job_progress.setValue(0)
        self._overall_progress.setRange(0, len(renderable))
        self._overall_progress.setValue(0)

        self._render_worker = BatchRenderWorker(
            self._jobs, self._config, self._config_path, self._encoder_choice(),
        )
        self._render_worker.job_started.connect(self._on_render_job_started)
        self._render_worker.job_progress.connect(self._on_render_job_progress)
        self._render_worker.job_finished.connect(self._on_render_job_finished)
        self._render_worker.all_finished.connect(self._on_render_all_finished)
        self._render_worker.start()

    def _cancel_render(self):
        if self._render_worker:
            self._render_worker.cancel()
            self._current_label.setText("Cancelling after current job…")

    def _on_render_job_started(self, index: int):
        job = self._jobs[index]
        job.status = "rendering"
        self._sync_list_item(index)
        self._current_label.setText(f"Rendering: {job.display_name}")
        self._job_progress.setValue(0)

    def _on_render_job_progress(self, index: int, value: float, msg: str):
        self._job_progress.setValue(int(value))

    def _on_render_job_finished(self, index: int, success: bool, error_msg: str):
        job = self._jobs[index]
        job.status = "done" if success else "error"
        job.error_msg = error_msg
        self._sync_list_item(index)
        done_count = sum(1 for j in self._jobs if j.status == "done")
        self._overall_progress.setValue(done_count)

    def _on_render_all_finished(self, done: int, errors: int):
        self._render_btn.setVisible(True)
        self._cancel_btn.setVisible(False)
        self._add_btn.setEnabled(True)
        self._remove_btn.setEnabled(True)
        self._clear_btn.setEnabled(True)
        self._template_combo.setEnabled(True)
        self._current_label.setText("")
        self._render_worker = None
        self._update_buttons()

        if errors == 0:
            QMessageBox.information(
                self, "Batch Complete 🎉",
                f"All {done} clip(s) rendered successfully!\n\n"
                f"Outputs are in each video's  exports/  folder.",
            )
        else:
            QMessageBox.warning(
                self, "Batch Complete",
                f"Done: {done} ✅   Failed: {errors} ❌\n\n"
                "Check the queue list for error details.",
            )

    # ================================================================
    #  KEYBOARD SHORTCUTS
    # ================================================================

    def keyPressEvent(self, event: QKeyEvent):
        if isinstance(QApplication.focusWidget(), QDoubleSpinBox):
            return super().keyPressEvent(event)

        key = event.key()
        if key == Qt.Key_Space:
            self._toggle_play()
        elif key == Qt.Key_Left:
            self._step_frames(-30 if event.modifiers() & Qt.ShiftModifier else -1)
        elif key == Qt.Key_Right:
            self._step_frames(30 if event.modifiers() & Qt.ShiftModifier else 1)
        elif key == Qt.Key_I:
            self._set_in_from_playhead()
        elif key == Qt.Key_O:
            self._set_out_from_playhead()
        elif key == Qt.Key_Delete:
            if self._render_worker is None:
                self._remove_selected()
        else:
            super().keyPressEvent(event)

    # ================================================================
    #  DRAG & DROP
    # ================================================================

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS:
                    event.acceptProposedAction()
                    return

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS
        ]
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()

    # ================================================================
    #  HELPERS
    # ================================================================

    def _update_buttons(self):
        has_jobs = len(self._jobs) > 0
        has_sel = self._active_index >= 0
        busy = self._render_worker is not None

        self._remove_btn.setEnabled(has_sel and not busy)
        self._clear_btn.setEnabled(has_jobs and not busy)
        self._set_in_btn.setEnabled(has_sel)
        self._set_out_btn.setEnabled(has_sel)
        self._play_btn.setEnabled(has_sel)
        self._step_back_btn.setEnabled(has_sel)
        self._step_fwd_btn.setEnabled(has_sel)
        self._prev_clip_btn.setEnabled(has_sel and self._active_index > 0)
        self._next_clip_btn.setEnabled(has_sel and self._active_index < len(self._jobs) - 1)

        ready = sum(1 for j in self._jobs if j.status in ("ready", "error"))
        self._render_btn.setEnabled(ready > 0 and not busy)
        self._render_btn.setText(
            f"🚀  Render All  ({ready} clip{'s' if ready != 1 else ''})"
            if ready else "🚀  Render All"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_frame is not None:
            self._display_frame(self._current_frame)
            self._display_render_preview(self._current_frame)

    def closeEvent(self, event):
        self._stop_play()
        self._release_capture()
        if self._render_worker and self._render_worker.isRunning():
            self._render_worker.cancel()
            self._render_worker.wait(5000)
        super().closeEvent(event)


# ── Entry point ─────────────────────────────────────────────────────


def launch_batch_gui(game: str | None = None, config_path: str | None = None) -> int:
    """Create or reuse a QApplication and open the batch render window."""
    app = QApplication.instance() or QApplication(sys.argv)
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "fastrack.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = BatchWindow(game, config_path)
    window.show()
    return app.exec()
