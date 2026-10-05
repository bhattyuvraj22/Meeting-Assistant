"""Startup check: tell the user what is missing BEFORE a run starts."""
import importlib.util
import json
import os
import shutil
import urllib.request
from urllib.parse import urlparse


def _is_local(url):
    return "localhost" in url or "127.0.0.1" in url

# checks/asks which models are downloaded in a local Ollama instance. Returns a set of model names, or raises an exception if Ollama is not running.
def _ollama_models(base_url):
    root = base_url.split("/v1")[0].rstrip("/")
    with urllib.request.urlopen(root + "/api/tags", timeout=3) as r:
        return {m["name"] for m in json.load(r).get("models", [])}

# Checks everything is ready or not, problems that must be fixed and notes(information).
def check_environment(cfg):
    problems, notes = [], []
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        problems.append("ffmpeg/ffprobe not found. Install ffmpeg (see README).")
    stt = cfg["stt"]
    if stt["backend"] == "local" and importlib.util.find_spec("faster_whisper") is None:
        problems.append("faster-whisper missing: pip install -r requirements-local.txt")
    if stt["backend"] == "api":
        if stt.get("api_key_env") and not os.getenv(stt["api_key_env"]):
            problems.append(f"{stt['api_key_env']} is not set in .env (needed for speech-to-text API).")
        host = urlparse(stt.get("base_url") or "").netloc
        if host:
            notes.append(f"Privacy: the audio is sent to {host} for transcription.")
    have, local_llm = None, False
    for name in ("llm1", "llm2"):
        c = cfg[name]
        env = c.get("api_key_env")
        if env and not os.getenv(env):
            problems.append(f"{env} is not set in .env (needed for {name}).")
        if _is_local(c["base_url"]):
            local_llm = True
            try:
                if have is None:
                    have = _ollama_models(c["base_url"])
                if c["model"] not in have and c["model"] + ":latest" not in have:
                    problems.append(f"Model not downloaded for {name}: run `ollama pull {c['model']}`")
            except (OSError, ValueError):
                problems.append("Ollama is not running (start it, or choose the 'api' profile).")
                break
        else:
            host = urlparse(c["base_url"]).netloc
            if host:
                notes.append(f"Privacy: the transcript text is sent to {host} for {name}.")
    if local_llm:
        notes.append("Local models: start Ollama with OLLAMA_CONTEXT_LENGTH=32768 (or higher). "
                     "The default context window is small and long transcripts get cut off silently.")
    return list(dict.fromkeys(problems)), list(dict.fromkeys(notes))
