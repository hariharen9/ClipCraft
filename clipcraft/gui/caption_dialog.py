"""ClipCraft AI Auto-Captions Studio — Dedicated dialog for Whisper transcription and subtitle styling.

Provides local speech-to-text generation via faster-whisper, word-by-word karaoke
highlighting, TikTok/Shorts safe zone positioning, transcript editing, and ASS/SRT export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QProgressBar,
    QGroupBox,
    QCheckBox,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QFrame,
)
import qtawesome as qta

from ..captions import (
    CaptionCue,
    CaptionWord,
    CaptionStyle,
    transcribe_video_audio,
    export_to_ass,
    export_to_srt,
    format_srt_timestamp,
)


class TranscriptionWorker(QThread):
    """Background worker for local faster-whisper transcription."""
    progress = Signal(float, str)
    finished = Signal(list, str)
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float | None,
        model_size: str,
        language: str | None,
        max_words_per_cue: int = 4,
    ) -> None:
        super().__init__()
        self.video_path = video_path
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.model_size = model_size
        self.language = language
        self.max_words_per_cue = max_words_per_cue

    def run(self) -> None:
        try:
            def on_progress(frac: float, msg: str) -> None:
                self.progress.emit(frac, msg)

            cues, lang = transcribe_video_audio(
                video_path=self.video_path,
                start_sec=self.start_sec,
                end_sec=self.end_sec,
                model_size=self.model_size,
                language=self.language,
                progress_callback=on_progress,
                max_words_per_cue=self.max_words_per_cue,
            )
            self.finished.emit(cues, lang)
        except Exception as exc:
            self.error.emit(str(exc))


COLOR_PRESETS = [
    ("Neon Yellow (#FFE600)", "#FFE600"),
    ("Cyber Green (#00FF66)", "#00FF66"),
    ("Electric Cyan (#00E5FF)", "#00E5FF"),
    ("Hot Coral (#FF3366)", "#FF3366"),
    ("Pure White (#FFFFFF)", "#FFFFFF"),
]


class CaptionStudioDialog(QDialog):
    """Separate window for generating, editing, and styling Whisper auto-captions."""

    captions_applied = Signal(dict)

    def __init__(
        self,
        parent=None,
        video_path: str | None = None,
        clip_in: float = 0.0,
        clip_out: float | None = None,
        captions_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Auto-Captions Studio — Local Whisper")
        self.resize(760, 680)
        self.setMinimumSize(640, 560)

        self.video_path = video_path
        self.clip_in = clip_in
        self.clip_out = clip_out
        self._cfg = captions_config or {}

        # Parse initial state
        raw_cues = self._cfg.get("cues", [])
        self.cues: list[CaptionCue] = [CaptionCue.from_dict(c) for c in raw_cues]
        self.style = CaptionStyle.from_dict(self._cfg.get("style"))
        self.enabled = bool(self._cfg.get("enabled", True if self.cues else False))

        self._worker: TranscriptionWorker | None = None

        self._build_ui()
        self._load_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 16, 18, 16)

        # Header
        header = QHBoxLayout()
        header_icon = QLabel()
        header_icon.setPixmap(qta.icon("fa5s.closed-captioning", color="#00e5ff").pixmap(32, 32))
        header.addWidget(header_icon)

        title_col = QVBoxLayout()
        title_lbl = QLabel("AI Auto-Captions & Subtitles Studio")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        subtitle_lbl = QLabel("Generate high-retention word-by-word animated captions placed in the vertical safe zone.")
        subtitle_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        title_col.addWidget(title_lbl)
        title_col.addWidget(subtitle_lbl)
        header.addLayout(title_col, 1)

        self.enable_check = QCheckBox("Enable Captions")
        self.enable_check.setStyleSheet("font-weight: bold; font-size: 13px; color: #00e5ff;")
        self.enable_check.setChecked(self.enabled)
        header.addWidget(self.enable_check)
        layout.addLayout(header)

        # Section 1: AI Generation & Model
        gen_group = QGroupBox("Whisper Speech-to-Text Transcription")
        gen_layout = QVBoxLayout(gen_group)
        gen_layout.setSpacing(8)

        gen_controls = QHBoxLayout()
        gen_controls.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "base (Recommended · Fast & Accurate)",
            "tiny (Fastest · ~75MB)",
            "small (High Accuracy · ~460MB)",
        ])
        gen_controls.addWidget(self.model_combo, 1)

        gen_controls.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["Auto-Detect", "en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"])
        gen_controls.addWidget(self.lang_combo)

        # Detect compute device
        dev_desc = "CPU (int8)"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                dev_desc = "GPU (CUDA float16)"
        except Exception:
            pass
        dev_badge = QLabel(f"⚡ {dev_desc}")
        dev_badge.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
        gen_controls.addWidget(dev_badge)

        self.transcribe_btn = QPushButton(" Generate Captions")
        self.transcribe_btn.setIcon(qta.icon("fa5s.magic", color="#ffffff"))
        self.transcribe_btn.setStyleSheet("font-weight: bold; background-color: #0078d4; color: white; padding: 6px 14px;")
        self.transcribe_btn.clicked.connect(self._start_transcription)
        gen_controls.addWidget(self.transcribe_btn)
        gen_layout.addLayout(gen_controls)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        gen_layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Ready to transcribe audio from current clip.")
        self.status_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        gen_layout.addWidget(self.status_lbl)
        layout.addWidget(gen_group)

        # Section 2: Style & Safe Zone Settings
        style_group = QGroupBox("Caption Styling & Safe Zone Placement")
        style_layout = QVBoxLayout(style_group)
        style_layout.setSpacing(8)

        # Row 1: Colors & Typography
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Highlight Color:"))
        self.highlight_combo = QComboBox()
        for label, hex_val in COLOR_PRESETS:
            self.highlight_combo.addItem(label, hex_val)
        row1.addWidget(self.highlight_combo)

        row1.addSpacing(12)
        row1.addWidget(QLabel("Font Size:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(24, 120)
        self.size_spin.setValue(self.style.font_size)
        self.size_spin.setSuffix(" pt")
        self.size_spin.setFixedWidth(85)
        row1.addWidget(self.size_spin)

        row1.addSpacing(12)
        row1.addWidget(QLabel("Outline Stroke:"))
        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(0, 20)
        self.stroke_spin.setValue(self.style.stroke_width)
        self.stroke_spin.setSuffix(" px")
        self.stroke_spin.setFixedWidth(80)
        row1.addWidget(self.stroke_spin)

        row1.addStretch()
        style_layout.addLayout(row1)

        # Row 2: Toggles & Position
        row2 = QHBoxLayout()
        self.word_highlight_check = QCheckBox("Word-by-word Karaoke Highlight")
        self.word_highlight_check.setChecked(self.style.word_highlight)
        row2.addWidget(self.word_highlight_check)

        self.uppercase_check = QCheckBox("ALL CAPS Viral Style")
        self.uppercase_check.setChecked(self.style.uppercase)
        row2.addWidget(self.uppercase_check)

        row2.addStretch()
        style_layout.addLayout(row2)

        # Row 3: Vertical Position & Safe Zone presets
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Vertical Position:"))
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(30, 85)
        self.pos_slider.setValue(int(round(self.style.position_y * 100)))
        self.pos_slider.valueChanged.connect(self._on_pos_slider)
        pos_row.addWidget(self.pos_slider, 1)

        self.pos_lbl = QLabel(f"{int(round(self.style.position_y * 100))}%")
        self.pos_lbl.setFixedWidth(40)
        pos_row.addWidget(self.pos_lbl)

        # Safe zone quick buttons
        btn_bot = QPushButton("Safe Bottom (70%)")
        btn_bot.clicked.connect(lambda: self.pos_slider.setValue(70))
        btn_mid = QPushButton("Center (50%)")
        btn_mid.clicked.connect(lambda: self.pos_slider.setValue(50))
        pos_row.addWidget(btn_bot)
        pos_row.addWidget(btn_mid)

        style_layout.addLayout(pos_row)
        layout.addWidget(style_group)

        # Section 3: Transcript Review & Edit
        review_group = QGroupBox("Transcript Cues (Click text to edit)")
        review_layout = QVBoxLayout(review_group)
        review_layout.setSpacing(6)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Caption Text"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_table_item_changed)
        review_layout.addWidget(self.table)

        # Export row
        exp_row = QHBoxLayout()
        self.cue_count_lbl = QLabel("0 cues loaded.")
        self.cue_count_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        exp_row.addWidget(self.cue_count_lbl)
        exp_row.addStretch()

        self.exp_srt_btn = QPushButton(" Export .SRT")
        self.exp_srt_btn.setIcon(qta.icon("fa5s.file-alt", color="#dcdcdc"))
        self.exp_srt_btn.clicked.connect(self._export_srt)
        exp_row.addWidget(self.exp_srt_btn)

        self.exp_ass_btn = QPushButton(" Export .ASS (Karaoke)")
        self.exp_ass_btn.setIcon(qta.icon("fa5s.file-code", color="#dcdcdc"))
        self.exp_ass_btn.clicked.connect(self._export_ass)
        exp_row.addWidget(self.exp_ass_btn)
        review_layout.addLayout(exp_row)

        layout.addWidget(review_group, 1)

        # Action Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton(" Apply Captions")
        self.apply_btn.setIcon(qta.icon("fa5s.check", color="#ffffff"))
        self.apply_btn.setFixedWidth(130)
        self.apply_btn.setStyleSheet("font-weight: bold; background-color: #0078d4; color: white;")
        self.apply_btn.clicked.connect(self._apply_and_close)
        btn_box.addWidget(self.apply_btn)

        layout.addLayout(btn_box)

    # ================================================================
    #  STATE & TABLE POPULATION
    # ================================================================

    def _load_state(self) -> None:
        # Match highlight color preset
        h_color = self.style.highlight_color.upper()
        for idx in range(self.highlight_combo.count()):
            val = str(self.highlight_combo.itemData(idx)).upper()
            if val == h_color:
                self.highlight_combo.setCurrentIndex(idx)
                break

        self._populate_table()

    def _populate_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.cues))
        for row, cue in enumerate(self.cues):
            item_s = QTableWidgetItem(f"{cue.start:.2f}s")
            item_s.setFlags(item_s.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_e = QTableWidgetItem(f"{cue.end:.2f}s")
            item_e.setFlags(item_e.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_t = QTableWidgetItem(cue.text)
            self.table.setItem(row, 0, item_s)
            self.table.setItem(row, 1, item_e)
            self.table.setItem(row, 2, item_t)
        self.table.blockSignals(False)
        self.cue_count_lbl.setText(f"{len(self.cues)} cues loaded.")

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        col = item.column()
        if col == 2 and 0 <= row < len(self.cues):
            new_text = item.text().strip()
            self.cues[row].text = new_text
            # Update word texts proportionally
            words = self.cues[row].words
            split_words = new_text.split()
            if len(split_words) == len(words):
                for w, sw in zip(words, split_words):
                    w.word = sw

    def _on_pos_slider(self, val: int) -> None:
        self.pos_lbl.setText(f"{val}%")

    # ================================================================
    #  WHISPER TRANSCRIPTION
    # ================================================================

    def _start_transcription(self) -> None:
        if not self.video_path or not Path(self.video_path).is_file():
            QMessageBox.warning(self, "No Video", "Please load a video clip into ClipCraft before generating captions.")
            return

        model_key = "base"
        idx = self.model_combo.currentIndex()
        if idx == 1:
            model_key = "tiny"
        elif idx == 2:
            model_key = "small"

        lang_val = self.lang_combo.currentText()
        lang = None if lang_val == "Auto-Detect" else lang_val

        self.transcribe_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.status_lbl.setText(f"Starting Whisper ({model_key}) transcription…")

        self._worker = TranscriptionWorker(
            video_path=self.video_path,
            start_sec=self.clip_in,
            end_sec=self.clip_out,
            model_size=model_key,
            language=lang,
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_worker_progress(self, frac: float, msg: str) -> None:
        self.progress_bar.setValue(int(round(frac * 100)))
        self.status_lbl.setText(msg)

    def _on_worker_finished(self, cues: list[CaptionCue], lang: str) -> None:
        self.cues = cues
        self.enable_check.setChecked(True)
        self.transcribe_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(f"Transcription complete! Language: {lang.upper()} · {len(cues)} cues generated.")
        self.status_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
        self._populate_table()

    def _on_worker_error(self, err: str) -> None:
        self.transcribe_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(f"Error: {err}")
        self.status_lbl.setStyleSheet("color: #f44336; font-size: 11px;")
        QMessageBox.critical(self, "Transcription Error", f"Whisper speech recognition failed:\n\n{err}")

    # ================================================================
    #  EXPORTS & APPLIES
    # ================================================================

    def _export_srt(self) -> None:
        if not self.cues:
            QMessageBox.information(self, "No Captions", "No caption cues available to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export SubRip Subtitles", "captions.srt", "SubRip (*.srt)")
        if path:
            export_to_srt(self.cues, path, uppercase=self.uppercase_check.isChecked())
            QMessageBox.information(self, "Exported", f"Successfully saved SRT subtitles to:\n{path}")

    def _export_ass(self) -> None:
        if not self.cues:
            QMessageBox.information(self, "No Captions", "No caption cues available to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export ASS Karaoke Subtitles", "captions.ass", "Advanced SubStation (*.ass)")
        if path:
            style = self._get_current_style()
            export_to_ass(self.cues, path, style)
            QMessageBox.information(self, "Exported", f"Successfully saved ASS karaoke subtitles to:\n{path}")

    def _get_current_style(self) -> CaptionStyle:
        h_color = str(self.highlight_combo.currentData())
        return CaptionStyle(
            font_family=self.style.font_family,
            font_size=self.size_spin.value(),
            primary_color="#FFFFFF",
            highlight_color=h_color,
            stroke_color="#000000",
            stroke_width=self.stroke_spin.value(),
            position_y=self.pos_slider.value() / 100.0,
            uppercase=self.uppercase_check.isChecked(),
            word_highlight=self.word_highlight_check.isChecked(),
        )

    def get_captions_config(self) -> dict[str, Any]:
        style = self._get_current_style()
        return {
            "enabled": self.enable_check.isChecked() and len(self.cues) > 0,
            "cues": [c.to_dict() for c in self.cues],
            "style": style.to_dict(),
        }

    def _apply_and_close(self) -> None:
        cfg = self.get_captions_config()
        self.captions_applied.emit(cfg)
        self.accept()
