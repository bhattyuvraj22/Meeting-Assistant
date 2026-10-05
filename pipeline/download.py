"""Optional input: download the audio of a meeting from a link (YouTube, Vimeo, direct .mp3 link, ...)."""
from pathlib import Path
from urllib.parse import urlparse

from .errors import AudioError

MAX_LINK_SECONDS = 2 * 60 * 60      # refuse very long videos before downloading anything

# Download only the audio track of a link into work_dir. Returns the file path or raises AudioError.
def download_audio(url, work_dir, max_seconds=MAX_LINK_SECONDS):
    url = (url or "").strip()
    if urlparse(url).scheme not in ("http", "https"):
        raise AudioError("The link must start with http:// or https://")
    try:
        import yt_dlp                    # imported here so the app still runs without it
    except ImportError:
        raise AudioError("Downloading from links needs yt-dlp. Run: pip install yt-dlp")

    opts = {"format": "bestaudio/best",                              # audio only: much smaller than the video
            "outtmpl": str(Path(work_dir) / "download.%(ext)s"),
            "noplaylist": True, "quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)             # step 1: read details only
            if info.get("_type") == "playlist":
                raise AudioError("That link is a playlist. Paste the link of a single video.")
            if info.get("is_live"):
                raise AudioError("Live streams can't be processed. Try again after the stream has ended.")
            duration = info.get("duration") or 0
            if duration > max_seconds:
                raise AudioError(f"The recording is {duration / 3600:.1f} h long; the limit for links is "
                                 f"{max_seconds / 3600:.0f} h.")
            info = ydl.extract_info(url, download=True)              # step 2: download
            path = Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as e:
        raise AudioError(f"Could not download audio from that link (private, removed, or not supported): "
                         f"{str(e)[:200]}")
    if not path.exists():
        raise AudioError("The download finished but no audio file was found.")
    return path