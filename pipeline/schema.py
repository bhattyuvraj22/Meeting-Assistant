"""The shape of the final record. Every profile must produce this (validated by Pydantic)."""
from typing import Literal                                                                  # restrict a field to a exact values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator         # write own cleanup/check for a field.

UNSPECIFIED = "unspecified"
_EMPTY = {"", "none", "null", "n/a", "na", "tbd", "unknown", "not specified", "not stated", "unspecified"}
_ASSIGNED = {"assigned", "confirmed", "agreed", "committed"}

# every class usese extra="ignore" because the model reply may contain extra fields, and those are silently dropped instead of causing an error.
# AI/modeels gives messy answers, and these classes and functions tidy them up.

class Task(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str
    owner: str = UNSPECIFIED
    deadline: str = UNSPECIFIED
    status: Literal["assigned", "suggested"] = "suggested"
    evidence: str = ""
    timestamp: str = ""          # filled by code (never trusted from the model)

    @field_validator("owner", "deadline", mode="before")
    @classmethod
    def fix_unspecified(cls, v):
        if v is None or str(v).strip().lower() in _EMPTY:
            return UNSPECIFIED
        return str(v).strip()

    @field_validator("status", mode="before")
    @classmethod
    def fix_status(cls, v):
        return "assigned" if str(v).strip().lower() in _ASSIGNED else "suggested"


class Decision(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision: str
    evidence: str = ""
    timestamp: str = ""


class Proposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    proposal: str
    evidence: str = ""
    timestamp: str = ""


class MinutesSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str
    points: list[str] = Field(default_factory=list)

    @field_validator("points", mode="before")
    @classmethod
    def fix_points(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(p) for p in v]


class Record(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str
    minutes: list[MinutesSection] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)


class PartNotes(BaseModel):
    """What LLM 2 extracts from one part of a long meeting."""
    model_config = ConfigDict(extra="ignore")
    notes: list[MinutesSection] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)


class SummaryMinutes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str
    minutes: list[MinutesSection] = Field(default_factory=list)

# Validate list items one by one: a single malformed item is skipped instead of failing the whole reply.
def _items(cls, raw, label, warns):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"'{label}' must be a list")
    out = []
    for i, item in enumerate(raw, 1):
        try:
            out.append(cls.model_validate(item))
        except ValidationError:
            warns.append(f"Skipped a malformed {label} item (#{i}) in the model reply.")
    return out

# dict from LLM 2 build record, warnings. Raises ValueError/ValidationError if the reply is unusable.
def build_record(data):
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("missing 'summary'")
    warns = []
    rec = Record(
        summary=summary.strip(),
        minutes=_items(MinutesSection, data.get("minutes"), "minutes", warns),
        decisions=_items(Decision, data.get("decisions"), "decision", warns),
        proposals=_items(Proposal, data.get("proposals"), "proposal", warns),
        tasks=_items(Task, data.get("tasks"), "task", warns))
    return rec, warns

# dict from LLM 2 build record, warnings for one chunk of a long meeting. Raises ValueError/ValidationError if the reply is unusable.
def build_part_notes(data):
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    warns = []
    notes = PartNotes(
        notes=_items(MinutesSection, data.get("notes", data.get("minutes")), "notes", warns),
        decisions=_items(Decision, data.get("decisions"), "decision", warns),
        proposals=_items(Proposal, data.get("proposals"), "proposal", warns),
        tasks=_items(Task, data.get("tasks"), "task", warns))
    return notes, warns

# dict from LLM 2 build summary and minutes, warnings. Raises ValueError/ValidationError if the reply is unusable.
def build_summary_minutes(data):
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    warns = []
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("missing 'summary'")
    return SummaryMinutes(summary=summary.strip(),
                          minutes=_items(MinutesSection, data.get("minutes"), "minutes", warns)), warns
