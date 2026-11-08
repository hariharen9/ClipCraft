"""Dedicated keyframe editor for one layer.

Opened from the inspector's small **Animate…** button. The layer keeps its normal
static behaviour until at least two keys exist; this window only edits
``layer["anim"]["keys"]`` (normalized centre positions on the edited timeline).

It is intentionally separate from the main editor: animation is optional, the
canvas stays uncluttered, and the timeline can be scrubbed without disturbing the
clip's IN/OUT or playback state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..anim import keys_for_layer, normalize_keys, sample
from ..preview import layer_preview_image, render_background, to_qimage_array
from ..segments import timeline_to_source

PREVIEW_SIZE = QSize(270, 480)


def _clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:05.2f}"


class AnimTimeline(QWidget):
    """Keyframe strip: click to scrub, click a diamond to select it."""

    seek_requested = Signal(float)
    key_selected = Signal(int)

    PAD = 12
    BAR_TOP = 30
    BAR_HEIGHT = 26

    def __init__(self, duration: float, parent: QWidget | None = None):
        super().__init__(parent)
        self.duration = max(0.1, float(duration))
        self.keys: list[dict[str, float]] = []
        self.playhead = 0.0
        self.selected = -1
        self._dragging = False
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def set_keys(self, keys: list[dict[str, float]]) -> None:
        self.keys = list(keys)
        self.update()

    def set_playhead(self, value: float) -> None:
        self.playhead = max(0.0, min(self.duration, float(value)))
        self.update()

    def _x_for(self, time_value: float) -> float:
        usable = max(1.0, self.width() - 2 * self.PAD)
        return self.PAD + max(0.0, min(self.duration, time_value)) / self.duration * usable

    def _time_for(self, x: float) -> float:
        usable = max(1.0, self.width() - 2 * self.PAD)
        return max(0.0, min(self.duration, (x - self.PAD) / usable * self.duration))

    def _key_at(self, x: float) -> int:
        for index, key in enumerate(self.keys):
            if abs(self._x_for(key["t"]) - x) <= 7:
                return index
        return -1

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#14171c"))
        painter.fillRect(
            QRectF(self.PAD, self.BAR_TOP, max(1.0, self.width() - 2 * self.PAD), self.BAR_HEIGHT),
            QColor("#232830"),
        )

        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor("#8d96a3"))
        painter.drawText(QRectF(self.PAD, 4, 120, 14), Qt.AlignmentFlag.AlignLeft, _clock(0.0))
        painter.drawText(
            QRectF(self.width() - self.PAD - 120, 4, 120, 14),
            Qt.AlignmentFlag.AlignRight, _clock(self.duration),
        )

        for index, key in enumerate(self.keys):
            x = self._x_for(key["t"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffd54f") if index == self.selected else QColor("#4daafc"))
            painter.drawPolygon(QPolygonF([
                QPointF(x, self.BAR_TOP + self.BAR_HEIGHT / 2 - 6),
                QPointF(x + 6, self.BAR_TOP + self.BAR_HEIGHT / 2),
                QPointF(x, self.BAR_TOP + self.BAR_HEIGHT / 2 + 6),
                QPointF(x - 6, self.BAR_TOP + self.BAR_HEIGHT / 2),
            ]))

        x = self._x_for(self.playhead)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(QPointF(x, self.BAR_TOP - 6), QPointF(x, self.BAR_TOP + self.BAR_HEIGHT + 6))
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([
            QPointF(x - 5, self.BAR_TOP + self.BAR_HEIGHT + 6),
            QPointF(x + 5, self.BAR_TOP + self.BAR_HEIGHT + 6),
            QPointF(x, self.BAR_TOP + self.BAR_HEIGHT + 13),
        ]))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        index = self._key_at(x)
        if index >= 0:
            self.selected = index
            self.playhead = self.keys[index]["t"]
            self.key_selected.emit(index)
            self.seek_requested.emit(self.playhead)
        else:
            self._dragging = True
            value = self._time_for(x)
            self.playhead = value
            self.seek_requested.emit(value)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            return
        value = self._time_for(event.position().x())
        self.playhead = value
        self.seek_requested.emit(value)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False


class AnimationDialog(QDialog):
    """Keyframe studio for a single layer (position only)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        layer_name: str = "",
        layer: dict[str, Any] | None = None,
        duration: float = 0.0,
        video_path: str = "",
        in_point: float = 0.0,
        out_point: float = 0.0,
        cuts: list[tuple[float, float]] | None = None,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
        fps: float = 30.0,
    ):
        super().__init__(parent)
        self.layer_name = layer_name
        self.layer = dict(layer or {})
        self.duration = max(0.1, float(duration or 0.1))
        self.video_path = str(video_path)
        self.in_point = float(in_point)
        self.out_point = float(out_point)
        self.cuts = list(cuts or [])
        self.config = config or {}
        self.config_path = Path(config_path) if config_path else Path(".")
        self.fps = max(1.0, float(fps or 30.0))

        self._capture: cv2.VideoCapture | None = None
        self._frame_cache: tuple[int, np.ndarray | None] = (-1, None)
        self._playing = False

        self.keys = keys_for_layer(self.layer, self.duration)
        if not self.keys:
            rect = self.layer.get("rect", [0.0, 0.0, 1.0, 1.0])
            self.keys = [{"t": 0.0,
                          "x": float(rect[0]) + float(rect[2]) / 2,
                          "y": float(rect[1]) + float(rect[3]) / 2}]

        self.setWindowTitle(f"Animate — {layer_name.replace('_', ' ')}")
        self.resize(760, 720)
        self._build_ui()
        self._open_capture()
        self.timeline.set_keys(self.keys)
        self.timeline.set_playhead(0.0)
        self._refresh_all()

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel(f"Animate layer · {self.layer_name.replace('_', ' ')}")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        hint = QLabel(
            "Move the playhead, set X/Y, then press <b>Set key</b>. Two or more keys "
            "animate the layer; with fewer it stays static. Times are relative to the export."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4b2;")
        layout.addWidget(hint)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_SIZE)
        self.preview.setStyleSheet("background: #0b0d10; border: 1px solid #2a303a;")
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.preview, 1)

        self.timeline = AnimTimeline(self.duration)
        self.timeline.seek_requested.connect(self._on_seek)
        self.timeline.key_selected.connect(self._on_key_selected)
        layout.addWidget(self.timeline)

        form = QFormLayout()
        self.x_spin = QDoubleSpinBox()
        self.y_spin = QDoubleSpinBox()
        for spin in (self.x_spin, self.y_spin):
            spin.setRange(0.0, 100.0)
            spin.setDecimals(1)
            spin.setSingleStep(1.0)
            spin.setSuffix(" %")
        form.addRow("Centre X", self.x_spin)
        form.addRow("Centre Y", self.y_spin)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.set_key_button = QPushButton("Set key")
        self.set_key_button.clicked.connect(self.set_key_at_playhead)
        row.addWidget(self.set_key_button)

        self.delete_key_button = QPushButton("Delete key")
        self.delete_key_button.clicked.connect(self.delete_selected_key)
        row.addWidget(self.delete_key_button)

        self.clear_button = QPushButton("Clear all")
        self.clear_button.clicked.connect(self.clear_keys)
        row.addWidget(self.clear_button)

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self._toggle_play)
        row.addWidget(self.play_button)
        row.addStretch(1)
        layout.addLayout(row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "Choose…", "Slide in from left", "Slide out to right", "Drift up",
        ])
        preset_row.addWidget(self.preset_combo, 1)
        self.apply_preset_button = QPushButton("Apply preset")
        self.apply_preset_button.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.apply_preset_button)
        layout.addLayout(preset_row)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply_button = QPushButton("Apply animation")
        apply_button.setDefault(True)
        apply_button.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: #ffffff; font-weight: bold; padding: 6px 14px; }"
        )
        apply_button.clicked.connect(self.accept)
        footer.addWidget(apply_button)
        layout.addLayout(footer)

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(66)
        self._play_timer.timeout.connect(self._tick)

    def _open_capture(self) -> None:
        if not self.video_path:
            return
        capture = cv2.VideoCapture(self.video_path)
        self._capture = capture if capture.isOpened() else None

    # -- preview -----------------------------------------------------------

    def _frame_at(self, elapsed: float) -> np.ndarray | None:
        if self._capture is None:
            return None
        source_time = timeline_to_source(
            elapsed, self.in_point, self.out_point, self.cuts
        )
        index = int(round(source_time * self.fps))
        cached_index, cached_frame = self._frame_cache
        if index == cached_index:
            return cached_frame
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, index))
        ok, frame = self._capture.read()
        frame = frame if ok else None
        self._frame_cache = (index, frame)
        return frame

    def _canvas_size(self) -> tuple[int, int]:
        canvas = self.config.get("canvas", {})
        cw = float(canvas.get("width", 1080) or 1080)
        ch = float(canvas.get("height", 1920) or 1920)
        scale = min(PREVIEW_SIZE.width() / cw, PREVIEW_SIZE.height() / ch)
        return max(2, int(round(cw * scale))), max(2, int(round(ch * scale)))

    def _compose(self, elapsed: float) -> np.ndarray | None:
        frame = self._frame_at(elapsed)
        if frame is None:
            return None
        width, height = self._canvas_size()
        canvas = cv2.cvtColor(render_background(frame, width, height, self.config), cv2.COLOR_BGR2RGB)
        canvas = canvas.astype(np.float32)

        layers = self.config.get("layers", {})
        ordered = sorted(
            [(name, layer) for name, layer in layers.items()
             if name != "background" and layer.get("visible", True)],
            key=lambda pair: pair[1].get("z", 0),
        )
        for name, layer in ordered:
            image, _ = layer_preview_image(
                name, layer, frame, width, height, self.config_path
            )
            if image is None:
                continue
            if name == self.layer_name:
                keys = self.keys
            else:
                keys = keys_for_layer(layer, self.duration)
            center = sample(keys, elapsed) if len(keys) >= 2 else None
            if center is None:
                rect = layer.get("rect", [0.0, 0.0, 1.0, 1.0])
                center = (float(rect[0]) + float(rect[2]) / 2, float(rect[1]) + float(rect[3]) / 2)
            rect = layer.get("rect", [0.0, 0.0, 1.0, 1.0])
            left = int(round((center[0] - float(rect[2]) / 2) * width))
            top = int(round((center[1] - float(rect[3]) / 2) * height))
            self._blend(canvas, image, left, top, float(layer.get("opacity", 1.0)))

        return cv2.cvtColor(np.clip(canvas, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _blend(canvas: np.ndarray, image: np.ndarray, left: int, top: int, opacity: float) -> None:
        height, width = canvas.shape[:2]
        layer_h, layer_w = image.shape[:2]
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(width, left + layer_w), min(height, top + layer_h)
        if x1 <= x0 or y1 <= y0:
            return
        src = image[y0 - top:y1 - top, x0 - left:x1 - left]
        if src.ndim == 3 and src.shape[2] == 4:
            alpha = (src[..., 3:4].astype(np.float32) / 255.0) * opacity
            rgb = src[..., :3].astype(np.float32)
        else:
            alpha = opacity
            rgb = cv2.cvtColor(src, cv2.COLOR_BGR2RGB).astype(np.float32)
        region = canvas[y0:y1, x0:x1]
        canvas[y0:y1, x0:x1] = region * (1.0 - alpha) + rgb * alpha

    def _refresh_preview(self) -> None:
        composed = self._compose(self.timeline.playhead)
        if composed is None:
            self.preview.setText("No video loaded")
            return
        image = to_qimage_array(composed)
        self.preview.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # -- state -------------------------------------------------------------

    def _refresh_all(self) -> None:
        elapsed = self.timeline.playhead
        center = sample(self.keys, elapsed) if self.keys else None
        if center is None:
            rect = self.layer.get("rect", [0.0, 0.0, 1.0, 1.0])
            center = (float(rect[0]) + float(rect[2]) / 2, float(rect[1]) + float(rect[3]) / 2)
        for spin, value in ((self.x_spin, center[0]), (self.y_spin, center[1])):
            spin.blockSignals(True)
            spin.setValue(value * 100.0)
            spin.blockSignals(False)
        self._refresh_preview()

    def _on_seek(self, seconds: float) -> None:
        self.timeline.set_playhead(seconds)
        self.timeline.selected = -1
        self._refresh_all()

    def _on_key_selected(self, index: int) -> None:
        if 0 <= index < len(self.keys):
            self.timeline.selected = index
            self.timeline.set_playhead(self.keys[index]["t"])
            self._refresh_all()

    def set_key_at_playhead(self) -> None:
        time_value = round(self.timeline.playhead, 3)
        key = {"t": time_value, "x": self.x_spin.value() / 100.0, "y": self.y_spin.value() / 100.0}
        updated = [existing for existing in self.keys if abs(existing["t"] - time_value) > 1e-3]
        updated.append(key)
        self.keys = normalize_keys(updated, self.duration)
        self.timeline.set_keys(self.keys)
        self.timeline.selected = next(
            (index for index, item in enumerate(self.keys) if abs(item["t"] - time_value) < 1e-3), -1
        )
        self._refresh_all()

    def delete_selected_key(self) -> None:
        index = self.timeline.selected
        if 0 <= index < len(self.keys):
            del self.keys[index]
            self.keys = normalize_keys(self.keys, self.duration)
            self.timeline.set_keys(self.keys)
            self.timeline.selected = -1
            self._refresh_all()

    def clear_keys(self) -> None:
        self.keys = []
        self.timeline.set_keys(self.keys)
        self.timeline.selected = -1
        self._refresh_all()

    def _apply_preset(self) -> None:
        preset = self.preset_combo.currentText()
        rect = self.layer.get("rect", [0.0, 0.0, 1.0, 1.0])
        cx = float(rect[0]) + float(rect[2]) / 2
        cy = float(rect[1]) + float(rect[3]) / 2
        span = min(0.6, self.duration / 3.0)
        if preset == "Slide in from left":
            self.keys = [
                {"t": 0.0, "x": 0.02, "y": cy},
                {"t": span, "x": cx, "y": cy},
            ]
        elif preset == "Slide out to right":
            self.keys = [
                {"t": max(0.0, self.duration - span), "x": cx, "y": cy},
                {"t": self.duration, "x": 0.98, "y": cy},
            ]
        elif preset == "Drift up":
            self.keys = [
                {"t": 0.0, "x": cx, "y": min(1.0, cy + 0.12)},
                {"t": self.duration, "x": cx, "y": max(0.0, cy - 0.12)},
            ]
        else:
            return
        self.keys = normalize_keys(self.keys, self.duration)
        self.timeline.set_keys(self.keys)
        self.timeline.selected = -1
        self._refresh_all()

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop_play()
            return
        self._playing = True
        self.play_button.setText("Pause")
        self._play_timer.start()

    def _stop_play(self) -> None:
        self._playing = False
        self._play_timer.stop()
        self.play_button.setText("Play")

    def _tick(self) -> None:
        value = self.timeline.playhead + 0.066
        if value >= self.duration:
            self.timeline.set_playhead(self.duration)
            self._stop_play()
        else:
            self.timeline.set_playhead(value)
        self._refresh_all()

    def result_keys(self) -> list[dict[str, float]]:
        return normalize_keys(self.keys, self.duration)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_play()
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        super().closeEvent(event)
