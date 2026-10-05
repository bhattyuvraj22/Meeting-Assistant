"""Combine results from several parts of a long meeting and remove duplicates."""
from rapidfuzz import fuzz                                     # for character-based similarity

from .checks import negation_count, norm, numbers
from .schema import UNSPECIFIED, MinutesSection, PartNotes

# Texts that differ in a number or a negation are never duplicates.
def _same_meaning_basics(a, b):
    return numbers(a) == numbers(b) and negation_count(a) == negation_count(b)

# Keep one item per group of near-identical items (the richest one). Returns (kept, n_removed).
# Uses plain character similarity (not token-set similarity): 'Update the OAuth docs' and 'Update the API docs'
# must stay two tasks. Losing a real task costs more than leaving a harmless near-duplicate.
def dedupe(items, text_of, threshold, richness=lambda x: 0, compatible=lambda a, b: True):
    kept, removed = [], 0
    for it in items:
        hit = None
        for i, k in enumerate(kept):
            a, b = text_of(it), text_of(k)
            if compatible(it, k) and _same_meaning_basics(a, b) \
                    and fuzz.ratio(norm(a), norm(b)) >= threshold:
                hit = i
                break
        if hit is None:
            kept.append(it)
        else:
            removed += 1
            if richness(it) > richness(kept[hit]):
                kept[hit] = it
    return kept, removed

# scores how complete a task is .
def task_richness(t):
    return (t.owner != UNSPECIFIED) + (t.deadline != UNSPECIFIED) + (t.status == "assigned") + (1 if t.evidence else 0)

# Two tasks with different named owners or different stated deadlines are different tasks.
def tasks_compatible(a, b):
    if UNSPECIFIED not in (a.owner, b.owner) and a.owner.lower() != b.owner.lower():
        return False
    if UNSPECIFIED not in (a.deadline, b.deadline) and a.deadline.lower() != b.deadline.lower():
        return False
    return True

# compares the task descriptions, using task_richness and tasks_compatible
def dedupe_tasks(tasks, threshold):
    return dedupe(tasks, lambda t: t.description, threshold, task_richness, tasks_compatible)

# compares the decision text.
def dedupe_decisions(decisions, threshold):
    return dedupe(decisions, lambda d: d.decision, threshold)

#compares the proposal text.
def dedupe_proposals(proposals, threshold):
    return dedupe(proposals, lambda p: p.proposal, threshold)

# A proposal that was later agreed is a decision, not a proposal.
def drop_proposals_matching_decisions(proposals, decisions, threshold):
    kept, removed = [], 0
    for p in proposals:
        dup = any(_same_meaning_basics(p.proposal, d.decision)
                  and fuzz.ratio(norm(p.proposal), norm(d.decision)) >= threshold for d in decisions)
        if dup:
            removed += 1
        else:
            kept.append(p)
    return kept, removed

# merges topics with similar names, their points are combined and deduplicated .
def _merge_sections(sections, threshold):
    merged = []
    for s in sections:
        hit = next((m for m in merged if fuzz.ratio(norm(m.topic), norm(s.topic)) >= threshold), None)
        if hit is None:
            merged.append(MinutesSection(topic=s.topic, points=list(s.points)))
        else:
            hit.points, _ = dedupe(hit.points + list(s.points), lambda p: p, threshold)
    return merged

# List of PartNotes (one per transcript part) -> one PartNotes without duplicates.
def merge_parts(parts, settings):
    thr = settings.dedupe_threshold
    notes, decisions, proposals, tasks = [], [], [], []
    for p in parts:
        notes += p.notes
        decisions += p.decisions
        proposals += p.proposals
        tasks += p.tasks
    decisions, _ = dedupe_decisions(decisions, thr)
    proposals, _ = dedupe_proposals(proposals, thr)
    proposals, _ = drop_proposals_matching_decisions(proposals, decisions, thr - 5)
    tasks, _ = dedupe_tasks(tasks, thr)
    return PartNotes(notes=_merge_sections(notes, thr), decisions=decisions, proposals=proposals, tasks=tasks)
