"""Stage 3 (LLM 2): minutes, decisions, tasks -> validated JSON -> guardrails.
Short meetings use one call; long meetings are split into parts (map), merged in code, then summarised (reduce)."""
import json

from pydantic import ValidationError

from . import guardrails, merge
from .checks import is_hedged, quote_supported
from .errors import PipelineError, RequestTooLargeError
from .jsonutil import extract_json
from .schema import Record, build_part_notes, build_record, build_summary_minutes
from .transcript import Transcript

MIN_PART_WORDS = 600

# puts the transcript inside <transcript>...</transcript> tags, which is exactly what the prompts expect
def _wrap(text):
    return f"<transcript>\n{text}\n</transcript>"

# Ask for JSON, validate it, retry once with the error. Returns (validated_object, warnings).
def _call_json(llm, system, user, validate, label="minutes"):
    err = ""
    for _ in range(2):
        msg = user if not err else f"{user}\n\nYour previous reply was invalid ({err}). Return only valid JSON."
        reply = llm.chat(system, msg, json_mode=True)
        try:
            return validate(extract_json(reply))
        except (ValueError, ValidationError) as e:
            err = str(e)[:400]
    raise PipelineError(f"The {label} model did not return valid JSON: {err}")

# Split the transcript into parts, send it with the extract prompt and validate it as PartNotes,
# Merge all the parts' results with merge.merge_parts.
# Return the final Record. The summary and minutes come from the AI, but the decisions, 
# proposals and tasks come from the code merge, not rewritten by the model.
def _map_reduce(transcript, llm, prompts, settings, warnings):
    part_words = settings.minutes_part_words
    for attempt in range(2):
        parts = transcript.split_parts(part_words, settings.minutes_part_overlap_segments)
        notes, local = [], []
        try:
            for i, seg_list in enumerate(parts, 1):
                yield "progress", f"Writing minutes (part {i}/{len(parts)})..."
                pn, w = _call_json(llm, prompts["extract"], _wrap(Transcript(seg_list).timed()),
                                   build_part_notes, "minutes")
                notes.append(pn)
                local += w
            break
        except RequestTooLargeError:
            if attempt == 0 and part_words > MIN_PART_WORDS:
                part_words = max(MIN_PART_WORDS, part_words // 2)
                warnings.append(f"The provider rejected a large request; retrying with smaller parts ({part_words} words).")
                continue
            raise PipelineError("The minutes model's provider keeps rejecting requests as too large. "
                                "Use the local profile or a provider/model with higher token limits.")
    warnings += local

    yield "progress", "Writing minutes (combining parts)..."
    merged = merge.merge_parts(notes, settings)
    # only decisions that would survive the guardrails may reach the summary as "agreed"
    plain = transcript.plain()
    safe_decisions = [d.decision for d in merged.decisions
                      if quote_supported(d.evidence, plain, settings.evidence_threshold)
                      and not is_hedged(d.evidence, settings.hedge_phrases, settings.confirm_phrases)]
    payload = {"notes": [{"topic": s.topic, "points": s.points} for s in merged.notes],
               "decisions": safe_decisions}
    sm, w = _call_json(llm, prompts["reduce"], json.dumps(payload, ensure_ascii=False),
                       build_summary_minutes, "summary")
    warnings += w
    # decisions / proposals / tasks come from the code merge, NOT rewritten by the model
    return Record(summary=sm.summary, minutes=sm.minutes, decisions=merged.decisions,
                  proposals=merged.proposals, tasks=merged.tasks)

# Generator: yields ("progress", message) and finally ("result", (record, warnings)), prompts = {"single": ..., "extract": ..., "reduce": ...}
def generate_iter(transcript, llm, prompts, settings):
   
    warnings = []
    if transcript.word_count() <= settings.minutes_part_words:
        yield "progress", "Writing minutes..."
        record, w = _call_json(llm, prompts["single"], _wrap(transcript.timed()), build_record)
        warnings += w
    else:
        record = yield from _map_reduce(transcript, llm, prompts, settings, warnings)
    warnings += guardrails.apply(record, transcript, settings)
    yield "result", (record, warnings)

# Non-streaming helper. Returns (Record, warnings).
def generate_record(transcript, llm, prompts, settings):
    result = None
    for kind, payload in generate_iter(transcript, llm, prompts, settings):
        if kind == "result":
            result = payload
    return result
