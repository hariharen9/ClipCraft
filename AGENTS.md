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
   - [7.8 Split & Cut Studio (`split_dialog.py`)](#78-split--cut-studio-split_dialogpy)
   - [7.9 Projects, Autosave & Portable Templates](#79-projects-autosave--portable-templates)
   - [7.10 Animation Studio (`anim_dialog.py`)](#710-animation-studio-anim_dialogpy)
8. [Comprehensive API, Class & Function Index](#8-comprehensive-api-class--function-index)
9. [Keyboard Shortcuts & Pro NLE Controls](#9-keyboard-shortcuts--pro-nle-controls)
10. [Testing Suite & Quality Verification](#10-testing-suite--quality-verification)
11. [Critical Invariants & Developer Guidelines](#11-critical-invariants--developer-guidelines)
12. [Standalone Portable Windows Build](#12-standalone-portable-windows-build)

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
│   ├── segments.py                    # Cut-list math: kept spans, timeline<->source mapping, cut-aware stepping
│   ├── anim.py                        # Layer position keyframes: normalization, sampling, FFmpeg expressions
│   ├── project.py                     # .clipcraft sidecar: build/normalize/atomic save/load, recent projects
│   ├── silence.py                     # FFmpeg silencedetect parsing → cut regions for auto silence removal
│   ├── template_bundle.py             # Copy a template's images into templates/assets/<id>/ and rewrite paths
│   ├── batch_gui.py                   # Backward-compatibility import shim for BatchWindow
│   │
│   └── gui/                           # Modular PySide6 GUI Package
│       ├── __init__.py                # Package exports, constants, and compatibility aliases
│       ├── constants.py               # Look presets, render presets, token time formatting, size limits
│       ├── worker.py                  # QThread background worker for single clip render
│       ├── canvas_items.py            # QGraphicsItems: LayerItem, HandleItem, SafeZoneOverlayItem
│       ├── crop_dialog.py             # VisualSourceCropDialog & VisualCropBoxItem
│       ├── split_dialog.py            # SplitEditorDialog & SplitTimeline: split, delete segments, re-pick IN/OUT
│       ├── anim_dialog.py             # AnimationDialog & AnimTimeline: layer position keyframes studio
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
├── tests/                             # Automated Test Suite (all green)
│   ├── __init__.py                    # Test package marker
│   ├── test_cli.py                    # CLI arg parsing, time formats (MM:SS, HH:MM:SS), --cut ranges
│   ├── test_gui_smoke.py              # Smoke tests for Qt widgets, instantiation, dialogs, split timeline
│   ├── test_segments.py               # Cut math: normalization, kept spans, timeline mapping, cut-aware stepping
│   ├── test_render_cuts.py            # Trim/concat graph assembly + frame-exact end-to-end cut render
│   ├── test_fades.py                  # Per-layer fade chain + end-to-end alpha/colour fade renders
│   ├── test_project.py                # Sidecar build/normalize/save/load, version guard, recent list
│   ├── test_project_gui.py            # Autosave, restore, dirty marking, prefilled silence cuts, template save-as
│   ├── test_silence.py                # silencedetect parsing, padding, end-to-end tone/silence detection
│   ├── test_template_bundle.py        # Asset copying, path rewriting, id collisions, shared images
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
| `fade_enabled` | `bool` | Enables the fade-in/out ramp for this layer. Absent means no fade. |
| `fade_in` | `float` | Seconds to ramp the layer in from transparent (default `0.5`). |
| `fade_out` | `float` | Seconds to ramp the layer out to transparent at the clip end (default `0.5`). |
| `anim` | `object` | Optional position keyframes: `{"keys": [{"t": 0.0, "x": 0.5, "y": 0.5}, …]}`. x/y are the layer **centre** (0..1) at edited-timeline second `t`. Fewer than two keys = static. |
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
| `{dur}` | Result duration (`out - in` minus cut regions) | `20s`, `45s` |
| `{date}` | Current system date (`YYYY-MM-DD`) | `2026-11-07` |
| `{time}` | Current system time (`HHMMSS`) | `143015` |
| `{res}` | Canvas resolution string | `1080x1920` |

### 4.4 Project Sidecar (`<recording>.clipcraft`)

A template is *how* a short looks; a project is *this* edit. The sidecar lives next to the recording (`clutch.mp4` → `clutch.clipcraft`) and is written atomically:

```json
{
  "version": 1,
  "video": "D:/Captures/clutch.mp4",
  "template": "valorant",
  "template_path": "E:/Projects/ClipCraft/templates/valorant.json",
  "in": 2.5,
  "out": 42.0,
  "cuts": [[10.0, 13.0]],
  "audio": {"bgm_path": "song.mp3", "bgm_volume": 0.4},
  "captions": {"enabled": true, "cues": []},
  "playhead": 5.0,
  "saved_at": "2026-11-08T15:00:00"
}
```

- **Autosave**: trim edits, applied cuts, audio/caption changes and template switches mark the project dirty and schedule a write 1.2 s later (`AUTOSAVE_DELAY_MS`); closing the window flushes it.
- **Restore**: opening a recording automatically applies its sidecar, including cuts. A corrupt sidecar is ignored (the video still opens); a `version` newer than the build raises a clear error.
- **Recent projects** live in the state file (`recent_projects`, capped at 10) and appear under *Recent ▾ → Project*.
- The `template`/`template_path` fields are references only — layout edits still live in the template.

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

#### Cut Preprocessing (`build_cut_filter`)
Before any layout work, the source is reduced to the kept spans (IN/OUT minus the user's cut regions):

```
[0:v]trim=end=2.000000,setpts=PTS-STARTPTS[cv0]
[0:a]atrim=end=2.000000,asetpts=PTS-STARTPTS[ca0]
[0:v]trim=start=4.000000:end=8.000000,setpts=PTS-STARTPTS[cv1]
[0:a]atrim=start=4.000000:end=8.000000,asetpts=PTS-STARTPTS[ca1]
[cv0][cv1]concat=n=2:v=1:a=0[vcut]
[ca0][ca1]concat=n=2:v=0:a=1[acut]
```

- Span times are **relative to the IN point** because the input is seeked with `-ss <in>`.
- The first span omits `start=0`: after input seeking, frame 0 can carry a tiny negative PTS and an explicit `start=0` would drop it.
- Audio must be trimmed and concatenated too, using `atrim` + **`asetpts`** (`setpts` on an audio pad makes FFmpeg refuse to link the graph). Missing this is the classic A/V desync bug.
- `build_cut_filter()` returns `("", "0:v", "0:a")` when the cut list has no effect inside `[start, end]`, so an uncut render produces a byte-identical graph.
- The total `-t` duration is the sum of the kept spans, not `end - start`.

#### Per-Layer Fades (`build_layer_fade_filter`)
Each layer can ramp in/out independently (`fade_enabled`, `fade_in`, `fade_out`; default 0.5s each):

```
[lay_main]...,format=rgba,colorchannelmixer=aa=1.0000,fade=t=in:st=0:d=0.5000:alpha=1,
fade=t=out:st=2.5000:d=0.5000:alpha=1
```

- Overlaid layers use **alpha fades** (`alpha=1`), which reveal whatever is underneath. This requires an alpha-capable pix_fmt, hence `format=rgba` before the fade chain.
- Fade-out is anchored to the **edited** duration, so it always lands on the last exported frame: `st = duration - fade_out`, where `duration` is the kept length after cuts. Durations are clamped to the clip so a 0.5s fade cannot exceed a 0.4s clip.
- The **background** is the bottom of the stack, so an alpha fade there would be discarded by `format=yuv420p` (alpha is dropped, RGB stays). It therefore uses a **colour fade** (`alpha=False`) that ramps to/from black instead.
- Layers without `fade_enabled` get no extra filters at all, keeping their graph byte-identical.
- **Preview parity**: `main_window._layer_fade_factor()` computes the same ramp from source time (`source_to_timeline`) and multiplies each canvas item's opacity, so the ramp previews exactly and stays in sync during playback and across cut regions.

#### Animated Layer Positions (`clipcraft.anim` + `build_filter_complex`)
Layers with two or more keys in `layer["anim"]["keys"]` get time-varying overlay positions:

```
[comp0][lay_main]overlay=x='(0.200000+(0.600000)*(t-0.000000)/2.000000)*1080-108.00':
y='(...)*1920-96.00':eof_action=pass:shortest=1[comp1]
```

- Keys store the layer's **centre** in normalized canvas space at a time in **edited-timeline seconds** (after IN/OUT and cuts), so trimming or cutting never shifts the animation.
- `anim.piecewise_expression()` compiles the keys to a clamped, piecewise-linear FFmpeg expression (`if(lt(t,t1),…)`). Values clamp before the first and after the last key, exactly like `anim.sample()`.
- Overlay x/y is the top-left corner: `centre*canvas - rect/2`.
- With fewer than two keys the graph is byte-identical to a static layer — animation stays opt-in.
- The preview calls `LayerItem.setPos()` from the same `anim.sample()`; no pixmap rebuild, so per-tick cost is negligible.
- Supported keys are position only: FFmpeg cannot animate `scale` while keeping a constant overlay size, and `overlay`'s `alpha` option is not time-variable. Opacity animation therefore belongs to the fade controls for now.

#### Filter Graph Synthesis (`build_filter_complex`)
1. Slices the incoming video stream (the cut output `[vcut]`, or `[0:v]` when uncut) into $N+1$ outputs using `split`:
   ```
   [vcut]fps=60,split=3[vsrc0][vsrc1][vsrc2]
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
- `render_caption_overlay()`: Renders active word-by-word karaoke highlighted captions into an RGBA overlay for real-time playhead scrubbing and playback.
- `to_qimage_array()`: Zero-copy conversion of NumPy BGR, RGBA, or Grayscale arrays into Qt `QImage` structures.

### 6.5 AI Auto-Captions Engine (`clipcraft.captions`)
- **Local Speech-to-Text**: Powered by `faster-whisper` (CTranslate2) running locally with INT8 CPU acceleration or CUDA GPU float16. Includes `is_cuda_usable()` check for cuBLAS runtime DLLs (`cublas64_12.dll`) and automatic graceful CPU (`int8`) fallback to prevent crashes if CUDA runtime libraries are missing.
- **Word-Level Timestamping**: Extracts audio via FFmpeg (16kHz mono WAV) and transcribes with `word_timestamps=True`.
- **High-Retention Word Chunking**: `group_words_into_cues()` groups words into punchy, bite-sized 2–4 word phrases segmented by pauses, punctuation, and duration constraints.
- **Word-by-Word Karaoke Animation**:
  - Generates Advanced SubStation Alpha (`.ass`) subtitle files with active-word color tags (`{\c&H0000E6FF&}...{\c&H00FFFFFF&}`).
  - Burns directly into the video filter complex via FFmpeg `subtitles='...'` with zero frame drop and native vector sharpness.
  - Generates standard `.srt` subtitle files for creators desiring standalone subtitles.
  - Safe-zone positioning defaults to $Y=0.70$ (30% above bottom), keeping text above TikTok/Shorts UI overlays.

---

## 7. GUI Architecture & Threading Model (`clipcraft.gui`)

### 7.1 Studio Editor (`ClipCraftWindow`)
A 3-panel responsive layout:
- **Left Panel**: Transport controls, **Split & Cut…** launcher, background look sliders, Sound & Music launcher card (`AudioStudioDialog`), export pattern settings, render presets, progress bar.
- **Center Panel**: Canvas preview with `QGraphicsScene` and `QGraphicsView`, grips toggle, safe-zones toggle, sharp preview toggle.
- **Right Panel**: Layer inspector with layer list, eye toggles, typography controls, geometry spinboxes, source crop controls, and undo/redo history.
- **Window & splitters**: `launch_gui()` opens the window **maximised**; `F11` toggles borderless fullscreen and `Esc` returns to maximised. Left and right panes are wrapped in `QScrollArea`s with pinned minimum widths (336 / 416) and the splitter keeps their size (stretch factors `0,1,0`), so extra width always grows the canvas. The inspector's property rows naturally need ~392px; giving it 300px silently clips labels, which is why the minimums exist. The sidebar scrolls vertically because it needs ~980px of height on short laptop screens.
- **Aspect presets**: the render panel's **Aspect** combo applies canonical canvases from `constants.ASPECT_PRESETS` (9:16 1080×1920, 4:5 1080×1350, 1:1 1080×1080, 16:9 1920×1080). `_preview_size()` fits the configured canvas into a 360×640 box so non-vertical templates preview correctly, and the batch preview derives its aspect from the canvas instead of a hard-coded 16:9.

### 7.2 Playback Engine, Live Audio & Reverse Buffer
To maintain smooth 60fps playback with full sound synchronization:
- Driven by a 16ms `QTimer` (`_play_tick`).
- **Synchronized Live Audio**: Powered by dual `QMediaPlayer` + `QAudioOutput` instances (`_game_audio_player` for in-game recording audio and `_bgm_audio_player` for background music). Audio position and playback rate lock strictly to `playhead` and `_play_speed` on play, pause, seek, and loop. Shuttling backward automatically pauses audio.
- **Selective Redraw Optimization**: On playback ticks, **only** the background pixmap and video layer pixmaps are updated via `_update_frame_layers()`. Scene items, grip handles, text layers, and image layers are never destroyed or rebuilt during playback.
- **Shuttle Forward (`L`)**: Supports $1\times$, $2\times$, and $4\times$ playback via real-time clock pacing (`_read_backlog`).
- **Shuttle Reverse (`J`)**: Uses `_load_reverse_batch()` to decode small batches (~0.25s of footage) into `_reverse_buffer`, allowing rapid backward playback without seeking on every single frame.

### 7.3 Audio & Music Studio (`AudioStudioDialog` in `audio_dialog.py`)
- Dedicated modal studio for sound management, keeping the main sidepanel uncluttered.
- **Music Trimming / Cutting**: Visual scrubber timeline with start (IN) and end (OUT) offset spinboxes to start music at specific points (e.g. beat drops) before looping.
- **Audition Mode**: Dedicated play/pause audition player allows testing music cuts and volume balance directly in the dialog before applying.
- **Volume & FX**: Independent sliders for BGM Volume and Gameplay Audio, Auto-Ducking toggle, and smooth boundary Fade In/Out controls.

### 7.4 AI Auto-Captions Studio (`CaptionStudioDialog` in `caption_dialog.py`)
- Dedicated modal studio for local Whisper speech-to-text generation and animated subtitle styling.
- **Background Worker**: `TranscriptionWorker` (`QThread`) executes speech recognition in the background with live progress updates.
- **Transcript Editor**: In-place editable table for quick corrections of terms or gamer tags.
- **Visual Styler**: Live controls for Neon Yellow, Green, Cyan, Coral highlight colors, font size, stroke thickness, uppercase toggle, and safe-zone presets.
- **Export Formats**: One-click export to `.SRT` or `.ASS`.

### 7.4 Undo / Redo Transactional Model
- Manages an in-memory history of up to 100 deep-copied configuration snapshots.
- **Continuous Input Debouncing**: Continuous interactions (dragging sliders, moving canvas layers) start an interaction via `_pending_undo` and commit via an 800ms `QTimer` debounce or upon `mouseReleaseEvent`. This ensures single undo steps rather than dozens of micro-steps.

### 7.4 Batch Studio (`BatchWindow` & `BatchRenderWorker`)
- Multi-clip queue interface managing `BatchJob` dataclasses.
- Custom `TrimTimeline` widget: Self-painting Qt widget displaying IN/OUT flags, duration brackets, and draggable playhead.
- **Live 9:16 Preview**: Composited on the fly using OpenCV and pre-cached PIL assets. It honours static layer opacity **and per-layer fades** through `_layer_fade_factor()` (background fades to black by scaling pixels; overlaid layers fade via painter opacity), so the preview matches the exported file.
- **No cut support yet**: batch jobs carry only `in_time`/`out_time`. `run_render` accepts `cuts`, but the batch UI does not expose the Split & Cut studio.
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
- **`LayerStackWidget`**: Reorders layers via drag-and-drop or Forward/Backward buttons. Toggles visibility with vector eye icons. Displays type badges: `[VID]`, `[TXT]`, `[IMG]`. The list sizes itself to the stack — 26px rows, minimum 3 and maximum 8 visible rows (`ROW_HEIGHT`/`MIN_ROWS`/`MAX_ROWS`) — so layers never collapse into a two-row box, and taller stacks scroll.
- **`LayerInspectorWidget`**: Dynamic property inspector. Automatically toggles between Typography controls (for text layers), Asset Pickers (for image layers), and Crop Spinboxes (for video layers). The **Fade in / out** group holds the per-layer checkbox plus in/out durations (default 0.5s) and an **Apply to all** button that copies those settings to every layer.

### 7.8 Split & Cut Studio (`split_dialog.py`)
- Opened from the **Split & Cut…** button under the transport panel. It is the only way to remove footage from the *middle* of a clip; IN/OUT alone can only describe one contiguous range.
- **`SplitTimeline`** (custom-painted `QWidget`): shows the whole recording with kept segments in navy, removed segments in red with a dashed "CUT" border, split marks as dashed vertical lines, draggable IN (green) / OUT (red) handles, and the playhead. Mouse press selects the segment under the cursor, which is what **Delete segment** acts on.
- **Model**: `boundaries` (split points) + `removed` (removed ranges). `segments()` is derived, so IN/OUT and split points always stay consistent. `toggle_removed()` marks or restores one segment.
- **Result**: `result_data()` returns `{"in", "out", "cuts", "duration"}`; the main window stores `cuts` in `self._cut_regions` and hands them to the renderer.
- **Preview**: decodes frames with OpenCV (`CAP_PROP_POS_FRAMES`), with a 55 ms debounce so dragging the playhead stays responsive; playback hops over removed regions.
- **Keyboard**: `Space` play/pause, `←`/`→` step a frame, `S` split at playhead, `Del`/`Backspace` delete selected segment, `I`/`O` set IN/OUT.
- Painting detail: `QPainter.drawRect()` fills with the *current brush*. Always set `Qt.BrushStyle.NoBrush` before outline-only draws, otherwise a leftover brush floods neighbouring rectangles.
- **Auto-cut silences**: the **Auto-cut silences…** button runs `clipcraft.silence.detect_silence()` on a `SilenceScanWorker` thread over the IN/OUT range (`silencedetect=noise=-35dB:d=0.35`), shrinks each region by 0.08 s so quiet speech tails survive, and opens this dialog **pre-filled** with the results. Nothing changes until the user accepts.

### 7.9 Projects, Autosave & Portable Templates
- **Project lifecycle**: `_on_video_probed()` calls `_restore_project_for_video()`, which applies the sidecar beside the recording. Trim/cut/audio/caption edits call `_mark_project_dirty()`, debouncing an atomic write after 1.2 s; `closeEvent` flushes pending changes.
- **Restore guard**: `_apply_project()` runs with `_suppress_project_autosave = True` so restoring cannot immediately re-save (or fight with the file it just read).
- **Project menu**: *Recent ▾ → Project* offers Save project as…, Open project…, Save now, Delete saved project and a Recent projects submenu (state key `recent_projects`).
- **Portable templates**: **Save as new template…** calls `clipcraft.template_bundle.bundle_template()`, which deep-copies the config, copies every image layer into `templates/assets/<id>/` (one copy per distinct source), rewrites `asset` to a forward-slash relative path, assigns a unique id (`same_name`, `same_name_2`, …) and saves with `save_config()`. Missing images are reported and left pointing at their original path. This is what makes a template survive the portable build or a shared ZIP — absolute `D:/...` paths otherwise work on exactly one machine.

### 7.10 Animation Studio (`anim_dialog.py`)
- Opened from the inspector's small **Animate…** button; entirely optional and modal, so the editor stays uncluttered.
- **`AnimTimeline`**: keyframe strip with diamond markers. Click empty space to scrub, click a diamond to select it; the playhead can be dragged.
- **Controls**: centre X/Y spin boxes, **Set key**, **Delete key**, **Clear all**, Play/Pause, and presets (Slide in from left, Slide out to right, Drift up). Apply preset writes two keys relative to the clip duration.
- **Preview**: composites the whole layout at ~270px wide using `render_background` + `layer_preview_image`, applying the dialog's in-progress keys to the selected layer and every other layer's own keys.
- **Time mapping**: the dialog works in edited-timeline seconds; `timeline_to_source(in, out, cuts)` maps the playhead to the decoded source frame.
- **Apply** writes `layer["anim"]["keys"]` (or removes `anim` entirely when cleared) as a single undo step.

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
- `build_cut_filter(start, end, cuts, has_audio) -> tuple[str, str, str]`: Trim/concat prelude; returns `(chains, video_label, audio_label)`.
- `build_layer_fade_filter(layer, duration, *, alpha=True) -> str`: Per-layer fade chain (`alpha=False` for the background, which fades to black instead of revealing).
- `build_filter_complex(config, config_path, video_info, source_v="0:v", duration=None) -> tuple[str, list[Path]]`: Compiles FFmpeg filter string.
- `build_audio_filter_graph(video_info, duration, audio_config, bgm_input_index, source_a="0:a") -> tuple[str, bool]`: Mixes/ducks/fades audio from an arbitrary source label.
- `build_ffmpeg_command(..., audio_config=None, cuts=None) -> tuple[list[str], float]`: Assembles the CLI command; the returned duration is the kept length.
- `run_render(..., audio_config=None, cuts=None) -> Path`: Executes subprocess, streams progress, falls back to CPU on NVENC failure.

### Module: `clipcraft.segments`
- `normalize_cuts(cuts, duration=None) -> list[Cut]`: Clamp, sort, merge and drop zero-length cut regions.
- `kept_spans(start, end, cuts) -> list[Cut]`: Footage inside IN/OUT that is not cut away.
- `timeline_duration(start, end, cuts) -> float`: Length of the result (`end - start` minus cuts).
- `source_to_timeline(t, start, end, cuts) -> float` / `timeline_to_source(offset, ...) -> float`: Scrubber mapping between edited and source time.
- `cut_containing(t, cuts) -> Cut | None`, `next_kept_time`, `previous_kept_time`: Removed-region lookup and snapping.
- `step_time(t, delta, start, end, cuts) -> float`: Cut-aware frame stepping / shuttle advance.

### Module: `clipcraft.anim`
- `rect_center(rect) -> (x, y)`: Normalized centre of a layer rect.
- `normalize_keys(keys, duration=None) -> list[dict]`: Clamp/sort/de-duplicate keys; requires `t`, `x`, `y`.
- `keys_for_layer(layer, duration=None) -> list[dict]` / `has_animation(layer) -> bool`: Read a layer's keys.
- `sample(keys, t) -> (x, y) | None`: Linear interpolation, clamped at both ends.
- `center_for_layer(layer, t, duration=None) -> (x, y)`: Animated centre with static-rect fallback.
- `piecewise_expression(points, variable="t") -> str`: FFmpeg expression compiler.
- `overlay_expressions(layer, canvas_w, canvas_h, duration=None) -> (x, y) | None`: Overlay corner expressions, or None when static.

### Module: `clipcraft.project`
- `project_path_for(video) -> Path`: Sidecar location (`<stem>.clipcraft`).
- `build_project(video, template_id, in, out, cuts, audio, captions, playhead, template_path) -> dict`: Assemble the payload.
- `normalize_project(data) -> dict`: Validate/clamp/migrate; raises `ValueError` for unusable or newer-version files.
- `save_project(path, project) -> Path` / `load_project(path) -> dict`: Atomic write / validated read.
- `push_recent_project(existing, path) -> list[str]`: Recent list helper (capped at 10).

### Module: `clipcraft.silence`
- `parse_silencedetect(stderr, start_offset=0.0, total=None) -> list[Cut]`: Parse FFmpeg log lines into absolute regions.
- `detect_silence(video, start, end, noise_db=-35, min_silence=0.35, padding=0.08) -> list[Cut]`: Run `silencedetect` over the range.
- `total_cut_time(regions) -> float`: Sum of removed time.

### Module: `clipcraft.template_bundle`
- `slugify(name) -> str`: Filesystem-safe template id.
- `bundle_template(config, config_path, name, templates_dir=None, target_id=None) -> BundleResult`: Copy images to `templates/assets/<id>/`, rewrite paths, save the new template. Overwrites `target_id` when explicitly specified.

### Module: `clipcraft.captions`
- `CaptionWord`: Dataclass storing word string, start timestamp, end timestamp, and probability.
- `CaptionCue`: Dataclass storing cue start, end, text, and constituent words.
- `CaptionStyle`: Dataclass configuring font, colors, stroke, vertical position, uppercase, and karaoke highlight.
- `extract_audio_for_transcription(video_path, start, end, out_wav) -> Path`: Extracts 16kHz mono WAV for Whisper.
- `group_words_into_cues(words, max_words, max_duration, pause_threshold) -> list[CaptionCue]`: Groups words into punchy 2–4 word phrases.
- `transcribe_video_audio(video_path, start, end, model_size, language, callback) -> tuple[list[CaptionCue], str]`: Executes local `faster-whisper` transcription.
- `export_to_ass(cues, output_path, style, canvas_w, canvas_h) -> Path`: Compiles ASS subtitle file with active-word color tags.
- `export_to_srt(cues, output_path, uppercase) -> Path`: Exports standard SRT subtitle file.

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
- `AudioStudioDialog`: Dedicated sound, music trimming, volume, and ducking studio.
- `CaptionStudioDialog`: Local Whisper transcription and karaoke caption styling studio.
- `SplitEditorDialog` / `SplitTimeline`: Split, delete and restore middle segments, then re-pick IN/OUT.
- `AnimationDialog` / `AnimTimeline`: Position-keyframe studio for one layer.
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
| **`F11`** | Main | Toggle borderless fullscreen |
| **`Esc`** | Main (fullscreen) | Leave fullscreen, back to the maximised layout |
| **`S`** | Split & Cut | Split the clip at the playhead |
| **`Delete` / `Backspace`** | Split & Cut | Remove (or restore) the selected segment |
| **`I` / `O`** | Split & Cut | Set IN / OUT at the playhead |
| **`Space` / `←` / `→`** | Split & Cut | Play-pause / step one frame |
| **`Delete`** | Batch | Remove selected clip from queue |

---

## 10. Testing Suite & Quality Verification

Run the entire automated test suite:
```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Test Coverage Summary:
- `tests/test_cli.py`: Verifies time parsing (seconds, MM:SS, HH:MM:SS), `--cut` range parsing, argument parsing, default output naming.
- `tests/test_gui_smoke.py`: Headless Qt tests verifying widget instantiation, transport states, layer selection, dialogs, split timeline model and painting.
- `tests/test_segments.py`: Cut normalization, kept spans, timeline mapping and cut-aware stepping (including exact-boundary steps).
- `tests/test_render_cuts.py`: Trim/concat graph structure plus a frame-exact end-to-end render that decodes grey-coded frames to prove the removed ones are gone.
- `tests/test_fades.py`: Fade-chain unit tests (defaults, clamping, background colour fade) plus renders that measure the darkened first/last frames and the alpha ramp of an overlaid image.
- `tests/test_anim.py`: Key normalization/sampling, expression compilation, animated-graph structure, and an end-to-end render that measures the layer moving from x≈18px to x≈162px.
- `tests/test_project.py`: Sidecar round-trip, atomic write, trim repair, version guard, corrupt JSON, recent list.
- `tests/test_project_gui.py`: Autosave writes + restore, corrupt sidecar resilience, dirty marking, detected cuts reaching the split dialog, template save-as bundling, deleting a sidecar.
- `tests/test_silence.py`: `silencedetect` parsing (offsets, unclosed silence), padding shrink, and an end-to-end tone/silence scan.
- `tests/test_template_bundle.py`: Image copying, relative path rewrite, id collisions, shared-image de-duplication, missing assets.
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
7. **Cuts Are Pairs of Trims**: A cut region must be removed from **both** video and audio in the same filter graph (`trim`/`setpts` and `atrim`/`asetpts`), and the exported duration must be `timeline_duration()`, never `out - in`. Any new feature that seeks the source (playback, scrubbing, stepping, thumbnails) must go through `clipcraft.segments` so removed regions are skipped consistently.
8. **No Hidden Removed Footage**: `_play_tick`, `_reverse_tick`, `step_frames` and the scrubber must never rest inside a cut. If you add a new seek path, route it through `next_kept_time`/`previous_kept_time`/`step_time`.
9. **Fades Are Alpha Ramps**: Per-layer fades must stay on the *edited* timeline (fade-out ends on the last exported frame, cuts do not stretch them). Overlaid layers fade their alpha over whatever is underneath; the background fades colour to black because its alpha is discarded by `format=yuv420p`. The preview applies the identical ramp through `_layer_fade_factor()` — do not bake opacity into `layer_preview_image()`, or fades will double-apply.
10. **Autosave Must Not Fight Restore**: Anything that writes the project sidecar must respect `_suppress_project_autosave`; `_apply_project()` sets it while restoring. A corrupt or newer sidecar must never prevent a recording from opening.
11. **Templates Must Be Portable**: A template shipped or shared must not depend on absolute machine paths. Use `Save as new template…` (`bundle_template`) so images live in `templates/assets/<id>/` and `layer["asset"]` stays a relative POSIX path.
12. **Animation Lives on the Edited Timeline**: Keyframe times are exported-seconds, sampled by `anim.sample()` for the preview and compiled by `anim.piecewise_expression()` for FFmpeg. Both must use the same keys and clamping; changing a layer's static rect must not shift its animated centre (keys store the centre, not the top-left).

---

## 12. Standalone Portable Windows Build & Setup Installer

ClipCraft provides an automated compilation pipeline producing both a 100% self-contained portable distribution archive and a standard Windows Setup Wizard:

### 12.1 Build Targets
1. **Windows Setup Wizard (`dist/ClipCraft_Setup_v0.1.0.exe`)**:
   - Built with Inno Setup (`installer.iss`).
   - Supports per-user installation (`%LOCALAPPDATA%\Programs\ClipCraft`, no admin rights/UAC needed) or machine-wide (`Program Files`).
   - Creates Windows Start Menu shortcuts and optional Desktop icon.
   - Registers a clean uninstaller in Windows Settings (*Installed apps* / *Add or remove programs*).
   - "Launch ClipCraft" checkbox upon completion.
2. **Portable Edition (`dist/ClipCraft_v0.1.0_Windows_Portable.zip`)**:
   - Zero-install folder and ZIP archive. Run anywhere without elevation.
   - Contains `ClipCraft.exe`, bundled `ffmpeg.exe`, `ffprobe.exe`, `templates/`, and local state.

### 12.2 Build Pipeline (`build_portable.py` / `build_portable.bat`)
- Compiles `clipcraft.py` into `dist/ClipCraft/ClipCraft.exe` with `console=False` (no flashing terminal window).
- Bundles vector fonts (`qtawesome`), AI subtitle assets (`ctranslate2`, `faster_whisper`), and PySide6 plugins.
- Automatically copies `ffmpeg.exe` and `ffprobe.exe` directly into `dist/ClipCraft/`, making the application fully self-sufficient on machines without FFmpeg on `PATH`.
- Copies all shipping game layout templates (`templates/*.json`) into `dist/ClipCraft/templates/`.
- Initializes `clipcraft_state.json` in portable mode and writes user instructions to `dist/ClipCraft/README.txt`.
- Generates `dist/ClipCraft_v0.1.0_Windows_Portable.zip` ready for one-click creator distribution.
- Automatically compiles `dist/ClipCraft_Setup_v0.1.0.exe` if Inno Setup (`ISCC.exe`) is detected.

### 12.3 GitHub Actions Automated Releases (`.github/workflows/release.yml`)
- Triggers on tag pushes (`v*`).
- Sets up Python 3.11, FFmpeg, and Inno Setup (`choco install innosetup`).
- Runs the complete automated test suite (`pytest`).
- Executes `build_portable.py` to compile both the portable ZIP and the setup wizard executable.
- Publishes a GitHub Release with `ClipCraft_Setup_*.exe`, `ClipCraft_*_Portable.zip`, and `ClipCraft.exe`.

### Running the Build Locally:
```powershell
.\.venv\Scripts\python.exe build_portable.py
```
Or double-click `build_portable.bat` in Windows Explorer.

