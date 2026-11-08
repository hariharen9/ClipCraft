"""Layer position keyframes.

A layer is static by default: its ``rect`` decides where it sits. Adding keys to
``layer["anim"]["keys"]`` makes the layer's *centre* move over the edited
timeline. Times are seconds from the start of the exported clip (after IN/OUT
trimming and cuts), so keyframes do not shift when removed footage changes.

Keys interpolate linearly and clamp outside their range. The renderer compiles
the same keys into FFmpeg overlay expressions, and the preview samples them with
``sample()`` — one source of truth for both.
"""

from __future__ import annotations

from typing import Any

Coord = tuple[float, float]

MAX_KEYS = 24


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def rect_center(rect: list[float]) -> Coord:
    """Normalized centre of a layer rect."""
    return (float(rect[0]) + float(rect[2]) / 2.0, float(rect[1]) + float(rect[3]) / 2.0)


def normalize_keys(
    keys: list[dict[str, Any]] | None,
    duration: float | None = None,
) -> list[dict[str, float]]:
    """Clamp, sort and de-duplicate keyframes.

    A key is ``{"t": seconds, "x": 0..1, "y": 0..1}`` where x/y are the layer's
    *centre* in normalized canvas space.
    """
    cleaned: list[dict[str, float]] = []
    for key in keys or []:
        if not isinstance(key, dict):
            continue
        if not {"t", "x", "y"} <= set(key.keys()):
            continue
        try:
            t = float(key["t"])
            x = float(key["x"])
            y = float(key["y"])
        except (TypeError, ValueError):
            continue
        if duration is not None:
            t = min(t, max(0.0, float(duration)))
        cleaned.append({"t": max(0.0, t), "x": clamp(x, 0.0, 1.0), "y": clamp(y, 0.0, 1.0)})

    cleaned.sort(key=lambda item: item["t"])
    merged: list[dict[str, float]] = []
    for key in cleaned:
        if merged and abs(key["t"] - merged[-1]["t"]) < 1e-3:
            merged[-1] = key  # Later key wins when two land on the same instant.
        else:
            merged.append(key)
    return merged[-MAX_KEYS:]


def keys_for_layer(layer: dict[str, Any], duration: float | None = None) -> list[dict[str, float]]:
    anim = layer.get("anim")
    if not isinstance(anim, dict):
        return []
    return normalize_keys(anim.get("keys"), duration)


def has_animation(layer: dict[str, Any]) -> bool:
    return bool(keys_for_layer(layer))


def sample(keys: list[dict[str, float]], time_value: float) -> Coord | None:
    """Interpolated centre at ``time_value``; clamps before the first / after the last key."""
    if not keys:
        return None
    t = float(time_value)
    if t <= keys[0]["t"]:
        return keys[0]["x"], keys[0]["y"]
    if t >= keys[-1]["t"]:
        return keys[-1]["x"], keys[-1]["y"]
    for index in range(1, len(keys)):
        right = keys[index]
        if t <= right["t"]:
            left = keys[index - 1]
            span = right["t"] - left["t"]
            ratio = 0.0 if span <= 1e-9 else (t - left["t"]) / span
            return (
                left["x"] + (right["x"] - left["x"]) * ratio,
                left["y"] + (right["y"] - left["y"]) * ratio,
            )
    return keys[-1]["x"], keys[-1]["y"]


def center_for_layer(
    layer: dict[str, Any],
    time_value: float,
    duration: float | None = None,
) -> Coord:
    """Animated centre at ``time_value``, falling back to the static rect centre."""
    keys = keys_for_layer(layer, duration)
    sampled = sample(keys, time_value)
    if sampled is not None:
        return sampled
    return rect_center(layer.get("rect", [0.0, 0.0, 1.0, 1.0]))


def piecewise_expression(points: list[tuple[float, float]], variable: str = "t") -> str:
    """Linear interpolation of ``points`` as an FFmpeg expression.

    ``variable`` is the FFmpeg time variable (``t`` for overlay, ``on/FRAME_RATE``
    for frame-counter filters). Values clamp outside the point range.
    """
    ordered = sorted(points)
    if not ordered:
        return "0"
    if len(ordered) == 1:
        return f"{ordered[0][1]:.6f}"

    expression = f"{ordered[-1][1]:.6f}"
    pairs = list(zip(ordered, ordered[1:]))
    for (t0, v0), (t1, v1) in reversed(pairs):
        span = t1 - t0
        if abs(span) < 1e-9:
            continue
        segment = f"({v0:.6f}+({v1 - v0:.6f})*({variable}-{t0:.6f})/{span:.6f})"
        expression = f"if(lt({variable},{t1:.6f}),{segment},{expression})"
    if ordered[0][0] > 1e-9:
        expression = f"if(lt({variable},{ordered[0][0]:.6f}),{ordered[0][1]:.6f},{expression})"
    return expression


def overlay_expressions(
    layer: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
    duration: float | None = None,
) -> tuple[str, str] | None:
    """FFmpeg overlay ``(x, y)`` expressions for an animated layer, or None."""
    keys = keys_for_layer(layer, duration)
    if len(keys) < 2:
        return None
    rect = layer.get("rect", [0.0, 0.0, 1.0, 1.0])
    half_w = float(rect[2]) * canvas_w / 2.0
    half_h = float(rect[3]) * canvas_h / 2.0
    x_expr = piecewise_expression([(key["t"], key["x"]) for key in keys], "t")
    y_expr = piecewise_expression([(key["t"], key["y"]) for key in keys], "t")
    return (
        f"({x_expr})*{canvas_w}-{half_w:.2f}",
        f"({y_expr})*{canvas_h}-{half_h:.2f}",
    )
