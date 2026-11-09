"""Project sidecars (``.clipcraft``).

A template describes *how* a short looks; a project describes *this* edit: which
recording, the trim, the cut regions, the audio mix and the caption cues. Neither
belongs in the other, so the project lives next to the recording as a sidecar:

    D:/Captures/Valorant/clutch.mp4
    D:/Captures/Valorant/clutch.clipcraft      <- this module

Writes are atomic (``.tmp`` then ``replace``), matching ``config.save_state``, so
an interrupted autosave can never truncate an existing project.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

from .segments import normalize_cuts

PROJECT_VERSION = 1
PROJECT_SUFFIX = ".clipcraft"
AUTOSAVE_DELAY_MS = 1200
MAX_RECENT_PROJECTS = 10


def project_path_for(video_path: str | Path) -> Path:
    """Default sidecar location: ``<video stem>.clipcraft`` beside the recording."""
    return Path(video_path).expanduser().resolve().with_suffix(PROJECT_SUFFIX)


def build_project(
    video_path: str | Path,
    template_id: str,
    in_time: float,
    out_time: float,
    cuts: list[tuple[float, float]] | None = None,
    audio: dict[str, Any] | None = None,
    captions: dict[str, Any] | None = None,
    playhead: float = 0.0,
    template_path: str | Path | None = None,
) -> dict[str, Any]:
    """Assemble the JSON payload for the current edit."""
    return {
        "version": PROJECT_VERSION,
        "video": str(Path(video_path).expanduser().resolve()),
        "template": str(template_id or ""),
        "template_path": str(template_path) if template_path else None,
        "in": float(in_time),
        "out": float(out_time),
        "cuts": [[round(float(a), 6), round(float(b), 6)] for a, b in normalize_cuts(cuts or [])],
        "audio": dict(audio or {}),
        "captions": dict(captions) if captions else None,
        "playhead": float(playhead),
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def normalize_project(data: Any) -> dict[str, Any]:
    """Validate/normalise a project payload, raising ``ValueError`` if unusable."""
    if not isinstance(data, dict):
        raise ValueError("Project file must contain a JSON object")

    version = int(data.get("version", PROJECT_VERSION) or PROJECT_VERSION)
    if version > PROJECT_VERSION:
        raise ValueError(
            f"This project was written by a newer ClipCraft (project v{version}, "
            f"this build reads v{PROJECT_VERSION})"
        )

    video = str(data.get("video") or "").strip()
    if not video:
        raise ValueError("Project file does not name a recording")

    in_time = max(0.0, float(data.get("in", 0.0) or 0.0))
    out_time = max(0.0, float(data.get("out", 0.0) or 0.0))
    if out_time and out_time < in_time:
        in_time, out_time = out_time, in_time

    audio = data.get("audio")
    captions = data.get("captions")
    template_path = data.get("template_path")

    return {
        "version": PROJECT_VERSION,
        "video": video,
        "template": str(data.get("template") or ""),
        "template_path": str(template_path) if template_path else None,
        "in": in_time,
        "out": out_time,
        "cuts": normalize_cuts(data.get("cuts") or []),
        "audio": dict(audio) if isinstance(audio, dict) else {},
        "captions": dict(captions) if isinstance(captions, dict) else None,
        "playhead": max(0.0, float(data.get("playhead", in_time) or 0.0)),
        "saved_at": str(data.get("saved_at") or ""),
    }


def save_project(path: str | Path, project: dict[str, Any]) -> Path:
    """Atomically write a project file."""
    payload = normalize_project(project)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temp, target)
    return target


def load_project(path: str | Path) -> dict[str, Any]:
    """Read and normalise a project file."""
    target = Path(path).expanduser()
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return normalize_project(data)


def push_recent_project(existing: list[str] | None, path: str | Path) -> list[str]:
    """Most-recent-first, de-duplicated, capped list for the recent-projects menu."""
    resolved = str(Path(path).expanduser().resolve())
    recent = [item for item in (existing or []) if item != resolved]
    recent.insert(0, resolved)
    return recent[:MAX_RECENT_PROJECTS]


def project_summary(project: dict[str, Any], duration: float | None = None) -> str:
    """One-line human summary for menus and status messages."""
    video = Path(project.get("video", "")).name or "project"
    cuts = len(project.get("cuts") or [])
    pieces = [video]
    if project.get("template"):
        pieces.append(str(project["template"]))
    if cuts:
        pieces.append(f"{cuts} cut{'s' if cuts != 1 else ''}")
    if duration is not None:
        pieces.append(f"{duration:.1f}s")
    return " · ".join(pieces)
