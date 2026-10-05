"""Honesty checks on the final record. Runs after LLM 2, in a fixed order, in every profile."""
from . import merge
from .checks import (deadline_supported, find_quote, is_hedged, locate, norm, owner_supported,
                     same_meaning, unsupported_facts)
from .schema import UNSPECIFIED, Proposal

# The located segment and its neighbours. An owner or deadline must be stated HERE, not just somewhere in the meeting.
def _context(transcript, seg, before=2, after=2):
    segs = transcript.segments
    i = next(k for k, s in enumerate(segs) if s.id == seg.id)
    return " ".join(s.text for s in segs[max(0, i - before): i + after + 1])

# goes through a list of decisions, proposals or tasks and keeps only the ones that are supported by the transcript. Returns the kept items and warnings for the dropped ones.
def _keep_supported(items, label, field, plain_norm, threshold, warnings):
    kept = []
    for it in items:
        name = getattr(it, field)[:80]
        matched = find_quote(it.evidence, plain_norm, threshold)
        if matched is None:
            warnings.append(f"Dropped {label} (quote not found in transcript): {name}")
        elif not same_meaning(it.evidence, matched):
            warnings.append(f"Dropped {label} (quote changes a number or negation): {name}")
        else:
            kept.append(it)
    return kept

# Mutates the record; returns a list of human-readable warnings for everything it changed.
def apply(record, transcript, settings):
    warnings = []
    plain = transcript.plain()
    plain_norm = norm(plain)
    hedges, confirms = settings.hedge_phrases, settings.confirm_phrases

    # 1. every item needs a quote that is really in the transcript, with the same numbers and negations
    record.decisions = _keep_supported(record.decisions, "decision", "decision", plain_norm,
                                       settings.evidence_threshold, warnings)
    record.proposals = _keep_supported(record.proposals, "proposal", "proposal", plain_norm,
                                       settings.evidence_threshold, warnings)
    record.tasks = _keep_supported(record.tasks, "task", "description", plain_norm,
                                   settings.evidence_threshold, warnings)

    # 2. timestamps and local context always come from the transcript, never from the model
    context = {}
    for item in [*record.decisions, *record.proposals, *record.tasks]:
        seg = locate(item.evidence, transcript)
        item.timestamp = seg.ts if seg else ""
        context[id(item)] = _context(transcript, seg) if seg else plain

    for t in record.tasks:
        ctx = context[id(t)]
        # 3. the owner must be named near the task, not just somewhere in the meeting
        if not owner_supported(t.owner, ctx):
            warnings.append(f"Owner '{t.owner}' is not named where this task was discussed, "
                            f"set to unspecified: {t.description[:60]}")
            t.owner = UNSPECIFIED
        # 4. the deadline must be stated near the task, never an invented calendar date
        if not deadline_supported(t.deadline, ctx, settings.deadline_threshold):
            warnings.append(f"Deadline '{t.deadline}' was not stated with this task, "
                            f"set to unspecified: {t.description[:60]}")
            t.deadline = UNSPECIFIED
        # 5. tentative wording with no confirmation after it means 'suggested'
        if t.status == "assigned" and is_hedged(t.evidence, hedges, confirms):
            t.status = "suggested"
            warnings.append(f"Task marked as suggested (tentative wording): {t.description[:60]}")

    # 6. a 'decision' that is tentative and never confirmed is really a proposal
    decisions = []
    for d in record.decisions:
        if is_hedged(d.evidence, hedges, confirms):
            record.proposals.append(Proposal(proposal=d.decision, evidence=d.evidence, timestamp=d.timestamp))
            warnings.append(f"Moved from decisions to proposals (tentative wording): {d.decision[:60]}")
        else:
            decisions.append(d)
    record.decisions = decisions

    # 7. flag numbers or names in the written text that were never said (warning only)
    texts = [("summary", record.summary)]
    texts += [(f"minutes topic '{s.topic[:40]}'", " ".join(s.points)) for s in record.minutes]
    texts += [(f"decision '{d.decision[:40]}'", d.decision) for d in record.decisions]
    texts += [(f"task '{t.description[:40]}'", t.description) for t in record.tasks]
    for where, text in texts:
        bad = unsupported_facts(text, plain)
        if bad:
            warnings.append(f"Check the {where}: {', '.join(bad)} not found in the transcript.")

    # 8. remove duplicates
    thr = settings.dedupe_threshold
    record.decisions, n1 = merge.dedupe_decisions(record.decisions, thr)
    record.proposals, n2 = merge.dedupe_proposals(record.proposals, thr)
    record.proposals, n3 = merge.drop_proposals_matching_decisions(record.proposals, record.decisions, thr - 5)
    record.tasks, n4 = merge.dedupe_tasks(record.tasks, thr)
    if n1 + n2 + n3 + n4:
        warnings.append(f"Removed {n1 + n2 + n3 + n4} duplicate item(s).")
    return warnings