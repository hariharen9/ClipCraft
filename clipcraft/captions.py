"""ClipCraft AI Auto-Captions Engine — Local speech-to-text with word-by-word animation.

Powered by faster-whisper. Extracts audio, transcribes with word-level timestamps,
groups words into high-retention short phrases (TikTok / Shorts safe zone),
and generates styled ASS subtitle streams with karaoke active-word highlighting.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from .renderer import find_ffmpeg


@dataclass
class CaptionWord:
    """Individual word with precise start and end timestamps."""
    word: str
    start: float  # seconds
    end: float    # seconds
    probability: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptionWord:
        return cls(
            word=str(data.get("word", "")),
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            probability=float(data.get("probability", 1.0)),
        )


@dataclass
class CaptionCue:
    """A bite-sized subtitle cue consisting of a small group of words (2-5 words)."""
    start: float  # seconds
    end: float    # seconds
    text: str
    words: list[CaptionWord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptionCue:
        words = [CaptionWord.from_dict(w) for w in data.get("words", [])]
        return cls(
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            text=str(data.get("text", "")),
            words=words,
        )


@dataclass
class CaptionStyle:
    """Visual typography and animation styling for viral short-form captions."""
    font_family: str = "Impact"
    font_size: int = 56           # scaled to 1080x1920
    primary_color: str = "#FFFFFF" # White for base words
    highlight_color: str = "#FFE600" # Neon Yellow for currently spoken word
    stroke_color: str = "#000000"  # Solid black outline
    stroke_width: int = 8          # Thick outline for readability
    position_y: float = 0.70       # 70% from top (TikTok/Shorts safe zone)
    uppercase: bool = True         # Punchy all-caps
    word_highlight: bool = True    # Word-by-word karaoke highlight
    max_words_per_cue: int = 4     # Bite-sized phrase length

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CaptionStyle:
        if not data:
            return cls()
        return cls(
            font_family=str(data.get("font_family", "Impact")),
            font_size=int(data.get("font_size", 56)),
            primary_color=str(data.get("primary_color", "#FFFFFF")),
            highlight_color=str(data.get("highlight_color", "#FFE600")),
            stroke_color=str(data.get("stroke_color", "#000000")),
            stroke_width=int(data.get("stroke_width", 8)),
            position_y=float(data.get("position_y", 0.70)),
            uppercase=bool(data.get("uppercase", True)),
            word_highlight=bool(data.get("word_highlight", True)),
            max_words_per_cue=int(data.get("max_words_per_cue", 4)),
        )


def hex_to_ass_bgr(hex_color: str) -> str:
    """Converts a standard #RRGGBB hex string into ASS &H00BBGGRR& color format."""
    s = hex_color.strip().lstrip("#")
    if len(s) == 6:
        r, g, b = s[0:2], s[2:4], s[4:6]
        return f"&H00{b}{g}{r}&".upper()
    return "&H00FFFFFF&"


def format_ass_timestamp(seconds: float) -> str:
    """Formats seconds into ASS timestamp format: H:MM:SS.cs (centiseconds)."""
    seconds = max(0.0, seconds)
    total_cs = int(math.floor(seconds * 100.0 + 0.5))
    hours = total_cs // 360000
    rem = total_cs % 360000
    mins = rem // 6000
    rem = rem % 6000
    secs = rem // 100
    cs = rem % 100
    return f"{hours}:{mins:02d}:{secs:02d}.{cs:02d}"


def format_srt_timestamp(seconds: float) -> str:
    """Formats seconds into standard SRT timestamp format: HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3600000
    rem = total_ms % 3600000
    mins = rem // 60000
    rem = rem % 60000
    secs = rem // 1000
    ms = rem % 1000
    return f"{hours:02d}:{mins:02d}:{secs:02d},{ms:03d}"


# =====================================================================
#  AUDIO EXTRACTION & TRANSCRIPTION
# =====================================================================

def extract_audio_for_transcription(
    video_path: str | Path,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    output_wav: str | Path | None = None,
) -> Path:
    """Extracts 16kHz mono audio from a video segment via FFmpeg for Whisper STT."""
    video_path = Path(video_path).resolve()
    ffmpeg_bin = find_ffmpeg()

    if output_wav is None:
        temp_f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_f.close()
        out_path = Path(temp_f.name)
    else:
        out_path = Path(output_wav).resolve()

    cmd = [ffmpeg_bin, "-y"]
    if start_sec > 0.0:
        cmd.extend(["-ss", f"{start_sec:.3f}"])
    if end_sec is not None and end_sec > start_sec:
        dur = end_sec - start_sec
        cmd.extend(["-t", f"{dur:.3f}"])

    cmd.extend([
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(out_path),
    ])

    startupinfo = None
    if subprocess.os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg audio extraction failed: {err[-300:]}")

    return out_path


def group_words_into_cues(
    words: list[CaptionWord],
    max_words: int = 4,
    max_duration: float = 2.2,
    pause_threshold: float = 0.35,
) -> list[CaptionCue]:
    """Groups a flat list of timestamped words into bite-sized high-retention caption cues."""
    if not words:
        return []

    cues: list[CaptionCue] = []
    current_words: list[CaptionWord] = []

    for i, w in enumerate(words):
        if not current_words:
            current_words.append(w)
            continue

        prev = current_words[-1]
        cue_dur = w.end - current_words[0].start
        pause = w.start - prev.end

        should_split = (
            len(current_words) >= max_words
            or cue_dur >= max_duration
            or pause >= pause_threshold
            or prev.word.rstrip().endswith((".", "!", "?"))
        )

        if should_split:
            cue_text = " ".join(cw.word.strip() for cw in current_words)
            cues.append(
                CaptionCue(
                    start=current_words[0].start,
                    end=current_words[-1].end,
                    text=cue_text,
                    words=list(current_words),
                )
            )
            current_words = [w]
        else:
            current_words.append(w)

    if current_words:
        cue_text = " ".join(cw.word.strip() for cw in current_words)
        cues.append(
            CaptionCue(
                start=current_words[0].start,
                end=current_words[-1].end,
                text=cue_text,
                words=list(current_words),
            )
        )

    return cues


def transcribe_video_audio(
    video_path: str | Path,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    model_size: str = "base",
    language: str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    max_words_per_cue: int = 4,
) -> tuple[list[CaptionCue], str]:
    """Transcribes audio using local faster-whisper and returns timed caption cues."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper package is not installed. Run: pip install faster-whisper") from exc

    if progress_callback:
        progress_callback(0.1, "Extracting audio from clip…")

    wav_path = extract_audio_for_transcription(video_path, start_sec, end_sec)

    try:
        if progress_callback:
            progress_callback(0.25, f"Loading Whisper model ({model_size})…")

        # Determine best available compute device
        device = "cpu"
        compute_type = "int8"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                device = "cuda"
                compute_type = "float16"
        except Exception:
            pass

        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        if progress_callback:
            progress_callback(0.45, "Transcribing speech and extracting word timestamps…")

        segments, info = model.transcribe(
            str(wav_path),
            word_timestamps=True,
            vad_filter=True,
            language=language,
        )

        detected_lang = info.language if hasattr(info, "language") else "en"
        raw_words: list[CaptionWord] = []

        for seg in segments:
            if seg.words:
                for w in seg.words:
                    word_clean = w.word.strip()
                    if word_clean:
                        # Offset timestamps relative to video master timeline
                        w_start = start_sec + float(w.start)
                        w_end = start_sec + float(w.end)
                        prob = float(w.probability) if hasattr(w, "probability") else 1.0
                        raw_words.append(CaptionWord(word_clean, w_start, w_end, prob))

        if progress_callback:
            progress_callback(0.85, "Formatting bite-sized caption cues…")

        cues = group_words_into_cues(raw_words, max_words=max_words_per_cue)

        if progress_callback:
            progress_callback(1.0, f"Generated {len(cues)} caption cues ({len(raw_words)} words).")

        return cues, detected_lang

    finally:
        if wav_path.is_file():
            try:
                wav_path.unlink()
            except Exception:
                pass


# =====================================================================
#  ASS & SRT SUBTITLE GENERATION
# =====================================================================

def export_to_ass(
    cues: list[CaptionCue],
    output_path: str | Path,
    style: CaptionStyle | None = None,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> Path:
    """Generates an Advanced SubStation Alpha (.ass) subtitle file with word-by-word highlight tags."""
    style = style or CaptionStyle()
    out = Path(output_path).resolve()

    primary_bgr = hex_to_ass_bgr(style.primary_color)
    highlight_bgr = hex_to_ass_bgr(style.highlight_color)
    stroke_bgr = hex_to_ass_bgr(style.stroke_color)

    # Vertical safe-zone margin: ASS Alignment 2 is Bottom-Center.
    # MarginV specifies distance in pixels from the bottom edge of the canvas.
    # If position_y = 0.70 (70% down), MarginV = (1.0 - 0.70) * canvas_h = 30% from bottom.
    margin_v = max(40, int(round((1.0 - style.position_y) * canvas_h)))

    font_name = style.font_family
    font_size = style.font_size
    outline = style.stroke_width

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {canvas_w}
PlayResY: {canvas_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_bgr},&H00000000,{stroke_bgr},&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines: list[str] = []

    for cue in cues:
        if not cue.words:
            # Fallback if no individual words
            text = cue.text.upper() if style.uppercase else cue.text
            s_ts = format_ass_timestamp(cue.start)
            e_ts = format_ass_timestamp(cue.end)
            dialogue_lines.append(f"Dialogue: 0,{s_ts},{e_ts},Default,,0,0,0,,{text}")
            continue

        words = cue.words
        word_count = len(words)

        if not style.word_highlight or word_count == 1:
            # Single static cue without word coloring
            text = " ".join(w.word for w in words)
            if style.uppercase:
                text = text.upper()
            s_ts = format_ass_timestamp(cue.start)
            e_ts = format_ass_timestamp(cue.end)
            dialogue_lines.append(f"Dialogue: 0,{s_ts},{e_ts},Default,,0,0,0,,{text}")
        else:
            # Generate word-by-word highlight transitions
            for active_idx in range(word_count):
                active_w = words[active_idx]
                t_start = active_w.start
                t_end = active_w.end

                # Smooth boundary between words
                if active_idx == 0:
                    t_start = min(cue.start, active_w.start)
                if active_idx == word_count - 1:
                    t_end = max(cue.end, active_w.end)
                elif active_idx + 1 < word_count:
                    next_w = words[active_idx + 1]
                    if next_w.start > t_end:
                        t_end = next_w.start

                # Assemble styled words for this active step
                parts: list[str] = []
                for idx, w in enumerate(words):
                    w_text = w.word.upper() if style.uppercase else w.word
                    if idx == active_idx:
                        # Active highlighted word
                        parts.append(f"{{\\c{highlight_bgr}}}{w_text}{{\\c{primary_bgr}}}")
                    else:
                        parts.append(w_text)

                line_text = " ".join(parts)
                s_ts = format_ass_timestamp(t_start)
                e_ts = format_ass_timestamp(t_end)
                dialogue_lines.append(f"Dialogue: 0,{s_ts},{e_ts},Default,,0,0,0,,{line_text}")

    full_ass = header + "\n".join(dialogue_lines) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(full_ass, encoding="utf-8")
    return out


def export_to_srt(cues: list[CaptionCue], output_path: str | Path, uppercase: bool = True) -> Path:
    """Exports caption cues to a standard SubRip (.srt) subtitle file."""
    out = Path(output_path).resolve()
    lines: list[str] = []

    for i, cue in enumerate(cues, start=1):
        s_ts = format_srt_timestamp(cue.start)
        e_ts = format_srt_timestamp(cue.end)
        text = cue.text.upper() if uppercase else cue.text
        lines.append(f"{i}\n{s_ts} --> {e_ts}\n{text}\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
