"""Stage 1: speech-to-text. Two backends behind one function. Returns timestamped segments + language."""
import os  # read the api key from env
import re  # split text into sentences

from . import audio  # gives access to audio.split_if_large
from .errors import (  # custom error for setup probem or faster-whisper not being installed
    ConfigError,
    PipelineError,
)
from .llm_client import call_with_retries  # retries the API call if the network fails
from .transcript import Segment, SttResult, Transcript  # build these dataclasses 

_local_models = {}


# maps language names to codes, because Groq returns "english" while faster-whisper returns "en".
_LANG_NAMES = {"english": "en", "hindi": "hi", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
               "portuguese": "pt", "dutch": "nl", "russian": "ru", "chinese": "zh", "japanese": "ja",
               "korean": "ko", "arabic": "ar", "bengali": "bn", "tamil": "ta", "telugu": "te", "urdu": "ur",
               "marathi": "mr", "gujarati": "gu", "turkish": "tr", "polish": "pl", "indonesian": "id"}


# 'English' / 'english' / 'en' -> 'en'. Unknown names are returned lower-cased.
def normalize_language(lang):
    if not lang:
        return None
    s = str(lang).strip().lower()
    return _LANG_NAMES.get(s, s)


def transcribe(wav_path, cfg, glossary="", work_dir=".", client=None):
    backend = cfg.get("backend")
    if backend == "local":
        return _local(wav_path, cfg, glossary)
    if backend == "api":
        return _api(wav_path, cfg, glossary, work_dir, client)
    raise ConfigError(f"Unknown stt backend '{backend}' (use 'local' or 'api').")

# check fast-whisper is installed or not,nand loads model .
def _local(wav_path, cfg, glossary):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise PipelineError("faster-whisper is not installed. Run: pip install -r requirements-local.txt")
    key = (cfg["model"], cfg.get("device", "auto"), cfg.get("compute_type", "auto"))
    if key not in _local_models:
        _local_models[key] = WhisperModel(key[0], device=key[1], compute_type=key[2])
    kwargs = {"vad_filter": True}
    if cfg.get("language"):
        kwargs["language"] = cfg["language"]
    if glossary:
        kwargs["initial_prompt"] = f"Terms: {glossary}"
    segments, info = _local_models[key].transcribe(str(wav_path), **kwargs)
    segs = []
    for s in segments:
        text = s.text.strip()
        if text:
            segs.append(Segment(len(segs) + 1, float(s.start), float(s.end), text))
    return SttResult(Transcript(segs), normalize_language(getattr(info, "language", None)),
                     getattr(info, "language_probability", None))

# Read a field from an object or a dict.
def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

# Fallback when the provider returns no segments: split sentences, estimate times from text length.
def _pseudo_segments(text, offset, duration):
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]
    total = sum(len(s) for s in sentences) or 1
    out, done = [], 0
    for s in sentences:
        start = offset + duration * done / total
        done += len(s)
        out.append((start, offset + duration * done / total, s.strip()))
    return out


# Whisper's own quality numbers per segment (standard thresholds from the Whisper paper/code):
# no_speech_prob high + avg_logprob low = probably silence turned into text; 
# compression_ratio high = repetitive text that Whisper got stuck on.
def _looks_hallucinated(seg):
    no_speech = float(_get(seg, "no_speech_prob", 0) or 0)
    logprob = float(_get(seg, "avg_logprob", 0) or 0)
    compression = float(_get(seg, "compression_ratio", 0) or 0)
    return (no_speech > 0.6 and logprob < -1.0) or compression > 2.4

#sending recording to an online transcription service and tidying up what comes back.
def _api(wav_path, cfg, glossary, work_dir, client=None):
    env = cfg.get("api_key_env", "") or ""
    if client is None:
        from openai import OpenAI
        key = os.getenv(env) if env else "not-needed"
        if not key:
            raise ConfigError(f"Missing API key: set {env} in your .env file.")
        client = OpenAI(base_url=cfg["base_url"], api_key=key, max_retries=0)
    base = {"model": cfg["model"], "response_format": "verbose_json"}
    if cfg.get("language"):
        base["language"] = cfg["language"]
    if glossary:
        base["prompt"] = f"Terms: {glossary}"

    raw, language = [], None
    for chunk, offset in audio.split_if_large(wav_path, work_dir):
        def once(chunk=chunk):
            with open(chunk, "rb") as f:     # re-opened on every retry
                return client.audio.transcriptions.create(file=f, **base)
        resp = call_with_retries(once, model=cfg["model"], base_url=cfg.get("base_url", ""), env_var=env, retries=4)
        language = language or normalize_language(_get(resp, "language"))
        segs = _get(resp, "segments") if not isinstance(resp, str) else None
        if segs:
            for s in segs:
                text = (_get(s, "text", "") or "").strip()
                if text and not _looks_hallucinated(s):
                    raw.append((offset + float(_get(s, "start", 0) or 0), offset + float(_get(s, "end", 0) or 0), text))
        else:
            text = resp if isinstance(resp, str) else (_get(resp, "text", "") or "")
            duration = float(_get(resp, "duration", 0) or 0) if not isinstance(resp, str) else 0.0
            raw += _pseudo_segments(text, offset, duration)
    segments = [Segment(i, a, b, t) for i, (a, b, t) in enumerate(raw, 1)]
    return SttResult(Transcript(segments), language, None)
