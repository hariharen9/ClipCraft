# FastTrack — Gaming Shorts Editor

A small Windows-first editor for turning a gameplay recording into a 9:16 vertical short. The first profile is **Valorant**, based on the supplied BadPanda layout.

## What it creates

The same source recording is used for four moving-picture layers:

1. A full-frame, blurred and slightly darkened background.
2. The large central gameplay window.
3. A separate top-right killfeed crop.
4. A separate lower-left chat crop.

Transparent PNG layers add the Valorant title, YouTube/Instagram handles, and a panda channel mark. Every layer can be moved/resized independently. For the three video windows, its *output rectangle* and its *source crop* are both editable. Image layers are never stretched: they keep their original aspect ratio inside their rectangle.

Default output: **1080 × 1920, 60 fps, MP4/H.264**, with the source audio retained. Rendering uses NVIDIA NVENC on a supported NVIDIA driver / FFmpeg build; `auto` falls back to CPU x264 if NVENC fails.

## 1. Requirements (Windows)

- Windows 10/11.
- Python 3.11 recommended (Python 3.10+ should work).
- FFmpeg **and ffprobe** installed and available on `PATH`.
- For GPU rendering: a current NVIDIA driver and an FFmpeg build that includes `h264_nvenc`.

Check FFmpeg from PowerShell:

```powershell
ffmpeg -version
ffmpeg -hide_banner -encoders | findstr nvenc
ffprobe -version
```

You should see `h264_nvenc` in the encoder list for NVENC support. The actual NVIDIA driver/runtime is also checked when rendering. If it cannot initialize, use `--encoder cpu` or leave the default `auto` to let FastTrack retry with CPU encoding.

## 2. Install

Extract the folder, open it in Explorer, and double-click `install.bat`. Or run:

```powershell
cd path\to\fasttrack-video-editor
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, you can skip activation and use `.venv\Scripts\python.exe` directly.

## 3. Open the editor

Double-click `run_gui.bat`, or:

```powershell
python fasttrack.py --gui
```

Choose a recording with **Browse**. To open the editor with a clip already loaded:

```powershell
python fasttrack.py "D:\Clips\valorant_match.mp4" -g valorant --gui
```

Scrub the timeline to a moment you want, click **Set IN**, scrub to the end, then click **Set OUT**. You can also type precise timestamps in seconds. The editor preview updates as you scrub.

### Layout editing

- Choose a layer in the right-hand **Layer editor**.
- Drag the layer in the preview to reposition it.
- Drag its small cyan bottom-right handle to resize it.
- Use **Output position / size** to set its rectangle as percentages of the portrait canvas.
- For `main`, `killfeed` and `chat`, use **Source crop** to choose which part of the original 16:9 footage appears in that layer. Crop values are percentages of the original video frame.
- Toggle **Visible** to hide a layer.
- Click **Apply to preview** after changing numeric fields.
- Click **Save layout to config.json** to keep your changes as the Valorant default.

The preview is a composition preview at a smaller canvas size; the final render uses your selected output dimensions and FFmpeg filters.

## 4. CLI use

The simplest workflow opens the visual editor so you can pick IN/OUT and adjust the composition:

```powershell
python fasttrack.py "D:\Clips\match.mp4" -g valorant
```

Supplying both trim points renders directly without opening the GUI:

```powershell
python fasttrack.py "D:\Clips\match.mp4" -g valorant --in 00:01:12.5 --out 00:01:31 -o "D:\Clips\exports\ace.mp4"
```

Times can be seconds (`72.5`), `MM:SS` (`01:12.5`) or `HH:MM:SS.mmm`. Encoder choices:

```powershell
# Prefer NVENC, automatically retry CPU x264 if NVENC is unavailable (default)
python fasttrack.py "D:\Clips\match.mp4" -g valorant --in 72.5 --out 91 --encoder auto

# Force NVIDIA NVENC
python fasttrack.py "D:\Clips\match.mp4" -g valorant --in 72.5 --out 91 --encoder nvenc

# Force CPU x264
python fasttrack.py "D:\Clips\match.mp4" -g valorant --in 72.5 --out 91 --encoder cpu
```

Print the exact FFmpeg command without rendering:

```powershell
python fasttrack.py "D:\Clips\match.mp4" --in 72.5 --out 91 --print-command
```

The default output location is an `exports` folder beside the input recording.

## 5. Customize assets and branding

All template values live in **`config.json`**. Paths are relative to that file unless absolute paths are used.

### Branding

Edit these values and restart the editor:

```json
"branding": {
  "youtube_handle": "@youryoutube",
  "instagram_handle": "@yourinstagram",
  "channel_name": "YOUR CHANNEL"
}
```

FastTrack regenerates the three starter PNGs (`assets/valorant_title.png`, `assets/socials.png`, `assets/channel_logo.png`) at launch. To use your own art, change the matching `asset` path under the corresponding layer in `config.json`, for example:

```json
"channel_logo": {
  "kind": "image",
  "asset": "assets/my_channel_logo.png",
  "rect": [0.695, 0.785, 0.275, 0.19],
  "opacity": 1.0,
  "z": 60,
  "visible": true
}
```

Use transparent PNGs for clean overlays. Replace the title/social/logo paths with your own PNGs and keep the existing geometry as a starting point.

### Layer geometry

Every `rect` uses normalized `[x, y, width, height]` values from 0.0 to 1.0 relative to the output canvas. `[0, 0, 1, 1]` covers the complete canvas.

For video layers, `crop` is another normalized `[x, y, width, height]` rectangle in the original source frame. For example:

```json
"killfeed": {
  "kind": "video",
  "rect": [0.445, 0.162, 0.555, 0.085],
  "crop": [0.59, 0.018, 0.405, 0.20],
  "fit": "cover",
  "z": 20,
  "visible": true
}
```

If your recorded HUD position differs from the reference, adjust `crop` rather than moving the whole recording. Adjust `rect` to move or resize the rendered crop on the portrait canvas.

### Image layers keep their original shape

Image layers (`valorant_title`, `socials`, `channel_logo`, or any picture you import) are never stretched. FastTrack trims fully transparent borders first, then scales the visible content to the largest size that fits inside the layer `rect` while preserving the original aspect ratio, centered in that rectangle. Dragging the corner handle in the editor also keeps the aspect ratio locked, so pictures can only be resized proportionally.

If you specifically want a picture stretched to fill its whole rectangle, set `"fit": "fill"` on that image layer:

```json
"valorant_title": {
  "kind": "image",
  "asset": "assets/valorant_title.png",
  "fit": "fill",
  "rect": [0.128, 0.052, 0.803, 0.065]
}
```

`background.blur`, `background.brightness` and `background.saturation` control the blurred backdrop. The `canvas` section controls dimensions, FPS, encoder, quality and presets.

## 6. Current scope / practical notes

- This first build contains the Valorant template only; the `-g` flag is structured so more game templates can be added later.
- The preview is a frame-based composition editor, not a full multitrack NLE. It is designed for selecting a short segment and adjusting the reusable layout quickly.
- For the current template, the killfeed/chat source crop is a fixed rectangle. If the HUD moves during a recording (for example due to a different resolution or HUD scale), adjust the crop to match that recording before rendering.
- The main gameplay crop defaults to filling its center window. If you prefer to preserve the full 16:9 gameplay frame, widen the main window or change its `fit` value to `contain`.
- Rendering and preview are separate: dragging layers changes the layout, while source-crop field edits are applied with **Apply to preview**.

## Troubleshooting

**`FFmpeg was not found`** — install FFmpeg and add the folder containing `ffmpeg.exe` and `ffprobe.exe` to the Windows `PATH`, then reopen the terminal/editor.

**NVENC initialization error** — update the NVIDIA driver and use an FFmpeg build with NVENC. Set Encoder to `Auto` or choose `CPU / x264` in the GUI.

**GUI fails during install** — install dependencies with the same Python interpreter used to start FastTrack: `python -m pip install -r requirements.txt`.

**Preview shows black or cannot open a file** — try an H.264 MP4 recording. Some unusual codecs/containers can be rendered by FFmpeg but may not decode in the OpenCV preview backend.
