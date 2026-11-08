from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta


class TransportWidget(QGroupBox):
    """Clip selection & transport control panel (scrubber, play/pause, in/out, speed)."""

    play_toggled = Signal()
    step_back_requested = Signal()
    step_forward_requested = Signal()
    set_in_requested = Signal()
    set_out_requested = Signal()
    position_changed = Signal(int)
    scrub_started = Signal()
    scrub_finished = Signal()
    speed_changed = Signal(int)
    # Carries the new timestamp: both spin boxes connect valueChanged(float) here.
    in_out_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Clip selection", parent)
        layout = QVBoxLayout(self)

        self.frame_label = QLabel("00:00.000 / 00:00.000")
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.frame_label)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 10000)
        self.position_slider.valueChanged.connect(self.position_changed.emit)
        self.position_slider.sliderPressed.connect(self.scrub_started.emit)
        self.position_slider.sliderReleased.connect(self.scrub_finished.emit)
        layout.addWidget(self.position_slider)

        play_row = QHBoxLayout()
        self.play_button = QPushButton(" Play")
        self.play_button.setIcon(qta.icon("fa5s.play", color="#ffffff"))
        self.play_button.clicked.connect(self.play_toggled.emit)
        play_row.addWidget(self.play_button)

        self.step_back_button = QPushButton(" Frame")
        self.step_back_button.setIcon(qta.icon("fa5s.step-backward", color="#dcdcdc"))
        self.step_back_button.setToolTip("Back 1 frame (Left arrow; Shift = 1 second)")
        self.step_back_button.clicked.connect(self.step_back_requested.emit)
        play_row.addWidget(self.step_back_button)

        self.step_fwd_button = QPushButton(" Frame")
        self.step_fwd_button.setIcon(qta.icon("fa5s.step-forward", color="#dcdcdc"))
        self.step_fwd_button.setToolTip("Forward 1 frame (Right arrow; Shift = 1 second)")
        self.step_fwd_button.clicked.connect(self.step_forward_requested.emit)
        play_row.addWidget(self.step_fwd_button)
        layout.addLayout(play_row)

        io_row = QHBoxLayout()
        self.set_in_button = QPushButton(" Set IN")
        self.set_in_button.setIcon(qta.icon("fa5s.sign-in-alt", color="#4CAF50"))
        self.set_in_button.clicked.connect(self.set_in_requested.emit)
        io_row.addWidget(self.set_in_button)

        self.set_out_button = QPushButton(" Set OUT")
        self.set_out_button.setIcon(qta.icon("fa5s.sign-out-alt", color="#f44336"))
        self.set_out_button.clicked.connect(self.set_out_requested.emit)
        io_row.addWidget(self.set_out_button)
        layout.addLayout(io_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed"))
        self.speed_combo = QComboBox()
        for speed_label, speed_value in (("0.25×", 0.25), ("0.5×", 0.5), ("1×", 1.0), ("2×", 2.0), ("4×", 4.0)):
            self.speed_combo.addItem(speed_label, speed_value)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(self.speed_changed.emit)
        speed_row.addWidget(self.speed_combo)
        speed_row.addStretch(1)
        layout.addLayout(speed_row)

        trim_form = QFormLayout()
        self.in_spin = QDoubleSpinBox()
        self.out_spin = QDoubleSpinBox()
        for spin in (self.in_spin, self.out_spin):
            spin.setRange(0, 24 * 60 * 60)
            spin.setDecimals(3)
            spin.setSingleStep(0.25)
            spin.setSuffix(" s")
        self.in_spin.valueChanged.connect(self.in_out_changed.emit)
        self.out_spin.valueChanged.connect(self.in_out_changed.emit)
        trim_form.addRow("IN point", self.in_spin)
        trim_form.addRow("OUT point", self.out_spin)
        layout.addLayout(trim_form)

    def set_playing(self, playing: bool, direction: int = 1) -> None:
        """Update play/pause button icon and text depending on state."""
        if playing:
            if direction > 0:
                self.play_button.setText(" Pause")
                self.play_button.setIcon(qta.icon("fa5s.pause", color="#ffffff"))
            else:
                self.play_button.setText(" Rewind")
                self.play_button.setIcon(qta.icon("fa5s.backward", color="#ffffff"))
        else:
            self.play_button.setText(" Play")
            self.play_button.setIcon(qta.icon("fa5s.play", color="#ffffff"))

