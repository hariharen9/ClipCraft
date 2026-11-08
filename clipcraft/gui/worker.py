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
