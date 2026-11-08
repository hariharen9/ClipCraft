"""Split & Cut studio: remove unwanted chunks from the middle of a recording.

The main window only knows an IN and an OUT point, which can describe a single
contiguous range. This dialog adds the missing middle: scrub the source, split
it into segments at the playhead, delete any segment you do not want, then pick
the final IN/OUT. Deleted segments are written back as *cut regions* (absolute
source timestamps), which the renderer removes and the preview skips over.

Everything here talks in source time; the timeline widget only paints it.
"""

from __future__ import annotations

from typing import Any

import cv2
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..segments import (
    MIN_CUT,
    next_kept_time,
    normalize_cuts,
    step_time,
    timeline_duration,
)

PREVIEW_MIN_SIZE = QSize(560, 315)


def format_clock(seconds: float) -> str:
    """Format seconds as ``M:SS.mmm`` for timeline labels."""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


class SplitTimeline(QWidget):
    """Painted timeline: kept/removed segments, split marks, IN/OUT and playhead."""

    seek_requested = Signal(float)
    edit_changed = Signal()

    PAD = 14
    BAR_TOP = 42
    BAR_HEIGHT = 34
    HANDLE_GRAB = 8

    def __init__(self, duration: float, parent: QWidget | None = None):
        super().__init__(parent)
        self.duration = max(0.05, float(duration))
        self.playhead = 0.0
        self.in_point = 0.0
        self.out_point = self.duration
        self.boundaries: list[float] = []
        self.removed: list[tuple[float, float]] = []
        self.selected = -1
        self._drag: str | None = None

        self.setMinimumHeight(98)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # -- model -------------------------------------------------------------

    def segments(self) -> list[tuple[float, float]]:
        """Segments between split marks, clipped to the current IN/OUT range."""
        cuts = sorted({b for b in self.boundaries if self.in_point < b < self.out_point})
        points = [self.in_point, *cuts, self.out_point]
        return [(points[i], points[i + 1]) for i in range(len(points) - 1)]

    def segment_removed(self, index: int) -> bool:
        segments = self.segments()
        if not (0 <= index < len(segments)):
            return False
        start, end = segments[index]
        return any(start >= a - MIN_CUT and end <= b + MIN_CUT for a, b in self.removed)

    def toggle_removed(self, index: int) -> bool:
        """Mark the segment deleted, or restore it. Returns True when it changed."""
        segments = self.segments()
        if not (0 <= index < len(segments)):
            return False
        start, end = segments[index]
        if self.segment_removed(index):
            self.removed = [
                (a, b) for a, b in self.removed
                if not (a >= start - MIN_CUT and b <= end + MIN_CUT)
            ]
        else:
            self.removed.append((start, end))
            self.removed = normalize_cuts(self.removed, self.duration)
        self.edit_changed.emit()
        self.update()
        return True

    def add_split(self, time_value: float) -> bool:
        if not (self.in_point + MIN_CUT < time_value < self.out_point - MIN_CUT):
            return False
        if any(abs(time_value - b) < 0.05 for b in self.boundaries):
            return False
        self.boundaries.append(time_value)
        self.boundaries.sort()
        self.edit_changed.emit()
        self.update()
        return True

    def cuts(self) -> list[tuple[float, float]]:
        return normalize_cuts(self.removed, self.duration)

    def segment_at(self, time_value: float) -> int:
        for index, (start, end) in enumerate(self.segments()):
            if start - MIN_CUT <= time_value <= end + MIN_CUT:
                return index
        return -1

    # -- coordinates -------------------------------------------------------

    def _x_for(self, time_value: float) -> float:
        span = max(self.duration, 1e-6)
        return self.PAD + (max(0.0, min(self.duration, time_value)) / span) * max(
            1.0, self.width() - 2 * self.PAD
        )

    def _time_for(self, x: float) -> float:
        usable = max(1.0, self.width() - 2 * self.PAD)
        return max(0.0, min(self.duration, (x - self.PAD) / usable * self.duration))

    # -- painting ----------------------------------------------------------

    def _tick_step(self) -> float:
        target = self.duration / 9.0
        for step in (0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
            if target <= step:
                return float(step)
        return 900.0

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#14171c"))

        bar_rect = QRectF(
            self.PAD, self.BAR_TOP, max(1.0, self.width() - 2 * self.PAD), self.BAR_HEIGHT
        )
        painter.fillRect(bar_rect, QColor("#232830"))

        # Ruler
        painter.setFont(QFont("Segoe UI", 7))
        step = self._tick_step()
        tick = 0.0
        while tick <= self.duration + 1e-6:
            x = self._x_for(tick)
            painter.setPen(QPen(QColor("#3c434e"), 1))
            painter.drawLine(QPointF(x, self.BAR_TOP - 6), QPointF(x, self.BAR_TOP))
            painter.setPen(QColor("#8d96a3"))
            painter.drawText(QPointF(x + 2, self.BAR_TOP - 9), format_clock(tick))
            tick += step

        # Segments
        removed_ranges = self.cuts()
        for index, (start, end) in enumerate(self.segments()):
            left, right = self._x_for(start), self._x_for(end)
            rect = QRectF(left, self.BAR_TOP, max(1.0, right - left), self.BAR_HEIGHT)
            removed = any(start >= a - MIN_CUT and end <= b + MIN_CUT for a, b in removed_ranges)
            # fillRect() takes an explicit colour, but drawRect() fills with the
            # painter's brush: keep that empty or outlines flood their rectangle.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if removed:
                painter.fillRect(rect, QColor("#5a2130"))
                painter.fillRect(rect, QColor(192, 69, 95, 40))
                painter.setPen(QPen(QColor("#f08fa0"), 1, Qt.PenStyle.DashLine))
                painter.drawRect(rect)
                painter.setPen(QColor("#ffd7de"))
                if rect.width() > 46:
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "CUT")
            else:
                painter.fillRect(rect, QColor("#2f4a66"))
                painter.setPen(QPen(QColor("#4b7fa8"), 1))
                painter.drawRect(rect)

            if index == self.selected:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#ffd54f"), 2))
                painter.drawRect(rect.adjusted(-1, -1, 1, 1))

            painter.setPen(QColor("#d6dde7"))
            painter.setFont(QFont("Segoe UI", 8))
            if rect.width() > 60:
                painter.drawText(
                    rect, Qt.AlignmentFlag.AlignCenter,
                    f"{start:.2f}–{end:.2f}s",
                )

        # Split marks
        painter.setPen(QPen(QColor("#c9d3df"), 1, Qt.PenStyle.DashLine))
        for boundary in self.boundaries:
            if self.in_point < boundary < self.out_point:
                x = self._x_for(boundary)
                painter.drawLine(QPointF(x, self.BAR_TOP - 4), QPointF(x, self.BAR_TOP + self.BAR_HEIGHT + 4))

        # IN / OUT handles
        for value, color, label in (
            (self.in_point, QColor("#4CAF50"), "IN"),
            (self.out_point, QColor("#f44336"), "OUT"),
        ):
            x = self._x_for(value)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            direction = -1 if label == "IN" else 1
            triangle = QPolygonF([
                QPointF(x, self.BAR_TOP - 2),
                QPointF(x + direction * 9, self.BAR_TOP - 2),
                QPointF(x, self.BAR_TOP - 12),
            ])
            painter.drawPolygon(triangle)
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            painter.setPen(color)
            painter.drawText(QPointF(x + (4 if label == "IN" else -26), self.BAR_TOP + self.BAR_HEIGHT + 16), label)

        # Playhead
        x = self._x_for(self.playhead)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(QPointF(x, self.BAR_TOP - 14), QPointF(x, self.BAR_TOP + self.BAR_HEIGHT + 6))
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([
            QPointF(x - 5, self.BAR_TOP + self.BAR_HEIGHT + 6),
            QPointF(x + 5, self.BAR_TOP + self.BAR_HEIGHT + 6),
            QPointF(x, self.BAR_TOP + self.BAR_HEIGHT + 13),
        ]))

    # -- interaction -------------------------------------------------------

    def _handle_at(self, x: float) -> str | None:
        if abs(x - self._x_for(self.in_point)) <= self.HANDLE_GRAB:
            return "in"
        if abs(x - self._x_for(self.out_point)) <= self.HANDLE_GRAB:
            return "out"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        handle = self._handle_at(x)
        self._drag = handle or "playhead"
        if handle is None:
            self.playhead = self._time_for(x)
            self.selected = self.segment_at(self.playhead)
            self.seek_requested.emit(self.playhead)
        else:
            self.selected = -1
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        if self._drag is None:
            handle = self._handle_at(x)
            self.setCursor(
                Qt.CursorShape.SizeHorCursor if handle else Qt.CursorShape.PointingHandCursor
            )
            return
        value = self._time_for(x)
        if self._drag == "in":
            self.in_point = max(0.0, min(value, self.out_point - MIN_CUT))
            self.selected = -1
            self.edit_changed.emit()
        elif self._drag == "out":
            self.out_point = min(self.duration, max(value, self.in_point + MIN_CUT))
            self.selected = -1
            self.edit_changed.emit()
        else:
            self.playhead = value
            self.seek_requested.emit(value)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None and self._drag != "playhead":
            # Dragging an IN/OUT handle can orphan removed ranges outside the range.
            self.removed = normalize_cuts(self.removed, self.duration)
        self._drag = None
        self.update()


class SplitEditorDialog(QDialog):
    """Modal studio for splitting out unwanted sections and re-picking IN/OUT."""

    def __init__(
        self,
        parent: QWidget | None = None,
        video_path: str = "",
        video_info: dict[str, Any] | None = None,
        cuts: list[tuple[float, float]] | None = None,
        in_point: float = 0.0,
        out_point: float | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Split & Cut Studio")
        self.resize(920, 700)
        self.setSizeGripEnabled(True)

        self.video_path = str(video_path)
        self.info = dict(video_info or {})
        self.duration = float(self.info.get("duration") or 0.0)
        self.fps = float(self.info.get("fps") or 30.0) or 30.0

        self.capture: cv2.VideoCapture | None = None
        self._frame_index = -1
        self._playing = False

        if not self.duration:
            self._probe()

        self._build_ui()

        end = self.duration if out_point is None else min(self.duration, float(out_point))
        self.timeline.in_point = max(0.0, min(float(in_point), max(0.0, end - MIN_CUT)))
        self.timeline.out_point = max(self.timeline.in_point + MIN_CUT, end)
        self.timeline.removed = normalize_cuts(cuts or [], self.duration)
        # Existing cuts need split marks at their edges, otherwise the timeline
        # would paint a removed range as one intact segment.
        for cut_start, cut_end in self.timeline.removed:
            for boundary in (cut_start, cut_end):
                if self.timeline.in_point < boundary < self.timeline.out_point:
                    if not any(abs(boundary - mark) < 0.05 for mark in self.timeline.boundaries):
                        self.timeline.boundaries.append(boundary)
        self.timeline.boundaries.sort()
        self.timeline.playhead = self.timeline.in_point

        self._open_capture()
        self.timeline.seek_requested.connect(self._on_seek)
        self.timeline.edit_changed.connect(self._on_edit)
        self._show_frame(self.timeline.playhead, force=True)
        self._sync_summary()

    # -- setup -------------------------------------------------------------

    def _probe(self) -> None:
        from ..renderer import probe_video

        if not self.video_path:
            return
        try:
            info = probe_video(self.video_path)
        except Exception:
            return
        self.info = info
        self.duration = float(info.get("duration") or 0.0)
        self.fps = float(info.get("fps") or 30.0) or 30.0

    def _open_capture(self) -> None:
        if not self.video_path:
            return
        capture = cv2.VideoCapture(self.video_path)
        self.capture = capture if capture.isOpened() else None

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("Split & cut")
        title_font = QFont("Segoe UI", 13, QFont.Weight.Bold)
        title.setFont(title_font)
        layout.addWidget(title)

        hint = QLabel(
            "Scrub to a point, press <b>Split</b> (S) to break the clip there, click a segment and "
            "press <b>Delete segment</b> (Del) to remove it. Then set IN and OUT around what is left."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4b2;")
        layout.addWidget(hint)

        self.preview = QLabel("No preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_MIN_SIZE)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background: #0b0d10; border: 1px solid #2a303a; color: #6b7482;")
        layout.addWidget(self.preview, 1)

        self.timeline = SplitTimeline(self.duration)
        layout.addWidget(self.timeline)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #cfd8e3;")
        layout.addWidget(self.summary)

        row = QHBoxLayout()
        self.play_btn = QPushButton("Play (Space)")
        self.play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self.play_btn)

        self.step_back_btn = QPushButton("◀ Frame")
        self.step_back_btn.clicked.connect(lambda: self._nudge(-1))
        row.addWidget(self.step_back_btn)

        self.step_fwd_btn = QPushButton("Frame ▶")
        self.step_fwd_btn.clicked.connect(lambda: self._nudge(1))
        row.addWidget(self.step_fwd_btn)

        self.split_btn = QPushButton("Split at playhead (S)")
        self.split_btn.clicked.connect(self.split_at_playhead)
        row.addWidget(self.split_btn)

        self.delete_btn = QPushButton("Delete segment (Del)")
        self.delete_btn.clicked.connect(self.delete_selected_segment)
        row.addWidget(self.delete_btn)

        self.restore_btn = QPushButton("Restore all")
        self.restore_btn.clicked.connect(self.restore_all)
        row.addWidget(self.restore_btn)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.set_in_btn = QPushButton("Set IN here (I)")
        self.set_in_btn.clicked.connect(self.set_in_here)
        row2.addWidget(self.set_in_btn)

        self.set_out_btn = QPushButton("Set OUT here (O)")
        self.set_out_btn.clicked.connect(self.set_out_here)
        row2.addWidget(self.set_out_btn)
        row2.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row2.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton("Apply cuts")
        self.apply_btn.setDefault(True)
        self.apply_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: #ffffff; font-weight: bold; padding: 6px 14px; }"
        )
        self.apply_btn.clicked.connect(self._apply)
        row2.addWidget(self.apply_btn)
        layout.addLayout(row2)

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(max(15, int(1000.0 / max(self.fps, 1.0))))
        self._play_timer.timeout.connect(self._tick)

        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(55)
        self._seek_timer.timeout.connect(lambda: self._show_frame(self.timeline.playhead))

    # -- preview -----------------------------------------------------------

    def _frame_pos(self, seconds: float) -> int:
        return max(0, int(round(seconds * self.fps)))

    def _read_frame(self, seconds: float) -> Any:
        if self.capture is None:
            return None
        index = self._frame_pos(seconds)
        try:
            if index != self._frame_index + 1:
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self.capture.read()
            if not ok:
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, index - 1))
                ok, frame = self.capture.read()
            if not ok:
                return None
            self._frame_index = index
            return frame
        except cv2.error:
            return None

    def _show_frame(self, seconds: float, force: bool = False) -> None:
        frame = self._read_frame(seconds)
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data, width, height, channels * width, QImage.Format.Format_RGB888
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    def _on_seek(self, seconds: float) -> None:
        self._sync_summary()
        if not self._playing:
            self._seek_timer.start()

    def _on_edit(self) -> None:
        self._sync_summary()

    def _sync_summary(self) -> None:
        tl = self.timeline
        kept = timeline_duration(tl.in_point, tl.out_point, tl.cuts())
        removed = (tl.out_point - tl.in_point) - kept
        cuts = len(tl.cuts())
        self.summary.setText(
            f"IN {format_clock(tl.in_point)}   ·   OUT {format_clock(tl.out_point)}   ·   "
            f"output <b>{format_clock(kept)}</b>   ·   {cuts} cut{'s' if cuts != 1 else ''} "
            f"({removed:.2f}s removed)"
        )
        self.apply_btn.setEnabled(kept > MIN_CUT)
        self.delete_btn.setEnabled(tl.selected >= 0)

    # -- actions -----------------------------------------------------------

    def split_at_playhead(self) -> None:
        if not self.timeline.add_split(self.timeline.playhead):
            self._status("Move the playhead inside IN/OUT, away from existing split marks")
            return
        self._sync_summary()

    def delete_selected_segment(self) -> None:
        index = self.timeline.selected
        if index < 0:
            self._status("Click a segment first")
            return
        segments = self.timeline.segments()
        if len(segments) <= 1:
            self._status("Split the clip first, then delete one of the pieces")
            return
        self.timeline.toggle_removed(index)
        self._sync_summary()

    def restore_all(self) -> None:
        self.timeline.removed.clear()
        self.timeline.boundaries.clear()
        self.timeline.selected = -1
        self.timeline.update()
        self._sync_summary()

    def set_in_here(self) -> None:
        tl = self.timeline
        tl.in_point = max(0.0, min(tl.playhead, tl.out_point - MIN_CUT))
        tl.update()
        self._sync_summary()

    def set_out_here(self) -> None:
        tl = self.timeline
        tl.out_point = min(self.duration, max(tl.playhead, tl.in_point + MIN_CUT))
        tl.update()
        self._sync_summary()

    def _nudge(self, direction: int) -> None:
        if self._playing:
            self._stop()
        delta = direction / max(self.fps, 1.0)
        value = step_time(
            self.timeline.playhead, delta,
            self.timeline.in_point, self.timeline.out_point, self.timeline.cuts(),
        )
        self.timeline.playhead = value
        self.timeline.selected = self.timeline.segment_at(value)
        self.timeline.update()
        self._show_frame(value)
        self._sync_summary()

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop()
            return
        if self.timeline.playhead >= self.timeline.out_point - 1e-6:
            self.timeline.playhead = self.timeline.in_point
        self._playing = True
        self.play_btn.setText("Pause (Space)")
        self._play_timer.start()

    def _stop(self) -> None:
        self._playing = False
        self._play_timer.stop()
        self.play_btn.setText("Play (Space)")

    def _tick(self) -> None:
        tl = self.timeline
        target = tl.playhead + 1.0 / max(self.fps, 1.0)
        if target >= tl.out_point - 1e-6:
            tl.playhead = tl.out_point
            self._stop()
            return
        # Never rest inside a removed region: hop straight to where footage resumes.
        value = next_kept_time(target, tl.cuts())
        tl.playhead = value
        tl.selected = tl.segment_at(value)
        tl.update()
        self._show_frame(value)
        self._sync_summary()

    def _status(self, message: str) -> None:
        self.summary.setText(message)

    def _apply(self) -> None:
        tl = self.timeline
        kept = timeline_duration(tl.in_point, tl.out_point, tl.cuts())
        if kept <= MIN_CUT:
            QMessageBox.warning(self, "Nothing left to render", "Keep at least one segment of footage.")
            return
        self.accept()

    def result_data(self) -> dict[str, Any]:
        tl = self.timeline
        return {
            "in": float(tl.in_point),
            "out": float(tl.out_point),
            "cuts": tl.cuts(),
            "duration": timeline_duration(tl.in_point, tl.out_point, tl.cuts()),
        }

    # -- events ------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Space:
            self._toggle_play()
            return
        if key == Qt.Key.Key_Left:
            self._nudge(-1)
            return
        if key == Qt.Key.Key_Right:
            self._nudge(1)
            return
        if key == Qt.Key.Key_S:
            self.split_at_playhead()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_segment()
            return
        if key == Qt.Key.Key_I:
            self.set_in_here()
            return
        if key == Qt.Key.Key_O:
            self.set_out_here()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop()
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        super().closeEvent(event)
