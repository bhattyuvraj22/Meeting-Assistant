"""Fetch local models for a profile. Usage: python download_models.py --profile local [--pull]"""
import argparse
import shutil
import subprocess
from pipeline.config import load_config

ap = argparse.ArgumentParser()
ap.add_argument("--profile", default="local")
ap.add_argument("--pull", action="store_true", help="run `ollama pull` for you")
args = ap.parse_args()
cfg = load_config(args.profile)

if cfg["stt"]["backend"] == "local":
    from faster_whisper import WhisperModel
    print(f"Downloading Whisper '{cfg['stt']['model']}' ...")
    WhisperModel(cfg["stt"]["model"], device="cpu", compute_type="int8")

for name in ("llm1", "llm2"):
    c = cfg[name]
    if "localhost" in c["base_url"] or "127.0.0.1" in c["base_url"]:
        cmd = ["ollama", "pull", c["model"]]
        print(("Running: " if args.pull else "Run: ") + " ".join(cmd))
        if args.pull:
            if not shutil.which("ollama"):
                raise SystemExit("Ollama is not installed: https://ollama.com")
            subprocess.run(cmd, check=True)
print("Done.")
