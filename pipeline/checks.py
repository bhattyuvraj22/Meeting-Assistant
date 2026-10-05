"""Guardrails that keep the models honest. These run in every profile."""
import re

from rapidfuzz import fuzz  # gives a 0 to 100 similarity score between two texts.

NEGATIONS = {"not", "no", "never", "none", "nothing", "neither", "nor", "cannot", "without",
             "can't", "won't", "don't", "didn't", "isn't", "aren't", "wasn't", "weren't",
             "shouldn't", "couldn't", "wouldn't", "doesn't", "haven't", "hasn't", "hadn't"}

NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
                "hundred", "thousand", "million", "billion", "lakh", "crore"}

_STOP_OWNER = {"the", "team", "group", "and"}
_STOP_DEADLINE = {"by", "the", "a", "an", "of", "on", "in", "at", "to", "end", "before", "until", "next",
                  "this", "and", "till", "within", "from"}
_TS_PREFIX = re.compile(r"\[\d{1,2}:\d{2}:\d{2}\]\s*")


# ---------------------------------------------------------------- text helpers

# Splits text into lower-case words
def _words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower().replace("\u2019", "'"))

# words joined by single spaces, so comparison ignores case and punctuation
def norm(text):
    return " ".join(_words(text))

# Models sometimes copy the [hh:mm:ss] prefixes into a quote; they are not part of what was said.
def clean_quote(quote):
    return _TS_PREFIX.sub("", quote or "").strip()

# Finds the digit numbers in text
def numbers(text):
    return sorted(re.findall(r"\d+(?:[.,]\d+)?", text or ""))

# Finds number words
def number_words(text):
    return sorted(w for w in _words(text) if w in NUMBER_WORDS)

# Counts words like "not" and "never"
def negation_count(text):
    return sum(1 for w in _words(text) if w in NEGATIONS)


# ---------------------------------------------------------------- refinement

# checks whether a rewritten line is a safe edit, rejects if empty, length changed a lot, no. chnaged, number of negations changed.
def refine_ok(raw, new, lo=0.85, hi=1.15):
    """Is the refined text a safe edit of the raw text? Returns (ok, reason)."""
    if not new.strip():
        return False, "empty output"
    rw, nw = len(_words(raw)), len(_words(new))
    if rw and abs(nw - rw) > 3 and not lo <= nw / rw <= hi:  # small absolute slack: 'cube flow' -> 'Kubeflow'
        return False, f"length changed {nw / rw:.2f}x"
    if numbers(raw) != numbers(new):
        return False, "numbers changed"
    if negation_count(raw) != negation_count(new):
        return False, "negations changed"
    return True, ""

# Whole-word, case-insensitive search for a phrase. Returns the match or None.
def _find_phrase(text, phrase):
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, flags=re.IGNORECASE)

# True for words that look like an ordinary name: 'Rahul', 'Priya'. False for technical terms with inner capitals or digits: 'KuboFlow', 'PosterSQL', 'GPT4'.
def _plain_name(word):
    return word.isalpha() and word[:1].isupper() and word[1:].islower()

# Is this single word fix safe to apply? Returns (ok, reason).
def validate_correction(line_text, frm, to, glossary_terms=()):
    frm, to = (frm or "").strip(), (to or "").strip()
    if not frm or not to:
        return False, "empty correction"
    if frm == to:
        return False, "nothing changes"
    m = _find_phrase(line_text, frm)
    if not m:
        return False, f"'{frm}' not found in that line"
    fw, tw = frm.split(), to.split()
    if len(fw) > 6:
        return False, "too many words replaced"
    if len(tw) > len(fw) + 2:
        return False, "replacement is much longer than the original"
    if numbers(frm) != numbers(to) or number_words(frm) != number_words(to):
        return False, "would change a number"
    if negation_count(frm) != negation_count(to):
        return False, "would change a negation"
    glossary = {g.lower() for g in glossary_terms}
    mid_line = bool(line_text[:m.start()].strip())
    # Block one person's name being replaced by another ('Rahul' -> 'Priya').
    # Mis-heard technical terms look similar to the correct term, swapped names do not.
    if (len(fw) == 1 and len(tw) == 1 and mid_line and to.lower() not in glossary
            and _plain_name(frm) and _plain_name(to)
            and fuzz.ratio(frm.lower(), to.lower()) < 70):
        return False, "looks like one person's name being swapped for another (add it to the topic box to allow)"
    return True, ""

# Replace the first whole-word, case-insensitive occurrence of frm.
def apply_correction(line_text, frm, to):
    m = _find_phrase(line_text, frm.strip())
    if not m:
        return line_text
    return line_text[:m.start()] + to.strip() + line_text[m.end():]


# ---------------------------------------------------------------- minutes

# Does the evidence quote (roughly) appear in the transcript?
def quote_supported(quote, transcript, threshold=85):
    q = norm(clean_quote(quote))
    if len(q.split()) < 3:
        return False
    return fuzz.partial_ratio(q, norm(transcript)) >= threshold

# Best fuzzy match of the quote inside the normalised transcript (norm(transcript.plain())). 
# Returns the matched transcript text, widened to whole words, or None if it is not there.
def find_quote(quote, transcript_norm, threshold=85):
    
    q = norm(clean_quote(quote))
    if len(q.split()) < 3 or not transcript_norm:
        return None
    m = fuzz.partial_ratio_alignment(q, transcript_norm)
    if m is None or m.score < threshold:
        return None
    t = transcript_norm
    start = t.rfind(" ", 0, m.dest_start) + 1
    end = t.find(" ", m.dest_end)
    return t[start:] if end == -1 else t[start:end]

# A quote may differ slightly from what was said, but never in a number or a negation.
def same_meaning(quote, matched):
    q = norm(clean_quote(quote))
    return numbers(q) == numbers(matched) and negation_count(q) == negation_count(matched)

# An owner is believable only if the name was actually spoken in the given text(the guardrails pass the lines around the task, not the whole meeting).
def owner_supported(owner, transcript_plain):
    if owner is None or str(owner).strip().lower() in ("", "unspecified"):
        return True
    tokens = set(_words(transcript_plain))
    tokens |= {w[:-2] for w in tokens if w.endswith("'s")}
    for part in re.split(r"\s*(?:,|&|/|\band\b)\s*", str(owner)):
        # words of 2+ letters so owners such as 'QA' or 'HR' work; generic words do not count
        cand = [w for w in _words(part) if len(w) >= 2 and w not in _STOP_OWNER]
        if not cand or not any(w in tokens for w in cand):
            return False
    return True

# A deadline is believable only if it was said: no invented calendar dates or years.
def deadline_supported(deadline, transcript_plain, threshold=85):
    if deadline is None or str(deadline).strip().lower() in ("", "unspecified"):
        return True
    d = str(deadline)
    raw_lower = transcript_plain.lower()
    for iso in re.findall(r"\d{4}-\d{2}-\d{2}", d):
        if iso not in raw_lower:
            return False
    tokens = set(_words(transcript_plain))
    for year in re.findall(r"\b(?:19|20)\d{2}\b", d):
        if year not in tokens:
            return False
    key = [w for w in _words(d) if w not in _STOP_DEADLINE and len(w) > 1]
    for w in key:
        variants = {w, w + "s", w.rstrip("s"), w.replace("'s", "")}
        if not variants & tokens:
            return False
    return fuzz.partial_ratio(norm(d), norm(transcript_plain)) >= threshold

# Start positions of every whole-word occurrence of any phrase in text (text already lower-cased).
def _positions(text, phrases):
    return [m.start() for p in phrases
            for m in re.finditer(r"(?<!\w)" + re.escape(p.lower()) + r"(?!\w)", text)]

# Tentative wording that is NOT followed by a clear confirmation later in the same quote.'Someone should probably check it.' -> True.  'Maybe Monday? Yes, agreed.' -> False.
def is_hedged(quote, hedge_phrases, confirm_phrases=()):
    q = clean_quote(quote).lower().replace("\u2019", "'")
    hedges = _positions(q, hedge_phrases)
    if not hedges:
        return False
    return not any(pos > max(hedges) for pos in _positions(q, confirm_phrases))

# Numbers, and capitalised names in mid-sentence, that appear in `text` but never in the transcript.
def unsupported_facts(text, transcript_plain):
    said_numbers = {n.replace(",", "") for n in numbers(transcript_plain)}
    tokens = set(_words(transcript_plain))
    bad = [n for n in numbers(text) if n.replace(",", "") not in said_numbers]
    bad += [w for w in re.findall(r"(?<=[a-z,] )[A-Z][A-Za-z]+", text) if w.lower() not in tokens]
    return sorted(set(bad))

# The segment where the quote starts, or None. Windows of up to `window` consecutive segments are scored;
# the best score wins, and on a tie the window with the fewest segments (so the quote's own segment, not an
# earlier segment that merely shares a window with it).
def locate(quote, transcript, window=3):
    q = norm(clean_quote(quote))
    if len(q.split()) < 3:
        return None
    segs = transcript.segments
    best, best_w, best_seg = 0.0, 0, None
    for i in range(len(segs)):
        for w in range(1, window + 1):
            if i + w > len(segs):
                break
            text = norm(" ".join(s.text for s in segs[i:i + w]))
            if len(text) < 0.7 * len(q):       # a window shorter than the quote cannot contain it
                continue
            score = fuzz.partial_ratio(q, text)
            if score > best + 1e-9 or (abs(score - best) <= 1e-9 and best_seg is not None and w < best_w):
                best, best_w, best_seg = score, w, segs[i]
            if w == 1 and score >= 100:     # the quote sits entirely inside this one segment
                return segs[i]
    return best_seg if best >= 60 else None