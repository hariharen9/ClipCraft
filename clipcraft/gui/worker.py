from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..renderer import run_render

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
