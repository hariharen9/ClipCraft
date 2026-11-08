from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..renderer import run_render, probe_video


class VideoProbeWorker(QThread):
    finished_signal = Signal(dict, str)   # (info, video_path)
    error_signal = Signal(str, str)      # (error_message, video_path)

    def __init__(self, video_path: Path):
        super().__init__()
        self.video_path = Path(video_path)

    def run(self):
        try:
            info = probe_video(self.video_path)
            self.finished_signal.emit(info, str(self.video_path))
        except Exception as exc:
            self.error_signal.emit(str(exc), str(self.video_path))


class SilenceScanWorker(QThread):
    """Runs FFmpeg silencedetect off the UI thread.

    Scanning is audio-only and quick, but it still decodes the whole range, so
    keeping it off the GUI thread avoids a frozen window on long recordings.
    """

    finished_signal = Signal(list)   # list[tuple[float, float]]
    error_signal = Signal(str)

    def __init__(self, video: str, start: float, end: float, parent=None):
        super().__init__(parent)
        self.video = str(video)
        # Never name these `self.start`: that would shadow QThread.start().
        self.start_time = float(start)
        self.end_time = float(end)

    def run(self):
        try:
            from ..silence import detect_silence

            self.finished_signal.emit(
                detect_silence(self.video, self.start_time, self.end_time)
            )
        except Exception as exc:
            self.error_signal.emit(str(exc))


class RenderWorker(QThread):
    progress_signal = Signal(float, str)
    finished_signal = Signal(bool, str)

    def __init__(self, video: str, output: str, start: float, end: float,
                 config: dict[str, Any], config_path: Path, encoder: str,
                 audio_config: dict[str, Any] | None = None,
                 cuts: list[tuple[float, float]] | None = None):
        super().__init__()
        self.video = video
        self.output = output
        self.start_time = start
        self.end_time = end
        self.config = copy.deepcopy(config)
        self.config_path = config_path
        self.encoder = encoder
        self.audio_config = copy.deepcopy(audio_config) if audio_config else None
        self.cuts = list(cuts or [])

    def run(self):
        try:
            result = run_render(
                self.video, self.output, self.start_time, self.end_time,
                self.config, self.config_path, self.encoder,
                progress=lambda value, message: self.progress_signal.emit(value, message),
                audio_config=self.audio_config,
                cuts=self.cuts,
            )
            self.finished_signal.emit(True, str(result))
        except Exception as exc:  # The GUI displays the FFmpeg diagnostic to the user.
            self.finished_signal.emit(False, str(exc))
