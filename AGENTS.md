# ClipCraft — Master Architecture & Technical Specification (`AGENTS.md`)

> **Primary Audience**: Software engineers, AI agents, and contributors.  
> **Purpose**: This document serves as the authoritative, self-contained technical specification and persistent mental model of the ClipCraft repository. Reading this document provides complete comprehension of the codebase, component interactions, mathematical engines, data schemas, rendering pipeline, threading models, and operational workflows without needing to re-read every individual source file.

---

## Table of Contents
1. [Executive Summary & Purpose](#1-executive-summary--purpose)
2. [Technology Stack & System Requirements](#2-technology-stack--system-requirements)
3. [Repository File Map & Line Inventory](#3-repository-file-map--line-inventory)
4. [Data Models, Schemas & Dynamic Tokens](#4-data-models-schemas--dynamic-tokens)
5. [Coordinate Systems & Mathematical Transformations](#5-coordinate-systems--mathematical-transformations)
6. [Core Pipeline Deep Dive](#6-core-pipeline-deep-dive)
   - [6.1 Configuration & State Persistence (`clipcraft.config`)](#61-configuration--state-persistence-clipcraftconfig)
   - [6.2 Asset Generation Engine (`clipcraft.assets`)](#62-asset-generation-engine-clipcraftassets)
   - [6.3 FFmpeg Rendering Pipeline (`clipcraft.renderer`)](#63-ffmpeg-rendering-pipeline-clipcraftrenderer)
   - [6.4 Real-Time Preview Compositor (`clipcraft.preview`)](#64-real-time-preview-compositor-clipcraftpreview)
7. [GUI Architecture & Threading Model (`clipcraft.gui`)](#7-gui-architecture--threading-model-clipcraftgui)
   - [7.1 Studio Editor (`ClipCraftWindow`)](#71-studio-editor-clipcraftwindow)
   - [7.2 Playback Engine & Reverse Buffer](#72-playback-engine--reverse-buffer)
   - [7.3 Undo / Redo Transactional Model](#73-undo--redo-transactional-model)
   - [7.4 Batch Studio (`BatchWindow` & `BatchRenderWorker`)](#74-batch-studio-batchwindow--batchrenderworker)
   - [7.5 Visual Source Crop System (`VisualSourceCropDialog`)](#75-visual-source-crop-system-visualsourcecropdialog)
   - [7.6 Canvas Items, Grips & Safe Zones (`canvas_items.py`)](#76-canvas-items-grips--safe-zones-canvas_itemspy)
   - [7.7 Layer Stack & Property Inspector](#77-layer-stack--property-inspector)
8. [Comprehensive API, Class & Function Index](#8-comprehensive-api-class--function-index)
9. [Keyboard Shortcuts & Pro NLE Controls](#9-keyboard-shortcuts--pro-nle-controls)
10. [Testing Suite & Quality Verification](#10-testing-suite--quality-verification)
11. [Critical Invariants & Developer Guidelines](#11-critical-invariants--developer-guidelines)

---

## 1. Executive Summary & Purpose

**ClipCraft** is a high-performance desktop video editor and GPU-accelerated rendering engine designed for content creators, streamers, and gamers. Its core objective is to eliminate the 20–40 minute workflow typically required in complex NLEs (such as Adobe Premiere Pro or DaVinci Resolve) to convert standard 16:9 widescreen gameplay recordings into viral 9:16 vertical shorts (for YouTube Shorts, TikTok, Instagram Reels).

### Core Value Propositions:
1. **Multi-Stream Spatial Composition**: Slices a single 16:9 input recording into multiple concurrent streams:
   - Dynamic, color-graded, Gaussian-blurred full-bleed background.
   - Scaled primary gameplay feed (supporting `cover` or `contain` fit).
   - Arbitrary cropped sub-regions (facecam, killfeed, chat, inventory, minimap).
   - Rasterized vector-styled text (captions, meme text, watermarks) and transparent branding PNGs.
2. **Interactive Visual Cropping**: Eliminates manual coordinate input. Users drag and scale an 8-handle crop box directly over the uncropped 16:9 frame.
3. **Hardware-Accelerated Encoding**: Direct integration with FFmpeg using NVIDIA NVENC (`h264_nvenc`) with seamless automatic CPU fallback (`libx264`).
4. **Batch Processing Studio**: Full multi-clip queue interface with timeline trimming, live 9:16 composited previews, and sequential background rendering.

---

## 2. Technology Stack & System Requirements

- **Runtime**: Python `>= 3.10` (tested and validated on Python 3.11).
- **GUI Engine**: `PySide6` (`>=6.7, <7`): Qt Widgets, `QGraphicsScene`, `QGraphicsView`, `QGraphicsItem`, `QThread`, `QTimer`, Signals/Slots.
- **Computer Vision & Video Decoding**: `opencv-python` (`>=4.9`): Direct video stream demuxing via `cv2.VideoCapture`, frame scrubbing, spatial matrix operations, and Gaussian blur.
- **Numerical Processing**: `numpy` (`>=1.26`): Image array manipulation, channel conversions, memory contiguous slicing.
- **Image Rasterization**: `Pillow` (`Pillow>=10.0`): Alpha channel bounding box extraction (`getbbox()`), FreeType font resolution, multi-pass text stroke drawing (`ImageDraw`).
- **Vector Icons**: `qtawesome` (`>=1.3.0`): FontAwesome 5 Solid and Material Design vector icons directly embedded into Qt push buttons.
- **External Binaries**:
  - `ffmpeg`: System executable required on `PATH` for multi-stream filter graph execution and encoding.
  - `ffprobe`: System executable required on `PATH` for stream probing and metadata extraction.

---

## 3. Repository File Map & Line Inventory

```
ClipCraft/
│
├── clipcraft/                         # Core Python Package
│   ├── __init__.py                    # Package metadata (__version__ = "0.1.0")
│   ├── config.py                      # JSON config validation, template discovery, atomic state persistence
│   ├── assets.py                      # Procedural PIL asset generation for branding fallbacks
│   ├── renderer.py                    # FFmpeg command builder, filter_complex graph generator, subprocess runner
│   ├── preview.py                     # OpenCV/PIL software compositor mirroring FFmpeg in real time
│   ├── batch_gui.py                   # Backward-compatibility import shim for BatchWindow
│   │
│   └── gui/                           # Modular PySide6 GUI Package
│       ├── __init__.py                # Package exports, constants, and compatibility aliases
│       ├── constants.py               # Look presets, render presets, token time formatting, size limits
│       ├── worker.py                  # QThread background worker for single clip render
│       ├── canvas_items.py            # QGraphicsItems: LayerItem, HandleItem, SafeZoneOverlayItem
│       ├── crop_dialog.py             # VisualSourceCropDialog & VisualCropBoxItem
│       ├── layer_stack.py             # LayerStackWidget (Z-order reordering, eye toggles, badges)
│       ├── transport_bar.py           # TransportWidget (scrubber, shuttle buttons, speed, IN/OUT)
│       ├── inspector.py               # LayerInspectorWidget (sidebar for properties, typography, geometry)
│       ├── main_window.py             # ClipCraftWindow: Primary 3-panel editor and controller
│       └── batch_window.py            # BatchWindow & BatchRenderWorker: Multi-clip batch queue studio
│
├── templates/                         # Layout Template Definitions (JSON)
│   ├── valorant.json                  # Valorant layout (main, killfeed, chat, logos, titles)
│   ├── valorant.example.json          # Example template with relative assets and creator branding
│   ├── r6siege.json                   # Rainbow Six Siege (operator HUD, weapon HUD, round timer, killfeed)
│   ├── cs2.json                       # Counter-Strike 2 (radar top-left, killfeed top-right, health/ammo)
│   ├── apex.json                      # Apex Legends (squad health, minimap, killfeed, weapons)
│   ├── warzone.json                   # Call of Duty: Warzone (minimap, killfeed, team status, perks)
│   ├── fortnite.json                  # Fortnite (storm minimap, eliminated feed, health/shield, inventory)
│   ├── lol.json                       # League of Legends (champion ability bar, minimap, score)
│   ├── general_cam.json               # Generic gaming layout with dedicated top facecam
│   └── general_nocam.json             # Gameplay-focused clean layout
│
├── tests/                             # Automated Test Suite (All 22 tests passing)
│   ├── __init__.py                    # Test package marker
│   ├── test_cli.py                    # CLI arg parsing & time format conversion (MM:SS, HH:MM:SS)
│   ├── test_gui_smoke.py              # Smoke tests for Qt widgets, instantiation, and dialogs
│   ├── test_state.py                  # Atomic state persistence, corruption handling, path resolution
│   ├── test_templates.py              # Template schema validation & config cloning
│   └── test_tokens.py                 # Dynamic filename token substitution & formatting
│
├── clipcraft.py                       # CLI and application entry point
├── quick_edit.pyw                     # Zero-console Windows Explorer drag-and-drop launcher
├── clipcraft_state.json               # Portable local state file (recent files, folder, preferences)
├── pyproject.toml                     # PEP 517/518 build metadata & dependencies
├── requirements.txt                   # Pip dependency manifest
└── *.bat                              # Windows batch scripts: install, run_gui, run_batch, render
```

---

## 4. Data Models, Schemas & Dynamic Tokens

### 4.1 Template JSON Schema (`templates/<game>.json`)

Templates configure the full vertical layout and encoding parameters:

```json
{
  "version": 1,
  "name": "Valorant",
  "canvas": {
    "width": 1080,
    "height": 1920,
    "fps": 60,
    "encoder": "auto",
    "quality": 14,
    "nvenc_preset": "p5",
    "x264_preset": "medium"
  },
  "background": {
    "blur": 2.0,
    "brightness": -0.07,
    "saturation": 1.19
  },
  "branding": {
    "channel_name": "CREATOR",
    "youtube_handle": "@creator",
    "instagram_handle": "@creator"
  },
  "layers": {
    "background": {
      "kind": "background",
      "rect": [0.0, 0.0, 1.0, 1.0],
      "z": 0,
      "visible": true
    },
    "main": {
      "kind": "video",
      "rect": [0.0, 0.25, 1.0, 0.50],
      "crop": [0.0, 0.0, 1.0, 1.0],
      "fit": "cover",
      "z": 10,
      "visible": true
    },
    "killfeed": {
      "kind": "video",
      "rect": [0.43, 0.16, 0.56, 0.09],
      "crop": [0.73, 0.06, 0.27, 0.14],
      "fit": "cover",
      "z": 20,
      "visible": true
    },
    "title_graphic": {
      "kind": "image",
      "asset": "assets/title.png",
      "rect": [0.20, 0.05, 0.60, 0.05],
      "fit": "contain",
      "opacity": 1.0,
      "z": 40,
      "visible": true
    },
    "caption_text": {
      "kind": "text",
      "text": "INSANE CLUTCH!",
      "font": "Impact",
      "font_size": 48,
      "bold": true,
      "color": "#FFFFFF",
      "stroke_color": "#000000",
      "stroke_width": 3,
      "align": "center",
      "rect": [0.10, 0.80, 0.80, 0.08],
      "z": 50,
      "opacity": 1.0,
      "visible": true
    }
  }
}
```

#### Layer Properties Matrix:
| Field | Type | Description |
| :--- | :--- | :--- |
| `kind` | `string` | One of: `"background"`, `"video"`, `"image"`, `"text"`. |
| `rect` | `[float, float, float, float]` | Normalized `[x, y, width, height]` relative to canvas dimensions (0.0 to 1.0). |
| `crop` | `[float, float, float, float]` | (`video` only) Normalized `[x, y, width, height]` relative to source video (0.0 to 1.0). |
| `fit` | `string` | `"cover"` (crop to fill) or `"contain"` (letterbox/preserve aspect) or `"fill"`. |
| `z` | `int` | Integer Z-order. Layers are composited in strictly ascending order. |
| `visible` | `bool` | Visibility toggle. Hidden layers are skipped during rendering and preview. |
| `opacity` | `float` | Alpha multiplier from `0.0` (invisible) to `1.0` (fully opaque). |
| `asset` | `string` | (`image` only) File path relative to template location or absolute. |
| `text` | `string` | (`text` only) String content to render. |
| `font` | `string` | (`text` only) Font family name (Impact, Arial, Segoe UI, etc.). |
| `font_size` | `int` | (`text` only) Base point size at 1080p canvas width. |
| `bold` | `bool` | (`text` only) Whether to use the bold font variant. |
| `color` | `string` | (`text` only) Hex color for text fill (e.g., `"#FFFFFF"`). |
| `stroke_color` | `string` | (`text` only) Hex color for outline stroke (e.g., `"#000000"`). |
| `stroke_width` | `int` | (`text` only) Outline thickness in pixels at 1080p scale. |
| `align` | `string` | (`text` only) Horizontal alignment: `"center"`, `"left"`, `"right"`. |

### 4.2 State File Schema (`clipcraft_state.json`)

Saved atomically via temporary file swap:

```json
{
  "source_dir": "D:\\NVIDIA Captures\\Valorant",
  "show_grips": true,
  "preview_sharp": true,
  "last_template": "valorant",
  "show_safe_zones": false,
  "recent_files": [
    "D:\\NVIDIA Captures\\Valorant\\clip1.mp4",
    "D:\\NVIDIA Captures\\Valorant\\clip2.mp4"
  ],
  "output_pattern": "{clip}_{game}_{in}-{out}"
}
```

### 4.3 Dynamic Output Filename Tokens

Dynamic patterns configured in `output_pattern` are resolved during export:

| Token | Meaning | Example Output |
| :--- | :--- | :--- |
| `{clip}` | Source video file stem | `Valorant_Clutch_01` |
| `{game}` | Active template identifier | `valorant` |
| `{in}` | Trim IN timestamp | `0s`, `15s`, `1m20s` |
| `{out}` | Trim OUT timestamp | `35s`, `2m05s` |
| `{dur}` | Clip duration (`out - in`) | `20s`, `45s` |
| `{date}` | Current system date (`YYYY-MM-DD`) | `2026-11-07` |
| `{time}` | Current system time (`HHMMSS`) | `143015` |
| `{res}` | Canvas resolution string | `1080x1920` |

---

## 5. Coordinate Systems & Mathematical Transformations

ClipCraft operates across three distinct coordinate domains:

```
[ Normalized Coordinates ] ──► [ Preview Scene Units ] ──► [ Canvas Render Pixels ]
      (0.0 to 1.0)                 (360x640 * scale)             (e.g., 1080x1920)
```

1. **Normalized Unit Space (`[0.0, 1.0]`)**:
   - Stored in template JSON definitions (`rect` and `crop`).
   - Resolution-independent: A layer defined at `rect: [0.0, 0.25, 1.0, 0.50]` spans the entire width and middle half of any canvas size.
2. **Preview Scene Space (`QGraphicsScene`)**:
   - Baseline geometry is $360 \times 640$ pixels.
   - Scaled by `preview_scale`: $1.0\times$ (standard $360 \times 640$) or $1.5\times$ (sharp preview $540 \times 960$).
   - `LayerItem` positions and handle grips live entirely in this space.
3. **Canvas Render Output Space (FFmpeg Target)**:
   - Full master resolution (typically $1080 \times 1920$).
   - Normalized coordinates are multiplied by output width/height and rounded to the nearest **even integer** using `_even()` to satisfy H.264 YUV420p chroma subsampling requirements.

### Geometry Algorithms:
- **`contain_fit(native_w, native_h, box_w, box_h)`**:
  $$\text{scale} = \min\left(\frac{\text{box\_w}}{\text{native\_w}}, \frac{\text{box\_h}}{\text{native\_h}}\right)$$
  $$\text{draw\_w} = \max(2, \text{round}(\text{native\_w} \times \text{scale})), \quad \text{draw\_h} = \max(2, \text{round}(\text{native\_h} \times \text{scale}))$$
- **`fit_cover(frame, target_w, target_h)`**:
  Scales input frame up until both dimensions meet or exceed targets, then centers and crops excess edges.
- **`fit_contain(frame, target_w, target_h)`**:
  Scales input frame to fit completely within targets, centering the result on a black canvas.
- **`image_content_info(path)`**:
  Opens image, extracts alpha channel, and executes `rgba.getchannel("A").getbbox()`. This discards empty transparent padding around logos so grips and alignment snap to the visible artwork.

---

## 6. Core Pipeline Deep Dive

### 6.1 Configuration & State Persistence (`clipcraft.config`)
- **`get_state_file()`**: Resolves state path with portable-first precedence:
  1. Checks if `clipcraft_state.json` exists in `APP_DIR`. If found, portable mode is preserved.
  2. Windows fallback: `%LOCALAPPDATA%/ClipCraft/state.json` or `%APPDATA%/ClipCraft/state.json`.
  3. POSIX fallback: `$XDG_CONFIG_HOME/clipcraft/state.json` or `~/.config/clipcraft/state.json`.
- **`save_config()` / `save_state()`**:
  Enforces atomic writes via `.tmp` file writing followed by `replace()` to prevent JSON corruption during power loss or abrupt termination.
- **`validate_config(data)`**:
  Strict validation gate:
  - Width and height must be integers between 180 and 7680.
  - Dimensions must be even (`width % 2 == 0`, `height % 2 == 0`).
  - FPS must be between 1 and 120.
  - `layers.background` must exist.
  - Layer rects and video crops must contain exactly 4 positive numeric values.

### 6.2 Asset Generation Engine (`clipcraft.assets`)
If referenced assets do not exist, `ensure_assets()` procedurally synthesizes starter assets using Pillow:
- `make_valorant_title()`: Renders angular Valorant "V" polygon and title text.
- `make_valorant_logo()`: Synthesizes red angular V emblem icon with border and drop-shadow.
- `make_socials()`: Generates YouTube red pill and Instagram magenta rounded camera with handles.
- `make_panda_logo()`: Synthesizes high-res glowing mascot graphic with Gaussian blurred glow.

### 6.3 FFmpeg Rendering Pipeline (`clipcraft.renderer`)

#### Probe Phase (`probe_video`)
Executes `ffprobe` with JSON output formatting:
```bash
ffprobe -v error -show_streams -show_format -of json <video_path>
```
Extracts `duration`, `width`, `height`, calculated `fps` (`num / den`), codec, and audio stream presence.

#### Filter Graph Synthesis (`build_filter_complex`)
1. Slices primary video stream `[0:v]` into $N+1$ outputs using `split`:
   ```
   [0:v]fps=60,split=3[vsrc0][vsrc1][vsrc2]
   ```
2. **Background Branch (`vsrc0`)**:
   - Downscaled to 50% ($540 \times 960$) to minimize blur compute time.
   - Cropped, blurred via `boxblur=blur:2`.
   - Color graded via `eq=brightness=...:saturation=...`.
   - Scaled back up to $1080 \times 1920$ output.
3. **Unified Z-Order Compositing Pass**:
   - All visible non-background layers (`video`, `image`, `text`) are sorted strictly by ascending `z`-index and composited onto `comp{idx}` in a single sequential chain, guaranteeing visual parity with the preview canvas.
   - **Video Layers**: Cropped, scaled (`cover` / `contain`), opacity adjusted via `colorchannelmixer`, and overlaid onto `comp{idx}`.
   - **Image Layers**: Alpha padded regions cropped via `crop=W:H:X:Y`, scaled with optional aspect contain, and overlaid.
   - **Text Layers**: Pre-rendered to high-res temporary PNGs via `preview.render_text_image()`, added as loop inputs (`-loop 1 -framerate 60 -i temp.png`), and overlaid.
4. **Color Format Finalization**:
   - Appends `format=yuv420p[outv]` for universal mobile player compatibility.

#### Encoder Selection & Subprocess Execution (`run_render`)
- **GPU (NVIDIA NVENC)**:
  ```bash
  -c:v h264_nvenc -preset p5 -tune hq -rc vbr -cq 14 -b:v 0 -profile:v high -spatial-aq 1 -temporal-aq 1
  ```
- **CPU (libx264)**:
  ```bash
  -c:v libx264 -preset medium -crf 14 -profile:v high
  ```
- **Audio Pipeline (`build_audio_filter_graph`)**:
  - Integrated directly into `-filter_complex` with dual-stream processing:
    - Primary gameplay audio resampled and volume-adjusted (`aresample=48000:async=1:first_pts=0,volume=...`).
    - Looped background music track (`-stream_loop -1 -i bgm.mp3`).
    - **Sidechain Auto-Ducking**: When in-game voice chat or combat audio peaks, `sidechaincompress=threshold=0.125:ratio=4:attack=20:release=250` automatically ducks BGM volume.
    - Mixed via `amix=inputs=2:duration=first:dropout_transition=2:normalize=0`.
    - **Boundary Audio Fades**: Smooth 0.5s fade-in (`afade=t=in:ss=0:d=0.5`) and fade-out (`afade=t=out:st=...:d=0.5`) eliminate pop and click artifacts.
    - Encoded via `-c:a aac -b:a 192k -ar 48000`.
- **Execution & Fallback**:
  Runs via `subprocess.Popen` with `-progress pipe:1`. If encoder is `"auto"` and NVENC returns non-zero, it automatically restarts encoding using the CPU `libx264` pipeline.

### 6.4 Real-Time Preview Compositor (`clipcraft.preview`)
Maintains pixel-perfect parity with FFmpeg inside Python:
- `render_background()`: Matches FFmpeg chroma saturation adjustments by converting to grayscale and using weighted blending (`cv2.addWeighted`).
- `normalized_crop()`: Slices raw NumPy arrays with boundary clamping.
- `render_text_image()`: Multi-pass text drawing with stroke outlines and alignment offsets.
- `to_qimage_array()`: Zero-copy conversion of NumPy BGR, RGBA, or Grayscale arrays into Qt `QImage` structures.

---

## 7. GUI Architecture & Threading Model (`clipcraft.gui`)

### 7.1 Studio Editor (`ClipCraftWindow`)
A 3-panel responsive layout:
- **Left Panel**: Transport controls, background look sliders, Audio & BGM management (volume, auto-ducking, fades), export pattern settings, render presets, progress bar.
- **Center Panel**: Canvas preview with `QGraphicsScene` and `QGraphicsView`, grips toggle, safe-zones toggle, sharp preview toggle.
- **Right Panel**: Layer inspector with layer list, eye toggles, typography controls, geometry spinboxes, source crop controls, and undo/redo history.

### 7.2 Playback Engine & Reverse Buffer
To maintain smooth 60fps playback without UI freezing:
- Driven by a 16ms `QTimer` (`_play_tick`).
- **Selective Redraw Optimization**: On playback ticks, **only** the background pixmap and video layer pixmaps are updated via `_update_frame_layers()`. Scene items, grip handles, text layers, and image layers are never destroyed or rebuilt during playback.
- **Shuttle Forward (`L`)**: Supports $1\times$, $2\times$, and $4\times$ playback via real-time clock pacing (`_read_backlog`).
- **Shuttle Reverse (`J`)**: Uses `_load_reverse_batch()` to decode small batches (~0.25s of footage) into `_reverse_buffer`, allowing rapid backward playback without seeking on every single frame.

### 7.3 Undo / Redo Transactional Model
- Manages an in-memory history of up to 100 deep-copied configuration snapshots.
- **Continuous Input Debouncing**: Continuous interactions (dragging sliders, moving canvas layers) start an interaction via `_pending_undo` and commit via an 800ms `QTimer` debounce or upon `mouseReleaseEvent`. This ensures single undo steps rather than dozens of micro-steps.

### 7.4 Batch Studio (`BatchWindow` & `BatchRenderWorker`)
- Multi-clip queue interface managing `BatchJob` dataclasses.
- Custom `TrimTimeline` widget: Self-painting Qt widget displaying IN/OUT flags, duration brackets, and draggable playhead.
- **Live 9:16 Preview**: Composited on the fly using OpenCV and pre-cached PIL assets.
- **Background Execution**: `BatchRenderWorker` (`QThread`) executes jobs sequentially while streaming progress to dual progress bars (job progress and overall queue progress).

### 7.5 Visual Source Crop System (`VisualSourceCropDialog`)
- Modal dialog containing an interactive `VisualCropBoxItem` with 8 resize handles over the uncropped 16:9 source frame.
- Displays live pixel dimensions and normalized percentages.
- Applying commits changes back to the layer config and records an undo snapshot.

### 7.6 Canvas Items, Grips & Safe Zones (`canvas_items.py`)
- **`LayerItem`**: Subclasses `QGraphicsPixmapItem`. Tracks geometry in true scene units (`_geo`) independent of Qt's selectable-item padding.
- **`HandleItem`**: Subclasses `QGraphicsRectItem`. Dedicated 8-point resize grips (`nw`, `n`, `ne`, `e`, `se`, `s`, `sw`, `w`). Holding Shift or selecting a `contain` layer enforces strict aspect ratio preservation.
- **`SafeZoneOverlayItem`**: Guideline overlay visualizing YouTube Shorts and TikTok UI dead zones (Top Bar 11%, Bottom Captions 20%, Right Engagement 19%).

### 7.7 Layer Stack & Property Inspector
- **`LayerStackWidget`**: Reorders layers via drag-and-drop or Forward/Backward buttons. Toggles visibility with vector eye icons. Displays type badges: `[VID]`, `[TXT]`, `[IMG]`.
- **`LayerInspectorWidget`**: Dynamic property inspector. Automatically toggles between Typography controls (for text layers), Asset Pickers (for image layers), and Crop Spinboxes (for video layers).

---

## 8. Comprehensive API, Class & Function Index

### Module: `clipcraft.config`
- `get_state_file() -> Path`: Resolves state file with portable-first fallback.
- `load_config(path: str | Path | None) -> tuple[dict[str, Any], Path]`: Loads and validates template JSON.
- `save_config(data: dict[str, Any], path: str | Path) -> None`: Atomically saves configuration.
- `load_state(path: str | Path | None) -> dict[str, Any]`: Loads user preferences.
- `save_state(data: dict[str, Any], path: str | Path | None) -> None`: Atomically saves user preferences.
- `validate_config(data: dict[str, Any]) -> None`: Validates canvas, FPS, and layer schemas.
- `template_path(game: str) -> Path`: Resolves `templates/<game>.json`.
- `available_templates() -> list[tuple[str, str]]`: Returns sorted `(game_id, display_name)` pairs.
- `migrate_legacy_config() -> None`: Migrates root `config.json` into `templates/valorant.json`.
- `contain_fit(native_w, native_h, box_w, box_h) -> tuple[int, int]`: Proportional box scale math.
- `image_content_info(path: Path) -> tuple[int, int, tuple[int, int, int, int] | None]`: Returns dimensions and alpha bbox.
- `clone_config(data: dict[str, Any]) -> dict[str, Any]`: Deep copy utility.

### Module: `clipcraft.renderer`
- `find_ffmpeg() -> str`: Locates `ffmpeg` on system `PATH`.
- `probe_video(path: str | Path, ffprobe: str | None) -> dict[str, Any]`: Extracts stream metrics via `ffprobe`.
- `build_filter_complex(config, config_path, video_info) -> tuple[str, list[Path]]`: Compiles FFmpeg filter string.
- `build_ffmpeg_command(video_path, output_path, start, end, config, config_path, encoder) -> tuple[list[str], float]`: Assembles complete FFmpeg CLI command.
- `run_render(...) -> Path`: Executes subprocess, streams progress, falls back to CPU on NVENC failure.

### Module: `clipcraft.preview`
- `resolve_font(family: str, size: int, bold: bool) -> ImageFont`: Resolves system TTF font with fallbacks.
- `render_text_image(...) -> np.ndarray`: Rasterizes stroked text into RGBA NumPy array.
- `normalized_crop(frame: np.ndarray, crop: list[float]) -> np.ndarray`: Slices frame by normalized bounds.
- `fit_cover(frame: np.ndarray, width: int, height: int) -> np.ndarray`: Scales and crops to fill.
- `fit_contain(frame: np.ndarray, width: int, height: int) -> np.ndarray`: Scales with letterbox padding.
- `render_background(frame: np.ndarray, width: int, height: int, config) -> np.ndarray`: Generates blurred color-graded backdrop.
- `layer_preview_image(...) -> tuple[np.ndarray | None, float | None]`: Generates composited layer preview.
- `to_qimage_array(image: np.ndarray) -> QImage`: Zero-copy NumPy to Qt image conversion.

### Module: `clipcraft.gui`
- `ClipCraftWindow`: Primary single-clip editing studio.
- `BatchWindow`: Multi-clip queue studio.
- `VisualSourceCropDialog`: Full-screen 16:9 interactive crop dialog.
- `LayerStackWidget`: Reorderable layer list with eye toggles.
- `LayerInspectorWidget`: Sidebar property inspector.
- `TransportWidget`: Scrubber and playback transport bar.
- `RenderWorker`: `QThread` single clip render runner.
- `BatchRenderWorker`: `QThread` multi-clip sequential render runner.
- `LayerItem` / `HandleItem` / `SafeZoneOverlayItem`: Canvas graphics items.

---

## 9. Keyboard Shortcuts & Pro NLE Controls

| Shortcut | Context | Action |
| :--- | :--- | :--- |
| **`Space`** | Main / Batch | Toggle Play / Pause playback |
| **`I`** | Main / Batch | Set **IN** trim point to playhead |
| **`O`** | Main / Batch | Set **OUT** trim point to playhead |
| **`J`** | Main | Shuttle backward (tap repeatedly for 2×, 4× speed) |
| **`K`** | Main | Pause playback / shuttling |
| **`L`** | Main | Shuttle forward (tap repeatedly for 2×, 4× speed) |
| **`←` / `→`** | Main / Batch | Step 1 frame backward / forward |
| **`Shift + ←` / `→`** | Main / Batch | Jump 1 second backward / forward |
| **`Ctrl + Z`** | Main | Undo last canvas, layout, crop, or text change |
| **`Ctrl + Shift + Z`** | Main | Redo last undone change |
| **`Shift + Drag Grip`** | Canvas | Constrain layer aspect ratio while resizing |
| **`Delete`** | Batch | Remove selected clip from queue |

---

## 10. Testing Suite & Quality Verification

Run the entire automated test suite:
```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Test Coverage Summary:
- `tests/test_cli.py`: Verifies time parsing (seconds, MM:SS, HH:MM:SS), argument parsing, default output naming.
- `tests/test_gui_smoke.py`: Headless Qt tests verifying widget instantiation, transport states, layer selection, and dialogs.
- `tests/test_state.py`: Verifies state resolution (portable vs OS directory), atomic file write/swap, and corrupted JSON resilience.
- `tests/test_templates.py`: Enforces schema validity, layer types, and rect geometry across all files in `templates/`.
- `tests/test_tokens.py`: Tests `format_token_time` and token substitution patterns.

---

## 11. Critical Invariants & Developer Guidelines

1. **Preview & Renderer Parity**: Whenever updating how layers or backgrounds render (blur, opacity, fit, scale, crop, typography), changes must be implemented simultaneously in both `clipcraft/renderer.py` (FFmpeg filter graph) and `clipcraft/preview.py` (OpenCV/PIL preview).
2. **Even Canvas Dimensions**: Always enforce that output canvas width and height are even integers (`width % 2 == 0`, `height % 2 == 0`). Odd dimensions will cause FFmpeg `yuv420p` encoding to fail.
3. **Playback Performance**: In `main_window.py`, never call `refresh_canvas()` during playback ticks. Only update video layer pixmaps and background via `_update_frame_layers()`.
4. **State Persistence**: Always use `save_state()` and `save_config()` from `clipcraft.config`, which write to `.tmp` files before atomic replacement. Never write directly to target JSON files.
5. **Backwards Compatibility**: Maintain compatibility shims when restructuring:
   - `clipcraft.batch_gui` shim for `clipcraft.gui.batch_window`.
6. **Launcher & Virtualenv Resilience**: Batch launchers (`run_gui.bat`, `run_batch.bat`, `render.bat`, `install.bat`) must directly invoke `%~dp0.venv\Scripts\python.exe` to avoid executing system Python (e.g. Python 3.13) which may lack dependencies. Launchers must keep the window open (`pause`) on non-zero exit codes. Unhandled crashes and GUI startup errors must be written to `clipcraft.log` via `_setup_crash_logging()` in `clipcraft.py`.
