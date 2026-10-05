import json                       # json to parses ffprobe's output
import shutil                     # to check whether a program is exist on system/installed (i.e.,ffmpeg)
import subprocess                 # to run external commands (i.e., ffmpeg, ffprobe)
from pathlib import Path          # pathlib is object-oriented way to handle file paths

from .errors import AudioError    

ALLOWED = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma", ".mp4", ".webm", ".mkv"}
MAX_API_BYTES = 24 * 1024 * 1024  # Groq free tier upload cap is 25 MB , vary for other llm


# probe_duration asks ffprobe how long an audio file is and returns that number in seconds. It's a small helper used only by split_if_large, to measure each chunk after cutting.

def probe_duration(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True)
    try:
        return float(json.loads(probe.stdout or "{}").get("format", {}).get("duration") or 0)
    except (json.JSONDecodeError, ValueError):
        raise AudioError("Could not read the duration of an audio file.")
    

# validate_and_convert check the file is real audio, convert to 16 kHz mono mp3. Returns (path, duration_seconds),

def validate_and_convert(path, work_dir, min_seconds=2):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise AudioError("The uploaded file is empty or missing.")
    if p.suffix.lower() not in ALLOWED:
        raise AudioError(f"Unsupported file type '{p.suffix}'. Upload one of: {', '.join(sorted(ALLOWED))}")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise AudioError("ffmpeg is not installed. Install it (see README) and restart the app.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(p)],
        capture_output=True, text=True)
    try:
        info = json.loads(probe.stdout or "{}")
    except json.JSONDecodeError:
        info = {}
    if probe.returncode != 0 or not info.get("streams"):
        raise AudioError("The file could not be read as audio (corrupt, or not an audio/video recording).")
    duration = float(info.get("format", {}).get("duration") or 0)
    if duration < min_seconds:
        raise AudioError(f"The recording is too short ({duration:.1f}s) to contain a meeting.")
    out = Path(work_dir) / "audio_16k_mono.mp3"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(p), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise AudioError("Audio conversion failed: " + r.stderr[-300:])
    return out, duration


# API upload limits: split big files into ~20 min pieces. Returns a list of (chunk_path, start_offset_seconds) so timestamps stay correct.
# split_if_large exists only because of the API's upload limit

def split_if_large(path, work_dir, seconds=1200, max_bytes=MAX_API_BYTES):
    path = Path(path)
    if path.stat().st_size <= max_bytes:
        return [(path, 0.0)]
    pattern = Path(work_dir) / "chunk_%03d.mp3"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(path), "-f", "segment", "-segment_time", str(seconds),
                        "-c", "copy", str(pattern)], capture_output=True, text=True)
    chunks = sorted(Path(work_dir).glob("chunk_*.mp3"))
    if r.returncode != 0 or not chunks:
        raise AudioError("Could not split the long recording for upload.")
    out, offset = [], 0.0
    for c in chunks:
        out.append((c, offset))
        offset += probe_duration(c)
    return out