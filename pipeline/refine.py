"""Stage 2 (LLM 1): fix mis-heard technical terms. LLM 1 only LISTS corrections; code checks and applies them."""
import re                               # apply corrections

from .checks import apply_correction, refine_ok, validate_correction
from .jsonutil import extract_json
from .transcript import Transcript

# splits it wherever it finds a comma, a semicolon or a new line and form a set of lower-cased terms. Empty terms are ignored.
def _glossary_terms(glossary):
    return {t.strip().lower() for t in re.split(r"[,;\n]", glossary or "") if t.strip()}

# gets the line number out of the model's output.
def _line_id(value):
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else None

# Ask LLM 1 for a corrections list. One retry with the parse error. Returns (list, None) or (None, error).
def _ask(llm, system_prompt, user):
    err = ""
    for _ in range(2):
        msg = user if not err else f"{user}\n\nYour previous reply was invalid ({err}). Return only the JSON object."
        reply = llm.chat(system_prompt, msg, json_mode=True)
        try:
            data = extract_json(reply)
            corrections = data.get("corrections", [])
            if not isinstance(corrections, list):
                raise ValueError("'corrections' must be a list")
            return corrections, None
        except ValueError as e:
            err = str(e)[:200]
    return None, err

# Generator: yields ("progress", message) and finally ("result", (refined_transcript, applied, warnings)).
def refine_iter(transcript, llm, system_prompt, max_words=700, glossary=""):
    parts = transcript.split_parts(max_words, 0)
    terms = _glossary_terms(glossary)
    by_id = transcript.by_id()
    new_texts, applied, skipped, warnings = {}, [], [], []

    for i, part in enumerate(parts, 1):
        yield "progress", f"Refining transcript (part {i}/{len(parts)})..."
        user = (f"Meeting topic / known terms: {glossary}\n\n" if glossary else "") + Transcript(part).numbered()
        corrections, err = _ask(llm, system_prompt, user)
        if corrections is None:
            warnings.append(f"Refinement part {i} kept as raw text (the model did not return valid JSON: {err}).")
            continue
        in_part = {s.id for s in part}
        per_line = {}
        for c in corrections:
            if not isinstance(c, dict):
                skipped.append("a correction that was not an object")
                continue
            lid = _line_id(c.get("line"))
            if lid not in in_part:
                skipped.append(f"correction for unknown line {c.get('line')}")
                continue
            per_line.setdefault(lid, []).append((str(c.get("from", "")), str(c.get("to", ""))))

        # apply this part's corrections, line by line
        for lid, pairs in per_line.items():
            seg = by_id[lid]
            text, line_applied = seg.text, []
            for frm, to in pairs:
                ok, why = validate_correction(text, frm, to, terms)
                if ok:
                    text = apply_correction(text, frm, to)
                    line_applied.append({"line": lid, "timestamp": seg.ts, "from": frm.strip(), "to": to.strip()})
                else:
                    skipped.append(f"'{frm}' -> '{to}' at [{seg.ts}]: {why}")
            if not line_applied:
                continue
            ok, why = refine_ok(seg.text, text)      # final safety net on the whole edited line
            if ok:
                new_texts[lid] = text
                applied += line_applied
            else:
                skipped.append(f"all corrections at [{seg.ts}] reverted: {why}")

    # Consistency pass (runs once, after ALL parts): a correction accepted once is applied to every
    # other line with the same mis-heard words. LLMs often fix a term once and miss its repeats.
    learned = {}
    for c in applied:
        learned.setdefault(c["from"].lower(), (c["from"], c["to"]))
    for seg in transcript.segments:
        text = new_texts.get(seg.id, seg.text)
        line_applied = []
        for frm, to in learned.values():
            for _ in range(5):                      # a term can appear more than once in a line
                ok, _why = validate_correction(text, frm, to, terms)
                if not ok:                          # not found any more (or unsafe here): stop
                    break
                text = apply_correction(text, frm, to)
                line_applied.append({"line": seg.id, "timestamp": seg.ts, "from": frm, "to": to})
        if line_applied and refine_ok(seg.text, text)[0]:   # same final safety net, against the RAW line
            new_texts[seg.id] = text
            applied += line_applied

    for s in skipped[:10]:
        warnings.append(f"Skipped refinement: {s}")
    if len(skipped) > 10:
        warnings.append(f"...and {len(skipped) - 10} more skipped refinement corrections.")
    yield "result", (transcript.with_texts(new_texts), applied, warnings)

# Non-streaming helper. Returns (refined_transcript, applied_corrections, warnings).   
def refine_transcript(transcript, llm, system_prompt, max_words=700, glossary=""):
    result = None
    for kind, payload in refine_iter(transcript, llm, system_prompt, max_words, glossary):
        if kind == "result":
            result = payload
    return result
