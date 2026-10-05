"""Typed, validated configuration. A typo in config.yaml fails at startup with a clear message."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Used to spot when something was only a suggestion, not a decision.
DEFAULT_HEDGES = [
    "maybe", "perhaps", "might", "probably", "possibly", "what if", "could we", "we could",
    "how about", "i suggest", "someone should", "at some point", "i wonder", "not sure if",
    "let's think about", "would be nice", "worth considering", "if we have time",
]

# Clear agreement or commitment. Tentative wording FOLLOWED by one of these counts as agreed.
DEFAULT_CONFIRMS = [
    "agreed", "decided", "confirmed", "approved", "that's final", "let's go with", "let's do it",
    "let's do that", "go ahead", "sounds good", "will do", "i'll do it", "i'll do that",
    "i'll take it", "i'll take that", "on it", "yes", "yeah",
]

# holds stt settings, backend api/local, which language is spoken.
class SttCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["api", "local"]
    model: str
    base_url: str | None = None       # api backend only
    api_key_env: str | None = None    # name of the env var that holds the key
    language: str | None = None       # None = auto-detect (the app warns when it is not English)
    device: str = "auto"                 # local backend only
    compute_type: str = "auto"           # local backend only

# holds Ai base url, model, env that holds the secret key, crativity of AI(temperature), and timeout for request.
class LlmCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    model: str
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout: int = 300
    extra_body: dict = Field(default_factory=dict)   # passed to the provider as-is (e.g. reasoning_effort)

# holds the global settings for the pipeline, including thresholds, limits, and phrases to detect hedging or confirmation in speech.
class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refine_max_words: int = 700
    evidence_threshold: int = 85
    deadline_threshold: int = 85
    min_audio_seconds: int = 2
    min_words_per_minute: int = 20
    minutes_part_words: int = 2500
    minutes_part_overlap_segments: int = 3
    dedupe_threshold: int = 90
    max_upload_mb: int = 200
    keep_runs: int = 20
    hedge_phrases: list[str] = Field(default_factory=lambda: list(DEFAULT_HEDGES))
    confirm_phrases: list[str] = Field(default_factory=lambda: list(DEFAULT_CONFIRMS))

# bundels the stt and llm settings into a profile, which is selected by name in config.yaml. The profile is passed to the orchestrator and then to the other modules.
class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stt: SttCfg
    llm1: LlmCfg
    llm2: LlmCfg
