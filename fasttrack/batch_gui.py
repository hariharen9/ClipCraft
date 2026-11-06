"""Backward-compatibility shim for fasttrack.batch_gui.

All batch GUI components now live in fasttrack.gui.batch_window.
"""
from __future__ import annotations

from fasttrack.gui.batch_window import (
    VIDEO_EXTENSIONS,
    BatchJob,
    TrimTimeline,
    BatchRenderWorker,
    BatchWindow,
    launch_batch_gui,
)

__all__ = [
    "VIDEO_EXTENSIONS",
    "BatchJob",
    "TrimTimeline",
    "BatchRenderWorker",
    "BatchWindow",
    "launch_batch_gui",
]
