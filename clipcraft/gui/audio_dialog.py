"""ClipCraft Audio & Music Studio — Dedicated dialog for sound management.

Provides visual music track loading, cutting/trimming (IN/OUT offsets),
audition playback, independent volume sliders, auto-ducking configuration,
and smooth fade-in/fade-out controls in a self-contained window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, QTimer, Signal
from PySide6.QtGui import QIcon, QDragEnterEvent, QDropEvent, QMouseEvent, QKeyEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QDoubleSpinBox,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QFrame,
    QLineEdit,
    QSizePolicy,
    QStyle,
)
import qtawesome as qta

from .constants import AUDIO_DEFAULTS, SUPPORTED_AUDIO_EXTENSIONS, get_app_icon
from ..renderer import probe_video


def _format_time_ms(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    mins, rem = divmod(total_ms, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{mins}:{secs:02d}.{millis:03d}"


class AudioScrubberSlider(QSlider):
    """QSlider that jumps directly to clicked timeline positions and supports smooth scrubbing."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(event.position().x()), self.width()
            )
            self.setValue(val)
            self.sliderMoved.emit(val)
        else:
            super().mousePressEvent(event)


class AudioStudioDialog(QDialog):
    """Separate window for managing background music, trimming, volume, ducking, and fades."""

    audio_applied = Signal(dict)

    def __init__(
        self,
        parent=None,
        audio_config: dict[str, Any] | None = None,
        default_dir: str = "",
        clip_duration: float = 0.0,
    ):
        super().__init__(parent)
        self.setWindowTitle("ClipCraft — Audio & Music Studio")
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(620, 560)
        self.resize(680, 600)
        self.setAcceptDrops(True)

        self._default_dir = default_dir or str(Path.home())
        self._clip_duration = max(0.0, clip_duration)
        self._cfg = dict(audio_config or {})

        # Track metadata
        self._bgm_duration: float = 0.0
        self._last_audition_pos_sec: float = 0.0
        self._audition_player: QMediaPlayer | None = None
        self._audition_output: QAudioOutput | None = None
        self._audition_timer: QTimer | None = None

        self._init_player()
        self._build_ui()
        self._load_config_values()

    def _init_player(self) -> None:
        self._audition_player = QMediaPlayer(self)
        self._audition_output = QAudioOutput(self)
        self._audition_player.setAudioOutput(self._audition_output)

        self._audition_timer = QTimer(self)
        self._audition_timer.setInterval(40)  # ~25 fps update
        self._audition_timer.timeout.connect(self._on_audition_tick)

        self._audition_player.durationChanged.connect(self._on_player_duration_changed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.music", color="#0078d4").pixmap(24, 24))
        header_row.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("Audio & Background Music (BGM) Studio")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        subtitle_lbl = QLabel("Add custom tracks, trim/cut music start, balance volumes, and enable auto-ducking.")
        subtitle_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        title_col.addWidget(title_lbl)
        title_col.addWidget(subtitle_lbl)
        header_row.addLayout(title_col, 1)
        layout.addLayout(header_row)

        # --- Section 1: Music Track Selection ---
        track_group = QGroupBox("Background Music Track")
        track_layout = QVBoxLayout(track_group)
        track_layout.setSpacing(8)

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("No background music loaded — drag an audio file here or click Browse…")
        file_row.addWidget(self.file_edit, 1)

        self.browse_btn = QPushButton(" Browse…")
        self.browse_btn.setIcon(qta.icon("fa5s.folder-open", color="#dcdcdc"))
        self.browse_btn.clicked.connect(self._browse_bgm)
        file_row.addWidget(self.browse_btn)

        self.clear_btn = QPushButton(" Clear")
        self.clear_btn.setIcon(qta.icon("fa5s.trash-alt", color="#e0e0e0"))
        self.clear_btn.clicked.connect(self._clear_bgm)
        file_row.addWidget(self.clear_btn)
        track_layout.addLayout(file_row)

        self.track_info_lbl = QLabel("No track selected")
        self.track_info_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        track_layout.addWidget(self.track_info_lbl)
        layout.addWidget(track_group)

        # --- Section 2: Cutting & Trimming (IN / OUT) ---
        cut_group = QGroupBox("Music Trimming & Cut Points")
        cut_layout = QVBoxLayout(cut_group)
        cut_layout.setSpacing(8)

        # Scrubber / Timeline row
        scrub_row = QHBoxLayout()
        self.audition_btn = QPushButton(" Play")
        self.audition_btn.setIcon(qta.icon("fa5s.play", color="#ffffff"))
        self.audition_btn.setFixedWidth(82)
        self.audition_btn.clicked.connect(self._toggle_audition)
        scrub_row.addWidget(self.audition_btn)

        self.scrubber = AudioScrubberSlider(Qt.Orientation.Horizontal)
        self.scrubber.setRange(0, 10000)
        self.scrubber.sliderMoved.connect(self._on_scrubber_moved)
        self.scrubber.sliderReleased.connect(self._on_scrubber_released)
        scrub_row.addWidget(self.scrubber, 1)

        self.scrub_time_lbl = QLabel("0:00.000 / 0:00.000")
        self.scrub_time_lbl.setStyleSheet("font-family: monospace; font-size: 11px; color: #ccc;")
        self.scrub_time_lbl.setMinimumWidth(125)
        self.scrub_time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scrub_row.addWidget(self.scrub_time_lbl)
        cut_layout.addLayout(scrub_row)

        # Cut start / end inputs
        points_row = QHBoxLayout()
        points_row.addWidget(QLabel("Start At (IN):"))
        self.bgm_start_spin = QDoubleSpinBox()
        self.bgm_start_spin.setRange(0.0, 3600.0)
        self.bgm_start_spin.setSingleStep(0.5)
        self.bgm_start_spin.setDecimals(2)
        self.bgm_start_spin.setSuffix(" s")
        self.bgm_start_spin.setFixedWidth(115)
        self.bgm_start_spin.valueChanged.connect(self._on_cut_spin_changed)
        points_row.addWidget(self.bgm_start_spin)

        self.set_start_btn = QPushButton(" Set from Scrubber")
        self.set_start_btn.setIcon(qta.icon("fa5s.step-forward", color="#4CAF50"))
        self.set_start_btn.setToolTip("Set music start to current scrubber position")
        self.set_start_btn.clicked.connect(self._set_start_from_scrubber)
        points_row.addWidget(self.set_start_btn)

        points_row.addSpacing(16)
        points_row.addWidget(QLabel("End At (OUT):"))
        self.bgm_end_spin = QDoubleSpinBox()
        self.bgm_end_spin.setRange(0.0, 3600.0)
        self.bgm_end_spin.setSingleStep(0.5)
        self.bgm_end_spin.setDecimals(2)
        self.bgm_end_spin.setSuffix(" s")
        self.bgm_end_spin.setFixedWidth(130)
        self.bgm_end_spin.setSpecialValueText("End of track")
        self.bgm_end_spin.valueChanged.connect(self._on_cut_spin_changed)
        points_row.addWidget(self.bgm_end_spin)

        self.set_end_btn = QPushButton(" Set from Scrubber")
        self.set_end_btn.setIcon(qta.icon("fa5s.stop", color="#f44336"))
        self.set_end_btn.setToolTip("Set music loop end to current scrubber position")
        self.set_end_btn.clicked.connect(self._set_end_from_scrubber)
        points_row.addWidget(self.set_end_btn)

        points_row.addStretch()
        cut_layout.addLayout(points_row)

        self.cut_summary_lbl = QLabel("Music will play continuously looped across the clip.")
        self.cut_summary_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
        cut_layout.addWidget(self.cut_summary_lbl)
        layout.addWidget(cut_group)

        # --- Section 3: Volumes & Levels ---
        vol_group = QGroupBox("Audio Volumes & Levels")
        vol_layout = QVBoxLayout(vol_group)
        vol_layout.setSpacing(10)

        # BGM Volume
        bgm_vol_row = QHBoxLayout()
        bgm_lbl = QLabel("Music Volume:")
        bgm_lbl.setMinimumWidth(110)
        bgm_vol_row.addWidget(bgm_lbl)

        self.bgm_slider = QSlider(Qt.Orientation.Horizontal)
        self.bgm_slider.setRange(0, 200)
        self.bgm_slider.setValue(35)
        self.bgm_slider.valueChanged.connect(self._on_bgm_vol_slider)
        bgm_vol_row.addWidget(self.bgm_slider, 1)

        self.bgm_val_lbl = QLabel("35%")
        self.bgm_val_lbl.setFixedWidth(45)
        self.bgm_val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bgm_vol_row.addWidget(self.bgm_val_lbl)
        vol_layout.addLayout(bgm_vol_row)

        # Gameplay Volume
        game_vol_row = QHBoxLayout()
        game_lbl = QLabel("Gameplay Audio:")
        game_lbl.setMinimumWidth(110)
        game_vol_row.addWidget(game_lbl)

        self.game_slider = QSlider(Qt.Orientation.Horizontal)
        self.game_slider.setRange(0, 200)
        self.game_slider.setValue(100)
        self.game_slider.valueChanged.connect(self._on_game_vol_slider)
        game_vol_row.addWidget(self.game_slider, 1)

        self.game_val_lbl = QLabel("100%")
        self.game_val_lbl.setFixedWidth(45)
        self.game_val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        game_vol_row.addWidget(self.game_val_lbl)
        vol_layout.addLayout(game_vol_row)
        layout.addWidget(vol_group)

        # --- Section 4: Auto-Ducking & Transitions ---
        fx_group = QGroupBox("Smart Mixing & Fades")
        fx_layout = QVBoxLayout(fx_group)
        fx_layout.setSpacing(8)

        self.ducking_check = QCheckBox("Enable Auto-Ducking (automatically lowers music when voice callouts or gunshots peak)")
        self.ducking_check.setChecked(True)
        fx_layout.addWidget(self.ducking_check)

        fades_row = QHBoxLayout()
        self.fade_check = QCheckBox("Smooth Audio Fades:")
        self.fade_check.setChecked(True)
        self.fade_check.toggled.connect(self._toggle_fades_enabled)
        fades_row.addWidget(self.fade_check)

        fades_row.addWidget(QLabel("Fade In:"))
        self.fade_in_spin = QDoubleSpinBox()
        self.fade_in_spin.setRange(0.0, 3.0)
        self.fade_in_spin.setSingleStep(0.1)
        self.fade_in_spin.setDecimals(1)
        self.fade_in_spin.setSuffix(" s")
        self.fade_in_spin.setValue(0.5)
        self.fade_in_spin.setFixedWidth(110)
        fades_row.addWidget(self.fade_in_spin)

        fades_row.addSpacing(16)
        fades_row.addWidget(QLabel("Fade Out:"))
        self.fade_out_spin = QDoubleSpinBox()
        self.fade_out_spin.setRange(0.0, 3.0)
        self.fade_out_spin.setSingleStep(0.1)
        self.fade_out_spin.setDecimals(1)
        self.fade_out_spin.setSuffix(" s")
        self.fade_out_spin.setValue(0.5)
        self.fade_out_spin.setFixedWidth(110)
        fades_row.addWidget(self.fade_out_spin)

        fades_row.addStretch()
        fx_layout.addLayout(fades_row)
        layout.addWidget(fx_group)

        layout.addStretch()

        # Action bar
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton(" Apply & Save")
        self.apply_btn.setIcon(qta.icon("fa5s.check", color="#ffffff"))
        self.apply_btn.setFixedWidth(120)
        self.apply_btn.setStyleSheet("font-weight: bold; background-color: #0078d4; color: white;")
        self.apply_btn.clicked.connect(self._apply_and_close)
        btn_box.addWidget(self.apply_btn)

        layout.addLayout(btn_box)

    # ================================================================
    #  CONFIG & STATE
    # ================================================================

    def _load_config_values(self) -> None:
        bgm_path = self._cfg.get("bgm_path")
        if bgm_path:
            self.set_bgm_track(str(bgm_path))

        bgm_vol = float(self._cfg.get("bgm_volume", AUDIO_DEFAULTS["bgm_volume"]))
        self.bgm_slider.setValue(int(round(bgm_vol * 100)))

        game_vol = float(self._cfg.get("gameplay_volume", AUDIO_DEFAULTS["gameplay_volume"]))
        self.game_slider.setValue(int(round(game_vol * 100)))

        bgm_start = float(self._cfg.get("bgm_start", 0.0))
        self.bgm_start_spin.setValue(bgm_start)

        bgm_end = float(self._cfg.get("bgm_end", 0.0))
        self.bgm_end_spin.setValue(bgm_end)

        auto_ducking = bool(self._cfg.get("auto_ducking", AUDIO_DEFAULTS["auto_ducking"]))
        self.ducking_check.setChecked(auto_ducking)

        fade_in = float(self._cfg.get("fade_in", AUDIO_DEFAULTS["fade_in"]))
        fade_out = float(self._cfg.get("fade_out", AUDIO_DEFAULTS["fade_out"]))
        self.fade_check.setChecked(fade_in > 0 or fade_out > 0)
        self.fade_in_spin.setValue(fade_in if fade_in > 0 else 0.5)
        self.fade_out_spin.setValue(fade_out if fade_out > 0 else 0.5)
        self._toggle_fades_enabled(self.fade_check.isChecked())
        self._update_cut_summary()

    def get_audio_config(self) -> dict[str, Any]:
        fade_enabled = self.fade_check.isChecked()
        return {
            "bgm_path": self.file_edit.text().strip() or None,
            "bgm_volume": self.bgm_slider.value() / 100.0,
            "gameplay_volume": self.game_slider.value() / 100.0,
            "bgm_start": self.bgm_start_spin.value(),
            "bgm_end": self.bgm_end_spin.value(),
            "auto_ducking": self.ducking_check.isChecked(),
            "fade_in": self.fade_in_spin.value() if fade_enabled else 0.0,
            "fade_out": self.fade_out_spin.value() if fade_enabled else 0.0,
        }

    # ================================================================
    #  MUSIC LOADING & PROBING
    # ================================================================

    def _browse_bgm(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Music Track",
            self._default_dir,
            "Audio Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.wma);;All Files (*.*)",
        )
        if file_path:
            self.set_bgm_track(file_path)

    def set_bgm_track(self, file_path: str) -> None:
        p = Path(file_path).expanduser().resolve()
        if not p.is_file():
            return
        self.file_edit.setText(str(p))

        # Probe track duration and metadata
        try:
            info = probe_video(p)
            dur = float(info.get("duration", 0.0))
            self._bgm_duration = dur
            codec = info.get("audio_codec", "audio")
            self.track_info_lbl.setText(f"{p.name} · {_format_time_ms(dur)} · {codec.upper()}")
            self.bgm_start_spin.setRange(0.0, max(0.0, dur - 0.1))
            self.bgm_end_spin.setRange(0.0, dur)
        except Exception:
            self._bgm_duration = 0.0
            self.track_info_lbl.setText(p.name)

        if self._audition_player:
            self._audition_player.setSource(QUrl.fromLocalFile(str(p)))

        self._update_cut_summary()
        start = self.bgm_start_spin.value()
        self._sync_scrubber(start)

    def _clear_bgm(self) -> None:
        self._stop_audition()
        self.file_edit.clear()
        self.track_info_lbl.setText("No track selected")
        self._bgm_duration = 0.0
        if self._audition_player:
            self._audition_player.setSource(QUrl())
        self.bgm_start_spin.setValue(0.0)
        self.bgm_end_spin.setValue(0.0)
        self._update_cut_summary()
        self._sync_scrubber(0.0)

    # ================================================================
    #  AUDITION / PREVIEW PLAYBACK
    # ================================================================

    def _toggle_audition(self) -> None:
        if not self.file_edit.text():
            return
        if self._audition_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._stop_audition()
        else:
            self._start_audition()

    def _start_audition(self) -> None:
        if not self.file_edit.text():
            return
        dur = max(0.001, self._bgm_duration)
        scrub_sec = (self.scrubber.value() / 10000.0) * dur
        start_sec = self.bgm_start_spin.value()
        end_sec = self.bgm_end_spin.value()

        # If scrubber is at the end of track or at/beyond loop end, start from start_sec
        if (end_sec > start_sec and scrub_sec >= end_sec - 0.05) or (dur > 0 and scrub_sec >= dur - 0.05):
            play_sec = start_sec
        else:
            play_sec = scrub_sec

        self._last_audition_pos_sec = play_sec
        self._audition_player.setPosition(int(play_sec * 1000))
        vol = self.bgm_slider.value() / 100.0
        self._audition_output.setVolume(min(1.0, vol))
        self._audition_player.play()
        self._audition_timer.start()
        self.audition_btn.setText(" Pause")
        self.audition_btn.setIcon(qta.icon("fa5s.pause", color="#ffffff"))

    def _stop_audition(self) -> None:
        if self._audition_player:
            self._audition_player.pause()
        if self._audition_timer:
            self._audition_timer.stop()
        self.audition_btn.setText(" Play")
        self.audition_btn.setIcon(qta.icon("fa5s.play", color="#ffffff"))

    def _on_audition_tick(self) -> None:
        if not self._audition_player:
            return
        pos_sec = self._audition_player.position() / 1000.0
        end_sec = self.bgm_end_spin.value()
        start_sec = self.bgm_start_spin.value()
        dur = max(0.001, self._bgm_duration)

        # Check loop boundary
        if (end_sec > start_sec and pos_sec >= end_sec) or (dur > 0 and pos_sec >= dur - 0.05):
            self._audition_player.setPosition(int(start_sec * 1000))
            pos_sec = start_sec

        if not self.scrubber.isSliderDown():
            self._sync_scrubber(pos_sec)

    def _on_player_duration_changed(self, dur_ms: int) -> None:
        if dur_ms > 0 and self._bgm_duration <= 0.0:
            self._bgm_duration = dur_ms / 1000.0
            self.bgm_start_spin.setRange(0.0, max(0.0, self._bgm_duration - 0.1))
            self.bgm_end_spin.setRange(0.0, self._bgm_duration)
            self._update_cut_summary()

    def _sync_scrubber(self, pos_sec: float) -> None:
        dur = max(0.001, self._bgm_duration)
        val = int(min(1.0, max(0.0, pos_sec / dur)) * 10000)
        self.scrubber.blockSignals(True)
        self.scrubber.setValue(val)
        self.scrubber.blockSignals(False)
        self.scrub_time_lbl.setText(f"{_format_time_ms(pos_sec)} / {_format_time_ms(dur)}")

    def _on_scrubber_moved(self, value: int) -> None:
        dur = max(0.001, self._bgm_duration)
        pos_sec = (value / 10000.0) * dur
        self.scrub_time_lbl.setText(f"{_format_time_ms(pos_sec)} / {_format_time_ms(dur)}")
        if self._audition_player:
            self._audition_player.setPosition(int(pos_sec * 1000))

    def _on_scrubber_released(self) -> None:
        dur = max(0.001, self._bgm_duration)
        pos_sec = (self.scrubber.value() / 10000.0) * dur
        if self._audition_player:
            self._audition_player.setPosition(int(pos_sec * 1000))

    def _set_start_from_scrubber(self) -> None:
        dur = max(0.001, self._bgm_duration)
        pos_sec = (self.scrubber.value() / 10000.0) * dur
        self.bgm_start_spin.setValue(pos_sec)

    def _set_end_from_scrubber(self) -> None:
        dur = max(0.001, self._bgm_duration)
        pos_sec = (self.scrubber.value() / 10000.0) * dur
        self.bgm_end_spin.setValue(pos_sec)

    def _on_cut_spin_changed(self) -> None:
        self._update_cut_summary()

    def _update_cut_summary(self) -> None:
        if not self.file_edit.text():
            self.cut_summary_lbl.setText("No background music loaded.")
            self.cut_summary_lbl.setStyleSheet("color: #888888; font-size: 11px;")
            return
        start = self.bgm_start_spin.value()
        end = self.bgm_end_spin.value()
        if end > start:
            dur = end - start
            self.cut_summary_lbl.setText(f"Looping section: {start:.2f}s → {end:.2f}s ({dur:.2f}s segment)")
            self.cut_summary_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
        elif start > 0:
            self.cut_summary_lbl.setText(f"Track starts at {start:.2f}s and loops continuously.")
            self.cut_summary_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
        else:
            self.cut_summary_lbl.setText("Playing from track start and looping continuously.")
            self.cut_summary_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")

    # ================================================================
    #  VOLUMES & FADES
    # ================================================================

    def _on_bgm_vol_slider(self, val: int) -> None:
        self.bgm_val_lbl.setText(f"{val}%")
        if self._audition_output:
            self._audition_output.setVolume(min(1.0, val / 100.0))

    def _on_game_vol_slider(self, val: int) -> None:
        self.game_val_lbl.setText(f"{val}%")

    def _toggle_fades_enabled(self, enabled: bool) -> None:
        self.fade_in_spin.setEnabled(enabled)
        self.fade_out_spin.setEnabled(enabled)

    # ================================================================
    #  DRAG & DROP
    # ================================================================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS and path.is_file():
                        event.acceptProposedAction()
                        self.set_bgm_track(str(path))
                        return
        super().dropEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._toggle_audition()
            event.accept()
            return
        super().keyPressEvent(event)

    # ================================================================
    #  DIALOG CLOSE
    # ================================================================

    def _apply_and_close(self) -> None:
        self._stop_audition()
        cfg = self.get_audio_config()
        self.audio_applied.emit(cfg)
        self.accept()

    def reject(self) -> None:
        self._stop_audition()
        super().reject()

    def closeEvent(self, event) -> None:
        self._stop_audition()
        super().closeEvent(event)

