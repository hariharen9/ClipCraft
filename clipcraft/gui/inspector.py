from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from .constants import FADE_DEFAULT_SECONDS
from .layer_stack import LayerStackWidget


class LayerInspectorWidget(QWidget):
    """Right-hand sidebar panel managing layer stack, text/image properties, geometry, and crop."""

    layer_selected = Signal(str)
    visibility_toggled = Signal(str, bool)
    reordered = Signal(list)
    add_text_requested = Signal()
    delete_layer_requested = Signal(str)

    opacity_changed = Signal(int)
    opacity_pressed = Signal()
    opacity_released = Signal()

    fade_changed = Signal()
    fade_apply_all_clicked = Signal()

    text_content_edited = Signal(str)
    text_prop_changed = Signal()
    text_color_clicked = Signal()
    stroke_color_clicked = Signal()

    browse_asset_clicked = Signal()
    snap_aspect_clicked = Signal()

    geometry_value_changed = Signal()
    geometry_editing_finished = Signal()

    crop_value_changed = Signal()
    crop_editing_finished = Signal()
    visual_crop_clicked = Signal()
    reset_crop_clicked = Signal()

    undo_clicked = Signal()
    redo_clicked = Signal()
    save_layout_clicked = Signal()
    reset_layout_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)

        # ── Layer Editor & Stack ────────────────────────────────────
        layer_group = QGroupBox("Layer editor")
        layer_layout = QVBoxLayout(layer_group)

        self.layer_stack = LayerStackWidget()
        self.layer_stack.layer_selected.connect(self.layer_selected.emit)
        self.layer_stack.visibility_toggled.connect(self.visibility_toggled.emit)
        self.layer_stack.reordered.connect(self.reordered.emit)
        self.layer_stack.add_text_requested.connect(self.add_text_requested.emit)
        self.layer_stack.delete_layer_requested.connect(self.delete_layer_requested.emit)
        layer_layout.addWidget(self.layer_stack)

        vis_opacity_row = QHBoxLayout()
        self.visible_check = QCheckBox("Visible")
        vis_opacity_row.addWidget(self.visible_check)
        vis_opacity_row.addSpacing(10)
        vis_opacity_row.addWidget(QLabel("Opacity"))

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.sliderPressed.connect(self.opacity_pressed.emit)
        self.opacity_slider.sliderReleased.connect(self.opacity_released.emit)
        self.opacity_slider.valueChanged.connect(self.opacity_changed.emit)
        vis_opacity_row.addWidget(self.opacity_slider, 1)

        self.opacity_label = QLabel("100%")
        self.opacity_label.setMinimumWidth(38)
        self.opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vis_opacity_row.addWidget(self.opacity_label)
        layer_layout.addLayout(vis_opacity_row)

        # ── Fade In / Out (#18) ────────────────────────────────────
        fade_group = QGroupBox("Fade in / out")
        fade_layout = QVBoxLayout(fade_group)
        fade_layout.setContentsMargins(6, 4, 6, 6)
        fade_layout.setSpacing(5)

        fade_header = QHBoxLayout()
        self.fade_check = QCheckBox("Fade in / out")
        self.fade_check.setToolTip(
            "Ramp this layer's opacity up at the clip start and down at the end"
        )
        self.fade_check.toggled.connect(self._on_fade_toggled)
        fade_header.addWidget(self.fade_check)
        fade_header.addStretch(1)

        self.fade_all_button = QPushButton(" Apply to all")
        self.fade_all_button.setIcon(qta.icon("fa5s.layer-group", color="#dcdcdc"))
        self.fade_all_button.setToolTip("Copy these fade settings to every layer")
        self.fade_all_button.clicked.connect(self.fade_apply_all_clicked.emit)
        fade_header.addWidget(self.fade_all_button)
        fade_layout.addLayout(fade_header)

        fade_form = QFormLayout()
        self.fade_in_spin = QDoubleSpinBox()
        self.fade_out_spin = QDoubleSpinBox()
        for spin, tip in (
            (self.fade_in_spin, "Seconds to fade this layer in from transparent"),
            (self.fade_out_spin, "Seconds to fade this layer out to transparent"),
        ):
            spin.setRange(0.0, 30.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setValue(FADE_DEFAULT_SECONDS)
            spin.setSuffix(" s")
            spin.setToolTip(tip)
            spin.setEnabled(False)
            spin.valueChanged.connect(self._on_fade_duration_changed)
            fade_form.addRow("Fade in" if spin is self.fade_in_spin else "Fade out", spin)
        fade_layout.addLayout(fade_form)
        layer_layout.addWidget(fade_group)

        # ── Text Properties (#17) ───────────────────────────────────
        self.text_group = QGroupBox("Text properties")
        text_layout = QVBoxLayout(self.text_group)
        text_layout.setContentsMargins(6, 4, 6, 6)
        text_layout.setSpacing(5)

        self.text_content_edit = QLineEdit()
        self.text_content_edit.setPlaceholderText("Enter text…")
        self.text_content_edit.textEdited.connect(self.text_content_edited.emit)
        self.text_content_edit.editingFinished.connect(self.geometry_editing_finished.emit)
        text_layout.addWidget(self.text_content_edit)

        font_row = QHBoxLayout()
        self.font_combo = QComboBox()
        self.font_combo.addItems([
            "Impact", "Arial", "Segoe UI", "Calibri", "Verdana",
            "Tahoma", "Trebuchet MS", "Comic Sans MS", "Times New Roman", "Courier New"
        ])
        self.font_combo.currentIndexChanged.connect(self.text_prop_changed.emit)
        font_row.addWidget(self.font_combo, 1)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 300)
        self.font_size_spin.setValue(48)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.valueChanged.connect(self.text_prop_changed.emit)
        font_row.addWidget(self.font_size_spin)

        self.font_bold_check = QCheckBox("Bold")
        self.font_bold_check.setChecked(True)
        self.font_bold_check.stateChanged.connect(self.text_prop_changed.emit)
        font_row.addWidget(self.font_bold_check)
        text_layout.addLayout(font_row)

        style_row = QHBoxLayout()
        self.text_color_btn = QPushButton(" Color")
        self.text_color_btn.setIcon(qta.icon("mdi6.palette", color="#ffffff"))
        self.text_color_btn.setFixedHeight(24)
        self.text_color_btn.clicked.connect(self.text_color_clicked.emit)
        style_row.addWidget(self.text_color_btn)

        self.stroke_color_btn = QPushButton(" Stroke")
        self.stroke_color_btn.setIcon(qta.icon("mdi6.brush", color="#ffffff"))
        self.stroke_color_btn.setFixedHeight(24)
        self.stroke_color_btn.clicked.connect(self.stroke_color_clicked.emit)
        style_row.addWidget(self.stroke_color_btn)

        self.stroke_width_spin = QSpinBox()
        self.stroke_width_spin.setRange(0, 30)
        self.stroke_width_spin.setValue(3)
        self.stroke_width_spin.setSuffix(" px")
        self.stroke_width_spin.valueChanged.connect(self.text_prop_changed.emit)
        style_row.addWidget(self.stroke_width_spin)

        self.text_align_combo = QComboBox()
        self.text_align_combo.addItems(["Center", "Left", "Right"])
        self.text_align_combo.currentIndexChanged.connect(self.text_prop_changed.emit)
        style_row.addWidget(self.text_align_combo)
        text_layout.addLayout(style_row)
        layer_layout.addWidget(self.text_group)

        # ── Image Asset ─────────────────────────────────────────────
        self.asset_group = QGroupBox("Image asset")
        asset_layout = QHBoxLayout(self.asset_group)
        asset_layout.setContentsMargins(6, 4, 6, 4)
        self.asset_edit = QLineEdit()
        self.asset_edit.setReadOnly(True)
        self.asset_edit.setPlaceholderText("No asset")
        asset_layout.addWidget(self.asset_edit, 1)

        self.asset_button = QPushButton(" Browse…")
        self.asset_button.setIcon(qta.icon("mdi6.image", color="#dcdcdc"))
        self.asset_button.setMaximumWidth(84)
        self.asset_button.clicked.connect(self.browse_asset_clicked.emit)
        asset_layout.addWidget(self.asset_button)
        layer_layout.addWidget(self.asset_group)

        # ── Output Position / Size ──────────────────────────────────
        geometry_group = QGroupBox("Output position / size (% of canvas)")
        geometry_inner = QVBoxLayout(geometry_group)
        geometry_inner.setContentsMargins(6, 4, 6, 6)
        geometry_form = QFormLayout()
        self.geom_fields: dict[str, QDoubleSpinBox] = {}
        for key, title in (("x", "X"), ("y", "Y"), ("w", "Width"), ("h", "Height")):
            spin = QDoubleSpinBox()
            spin.setRange(0.1 if key in ("w", "h") else -50.0, 150.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" %")
            spin.valueChanged.connect(lambda *_: self.geometry_value_changed.emit())
            spin.editingFinished.connect(self.geometry_editing_finished.emit)
            self.geom_fields[key] = spin
            geometry_form.addRow(title, spin)
        geometry_inner.addLayout(geometry_form)

        self.snap_aspect_button = QPushButton("Snap to image aspect")
        self.snap_aspect_button.setToolTip("Fit the rectangle to the image's own aspect ratio, kept centered")
        self.snap_aspect_button.clicked.connect(self.snap_aspect_clicked.emit)
        geometry_inner.addWidget(self.snap_aspect_button)
        layer_layout.addWidget(geometry_group)

        # ── Source Crop ─────────────────────────────────────────────
        crop_group = QGroupBox("Source crop (% of original footage)")
        crop_form = QFormLayout(crop_group)
        self.crop_fields: dict[str, QDoubleSpinBox] = {}
        for key, title in (("x", "Crop X"), ("y", "Crop Y"), ("w", "Crop width"), ("h", "Crop height")):
            spin = QDoubleSpinBox()
            spin.setRange(0.1 if key in ("w", "h") else 0.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" %")
            spin.valueChanged.connect(lambda *_: self.crop_value_changed.emit())
            spin.editingFinished.connect(self.crop_editing_finished.emit)
            self.crop_fields[key] = spin
            crop_form.addRow(title, spin)

        crop_btn_row = QHBoxLayout()
        self.visual_crop_button = QPushButton(" Crop visually…")
        self.visual_crop_button.setIcon(qta.icon("mdi6.crop", color="#4daafc"))
        self.visual_crop_button.setToolTip("Open full 16:9 source frame and crop by dragging an interactive box")
        self.visual_crop_button.clicked.connect(self.visual_crop_clicked.emit)
        crop_btn_row.addWidget(self.visual_crop_button)

        self.reset_crop_button = QPushButton(" Reset crop")
        self.reset_crop_button.setIcon(qta.icon("fa5s.undo", color="#dcdcdc"))
        self.reset_crop_button.setToolTip("Reset source crop to config defaults")
        self.reset_crop_button.clicked.connect(self.reset_crop_clicked.emit)
        crop_btn_row.addWidget(self.reset_crop_button)

        layer_layout.addWidget(crop_group)
        layer_layout.addLayout(crop_btn_row)
        layout.addWidget(layer_group)

        # ── Template Actions ────────────────────────────────────────
        actions_group = QGroupBox("Template")
        actions_layout = QVBoxLayout(actions_group)
        history_row = QHBoxLayout()

        self.undo_button = QPushButton(" Undo")
        self.undo_button.setIcon(qta.icon("fa5s.undo-alt", color="#dcdcdc"))
        self.undo_button.setToolTip("Undo the last canvas or layout change (Ctrl+Z)")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_clicked.emit)

        self.redo_button = QPushButton(" Redo")
        self.redo_button.setIcon(qta.icon("fa5s.redo-alt", color="#dcdcdc"))
        self.redo_button.setToolTip("Redo an undone change (Ctrl+Shift+Z)")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self.redo_clicked.emit)

        history_row.addWidget(self.undo_button)
        history_row.addWidget(self.redo_button)
        actions_layout.addLayout(history_row)

        self.save_button = QPushButton(" Save layout to template")
        self.save_button.setIcon(qta.icon("fa5s.save", color="#dcdcdc"))
        self.save_button.clicked.connect(self.save_layout_clicked.emit)
        actions_layout.addWidget(self.save_button)

        self.reset_button = QPushButton(" Reset to saved layout")
        self.reset_button.setIcon(qta.icon("fa5s.sync-alt", color="#dcdcdc"))
        self.reset_button.clicked.connect(self.reset_layout_clicked.emit)
        actions_layout.addWidget(self.reset_button)

        layout.addWidget(actions_group)
        layout.addStretch(1)

    def active_layer_name(self) -> str:
        return self.layer_stack.current_layer_name()

    # -- fade controls -----------------------------------------------------

    def _on_fade_toggled(self, enabled: bool) -> None:
        self.fade_in_spin.setEnabled(enabled)
        self.fade_out_spin.setEnabled(enabled)
        self.fade_changed.emit()

    def _on_fade_duration_changed(self, _value: float) -> None:
        self.fade_changed.emit()

    def fade_settings(self) -> tuple[bool, float, float]:
        """Current (enabled, fade_in seconds, fade_out seconds) from the controls."""
        return (
            self.fade_check.isChecked(),
            float(self.fade_in_spin.value()),
            float(self.fade_out_spin.value()),
        )

    def set_fade_controls(self, enabled: bool, fade_in: float, fade_out: float) -> None:
        """Load a layer's fade settings without re-emitting change signals."""
        for widget in (self.fade_check, self.fade_in_spin, self.fade_out_spin):
            widget.blockSignals(True)
        self.fade_check.setChecked(bool(enabled))
        self.fade_in_spin.setValue(max(0.0, float(fade_in)))
        self.fade_out_spin.setValue(max(0.0, float(fade_out)))
        for widget in (self.fade_check, self.fade_in_spin, self.fade_out_spin):
            widget.blockSignals(False)
        self.fade_in_spin.setEnabled(bool(enabled))
        self.fade_out_spin.setEnabled(bool(enabled))

    def set_undo_redo_enabled(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)
