from pathlib import Path  # builds file paths.

import yaml  # to read the YAML file
from dotenv import load_dotenv  # load API keys from .env file
from pydantic import ValidationError  # to catch class , data mismatch erros

from .errors import ConfigError
from .settings import Profile, Settings

ROOT = Path(__file__).resolve().parent.parent           
CONFIG_PATH = ROOT / "config.yaml"

# load .env ,opens config.yaml, checks that a profiles section exists, and returns the raw dict .
def _read(path=None):
    load_dotenv(ROOT / ".env")
    p = Path(path) if path else CONFIG_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {p}")
    except yaml.YAMLError as e:
        raise ConfigError(f"{p.name} is not valid YAML: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict) or not data["profiles"]:
        raise ConfigError(f"{p.name} must contain a 'profiles' section.")
    return data

# rewrite the long error message to clear sentence when field is wrong type or missing, and return it to the user.
def _fmt(where, exc):
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return f"Invalid config ({where}): " + "; ".join(parts)

# list all available setup from config.yaml and return the default which app fill in dropdown .
def list_profiles(path=None):
    raw = _read(path)
    return list(raw["profiles"]), raw.get("profile") or next(iter(raw["profiles"]))

#  Checks existence of profiles fro sheet, if not, it lists the available ones.Checks every field is filled in correctly. If not, it uses _fmt to explain the mistake.Checks that llm1 and llm2 are different models. Returns the approved setup as a plain dict that the rest of the program can use.
def load_config(profile=None, path=None):
    """Validate config.yaml and return the chosen profile as a plain dict (stt, llm1, llm2, settings, name)."""
    raw = _read(path)
    name = profile or raw.get("profile")
    if name not in raw["profiles"]:
        raise ConfigError(f"Unknown profile '{name}'. Available: {list(raw['profiles'])}")
    try:
        prof = Profile.model_validate(raw["profiles"][name])
        settings = Settings.model_validate(raw.get("settings") or {})
    except ValidationError as e:
        raise ConfigError(_fmt(f"profile '{name}'", e))
    cfg = prof.model_dump()
    cfg["name"] = name
    cfg["settings"] = settings.model_dump()
    if cfg["llm1"]["model"].strip().lower() == cfg["llm2"]["model"].strip().lower():
        raise ConfigError(
            f"LLM 1 and LLM 2 must be different models (both are '{cfg['llm1']['model']}' in profile '{name}'). "
            "The task requires two separate language-model stages.")
    return cfg
