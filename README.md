# ClipCraft ⚡
### Turn 16:9 Gameplay Recordings into Viral 9:16 Vertical Shorts in Seconds.

![Platform](https://img.shields.io/badge/Platform-Windows-blue?style=flat-square&logo=windows)
![Format](https://img.shields.io/badge/Output-9%3A16%20Shorts%20%2F%20TikTok%20%2F%20Reels-ff0050?style=flat-square)
![GPU Acceleration](https://img.shields.io/badge/Render-Hardware%20Accelerated-76b900?style=flat-square&logo=nvidia)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

**ClipCraft** is a high-speed, creator-first video editor built specifically for gamers and streamers. Instead of spending 30 minutes keyframing and cropping inside complex editing suites like Premiere Pro or DaVinci Resolve, ClipCraft turns raw horizontal gameplay into high-impact, multi-layer vertical videos with a few clicks.

Drop your recording, pick your moments, align your layout, and export crisp 60fps shorts ready for **YouTube Shorts**, **TikTok**, and **Instagram Reels**.

---

## 📦 Downloads & Installation

### Option 1: Standard Windows Setup Wizard (Recommended)
Download **`ClipCraft_Setup_v0.1.0.exe`** from [Latest Releases](https://github.com/hariharen9/ClipCraft/releases/latest).
- Standard Windows setup wizard with Start Menu shortcuts and optional Desktop icon.
- Can be installed for the current user without administrator privileges or system-wide.
- Includes full clean uninstaller registered in Windows Settings (*Installed apps*).
- Bundles complete standalone engine including FFmpeg and local AI Whisper captions.

### Option 2: Standalone Portable Edition (Zero Installation)
Download **`ClipCraft_v0.1.0_Windows_Portable.zip`** from [Latest Releases](https://github.com/hariharen9/ClipCraft/releases/latest).
- Extract anywhere (e.g., secondary SSD, USB drive) and run **`ClipCraft.exe`**.
- Fully portable: configurations and presets are kept inside the application directory.
- No Python, terminal, or system dependencies needed!

### Option 3: Developer Setup (From Source)
```bash
git clone https://github.com/hariharen9/ClipCraft.git
cd ClipCraft
install.bat
run_gui.bat
```

---

## ✨ Why Creators Love ClipCraft

* **Instant Multi-Layer Magic**: Automatically splits single 16:9 footage into an immersive blurred background, a focused center gameplay feed, and dedicated crops for your facecam, killfeed, or chat.
* **Real-Time Visual Cropping**: No guesswork. Frame your killfeed or facecam by simply dragging an interactive box directly over the uncropped source recording.
* **Instant Keyboard Trimming**: Edit at the speed of thought with classic NLE shuttle hotkeys (`J` `K` `L`, `Space`, `I` / `O`).
* **Built-in Styled Text Overlays**: Add catchy captions, hook titles, or social handles directly inside the editor—complete with bold fonts, color pickers, and outline strokes.
* **Multi-Game Templates**: Seamlessly switch layouts between **Valorant**, **Rainbow Six Siege**, **Counter-Strike 2**, **Apex Legends**, **Call of Duty / Warzone**, **Fortnite**, **League of Legends**, **General Facecam**, and **Clean Gameplay**, or customize and save your own.
* **Smart Audio & BGM Engine**: Drag & drop any `.mp3` or `.wav` track. Automatically ducks background music when voice callouts or gunshots peak, plus smooth 0.5s fades at clip start and end.
* **Split & Cut Anywhere**: One IN/OUT pair is not always enough. Open the **Split & Cut** studio to split a recording at any point, delete dead time, queue wipes, or silent stretches from the middle, and keep the rest — playback and export skip straight over the removed parts.
* **Mobile Safe-Zone Guides**: One-click overlay ensures your titles and action never get obscured by TikTok or YouTube Shorts buttons and captions.
* **Zero Waiting (Batch Studio)**: Queue up an entire session's worth of highlights and render them sequentially in the background while you grab a coffee.

---

## 🚀 Quick Start Guide

Getting started takes less than two minutes:

### 1. Setup
Double-click **`install.bat`** in the project folder. It installs the Python environment and verifies or installs **FFmpeg** via winget automatically. (If you don't have winget, ensure `ffmpeg` and `ffprobe` are installed on your system `PATH`).

### 2. Launch
Double-click **`run_gui.bat`** to open the main studio editor.

---

## 🎬 The 4-Step Creator Workflow

```
 1. DROP FOOTAGE  ──►  2. TRIM THE MOMENT  ──►  3. TWEAK LAYOUT  ──►  4. EXPORT
 Drag video in         Scrub & press I / O      Adjust crops/text        Click Render
```

1. **Drop Your Footage**: Drag any recording (`.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`) straight onto the editor, or choose from your **Recent Files** list.
2. **Trim the Action**: Scrub the timeline to your play, tap **`I`** to set your start point, tap **`O`** for your end point, and preview playback with **`Space`**.
3. **Customize Your Look**: 
   - Switch game templates instantly with the **Template** selector.
   - Click **📐 Crop visually…** to frame facecams or HUD elements.
   - Click **＋ Text** to drop in high-contrast meme titles or creator watermarks.
4. **Export**: Click **Render Shorts**. Your video is hardware-encoded at smooth 60fps, and a completion prompt lets you jump straight to the file or play it immediately.

---

## 🌟 Standout Features

### 📐 Interactive Visual Source Crop
Forget entering manual pixel numbers. Opening the visual cropper displays the full widescreen source frame. Simply drag and scale the crop box over what matters—your facecam, minimap, inventory, or killfeed—and watch your 9:16 canvas update simultaneously.

### ✂️ Split & Cut Studio
Need a moment that starts at 0:10 but has a 6-second pause at 0:22? Trim the boring middle out instead of settling for one contiguous range.
- **Split anywhere**: drop cut points on the timeline and the clip becomes selectable segments.
- **Delete / restore**: remove a segment from the middle and it turns into a red "CUT" block; restore it any time before you export.
- **IN / OUT on what is left**: drag the green/red handles (or press `I` / `O`) around the footage you actually want.
- **True preview**: the main scrubber, frame stepping, shuttle playback and the render itself all skip the removed regions, so what you preview is what you export.
- **Headless parity**: `--cut 22-28` on the command line removes the same region for scripted batches.

### 🎨 Layer Stack & Direct Text Engine
- **Visual Layer Hierarchy**: Drag and drop layers to bring elements forward or send them backward, with quick one-click eye toggles.
- **Native Text Studio**: Create bold titles and watermarks on the fly without launching Photoshop. Customize font family (*Impact*, *Arial*, *Segoe UI*, etc.), font size, bold weight, fill color, outline stroke color, stroke thickness, and text alignment.

### 🎵 Viral Audio & Background Music Engine
- **Drag & Drop Music**: Simply drop any `.mp3`, `.wav`, or `.m4a` file directly onto the editor. ClipCraft loops and synchronizes it across your trimmed clip.
- **Sidechain Auto-Ducking**: Automatically lowers the music track whenever in-game voice chat, discord callouts, or gunshot peaks occur, ensuring speech remains crystal clear.
- **Independent Volume Control**: Set individual level sliders for background music (default 35%) and gameplay footage (default 100%).
- **Smooth Audio Fades**: Automatic 0.5s fade-in at clip start and fade-out at clip end to prevent abrupt audio popping.

### 🛡️ Mobile Safe-Zone Overlays
Never lose your clutch play behind a TikTok "Like" button or a YouTube Shorts caption. Toggle **Safe zones** to visualize standard mobile UI dead-zones directly over your preview in real-time.

### 🏷️ Smart Auto-Naming & Output Tokens
ClipCraft automatically generates organized export filenames using dynamic tokens:
- `{clip}` — Source recording title
- `{game}` — Active game template
- `{in}` & `{out}` — Exact trim points (e.g., `12s-35s`)
- `{dur}` — Total short duration
- `{date}` & `{time}` — Timestamp stamps

---

## ⚡ Multi-Clip Batch Render Studio

Have 10 clutch clips from last night's stream? Don't export them one by one.

Double-click **`run_batch.bat`** to launch the **Batch Studio**:
1. Drop your entire clips folder into the queue.
2. Click through each clip to scrub and set its IN and OUT marks with live 9:16 layout previews.
3. Select your export template and hit **Start Batch Render**.
4. Sit back while ClipCraft renders every short sequentially with dual progress bars.

---

## ⌨️ Pro Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **`Space`** | Play / Pause playback |
| **`I`** | Set clip **IN** point at current playhead |
| **`O`** | Set clip **OUT** point at current playhead |
| **`J`** | Shuttle backward (tap repeatedly for 2×, 4× speed) |
| **`K`** | Pause shuttling / playback |
| **`L`** | Shuttle forward (tap repeatedly for 2×, 4× speed) |
| **`←` / `→`** | Step exactly 1 frame backward / forward |
| **`Shift + ←` / `→`** | Jump 1 second backward / forward |
| **`Ctrl + Z`** | Undo last layout, move, or crop change |
| **`Ctrl + Shift + Z`** | Redo last undone change |

---

## ⚙️ Hardware Acceleration

ClipCraft includes intelligent auto-switching render profiles:
* **GPU (NVIDIA NVENC)**: Lightning-fast hardware rendering optimized for modern NVIDIA graphics cards.
* **CPU (x264)**: Universal, pristine software encoding that works on any modern Windows PC.
* **Fast Draft Mode**: Quick export preset to check timing and audio before rendering full 60fps final masters.

---

<div align="center">
  <b>Built for gamers who want to spend more time playing and less time editing.</b>
</div>
