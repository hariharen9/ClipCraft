"""Make a template self-contained by copying its images beside it.

Templates used to reference absolute paths (``D:/.../logo.png``), which works on
exactly one machine: the portable build ships ``templates/*.json`` but not those
files, and a shared template breaks instantly. Bundling copies every image into
``templates/assets/<template>/`` and rewrites the layer paths to be relative.
"""

from __future__ import annotations

import copy
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import TEMPLATES_DIR, resolve_asset, save_config


@dataclass
class BundleResult:
    config: dict[str, Any]
    path: Path
    copied: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def template_id(self) -> str:
        return self.path.stem


def slugify(name: str) -> str:
    """Filesystem-friendly template id: lowercase words separated by underscores."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return slug or "template"


def _unique_id(base_slug: str, templates_dir: Path) -> str:
    candidate = base_slug
    index = 2
    while (templates_dir / f"{candidate}.json").exists():
        candidate = f"{base_slug}_{index}"
        index += 1
    return candidate


def _safe_filename(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "image"
    stem, dot, suffix = cleaned.rpartition(".")
    if not dot:
        stem, suffix = cleaned, ""
    candidate = f"{stem}.{suffix}" if suffix else stem
    index = 2
    while candidate.lower() in used:
        candidate = f"{stem}_{index}.{suffix}" if suffix else f"{stem}_{index}"
        index += 1
    used.add(candidate.lower())
    return candidate


def bundle_template(
    config: dict[str, Any],
    config_path: str | Path,
    name: str,
    templates_dir: str | Path | None = None,
) -> BundleResult:
    """Copy a template and its images into ``templates/assets/<id>/``.

    Returns the new config (already saved), its path, the copied file names and
    any layers whose image could not be found.
    """
    source_config_path = Path(config_path).expanduser().resolve()
    target_root = Path(templates_dir).expanduser().resolve() if templates_dir else TEMPLATES_DIR
    target_root.mkdir(parents=True, exist_ok=True)

    template_name = str(name).strip() or "Template"
    template_id = _unique_id(slugify(template_name), target_root)
    assets_dir = target_root / "assets" / template_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    bundled = copy.deepcopy(config)
    bundled["name"] = template_name
    result = BundleResult(config=bundled, path=target_root / f"{template_id}.json")
    used_names: set[str] = set()
    seen_sources: dict[Path, str] = {}

    for layer_name, layer in (bundled.get("layers") or {}).items():
        if layer.get("kind") != "image":
            continue
        raw_asset = str(layer.get("asset") or "").strip()
        if not raw_asset:
            continue

        source = resolve_asset(source_config_path, raw_asset)
        if not source.is_file():
            result.missing.append(f"{layer_name}: {raw_asset}")
            continue

        # Two layers sharing one image should share one bundled copy too.
        if source.resolve() in seen_sources:
            layer["asset"] = seen_sources[source.resolve()]
            continue

        filename = _safe_filename(source.name, used_names)
        destination = assets_dir / filename
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)

        # Forward slashes keep the JSON portable across platforms.
        layer["asset"] = f"assets/{template_id}/{filename}"
        seen_sources[source.resolve()] = layer["asset"]
        result.copied.append(filename)

    save_config(bundled, result.path)
    return result
