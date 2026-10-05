"""Transcript = list of timestamped segments with stable ids. Every stage works on this one type."""
import re
from dataclasses import dataclass, field

_REPLIES = {"yes", "yeah", "yep", "no", "nope", "okay", "ok", "right", "sure", "thanks",
            "thank you", "agreed", "done", "fine", "great", "mm", "hmm", "uh huh"}


# converts seconds to "HH:MM:SS" format

def fmt_ts(seconds):
    s = int(max(0, seconds or 0))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# Segment is a chunk/whisper output that contains the info about the timestamp,id and text .

@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str

    @property
    def ts(self):
        return fmt_ts(self.start)

    

# transcript is a list of ordered segments i.e., whole audio .

@dataclass
class Transcript:
    segments: list = field(default_factory=list)

    def __len__(self):
        return len(self.segments)

    def plain(self):
        """Texts joined with single spaces (used for evidence checks)."""
        return " ".join(s.text for s in self.segments)

    def display(self):
        """One line per segment: '[00:03:12] text' (shown to users, saved to .txt)."""
        return "\n".join(f"[{s.ts}] {s.text}" for s in self.segments)

    def timed(self):
        """Same format, fed to LLM 2."""
        return self.display()

    def numbered(self, seg_ids=None):
        """'[L12] text' lines, fed to LLM 1. Optionally only some segment ids."""
        ids = set(seg_ids) if seg_ids is not None else None
        return "\n".join(f"[L{s.id}] {s.text}" for s in self.segments if ids is None or s.id in ids)

    def word_count(self):
        return sum(len(s.text.split()) for s in self.segments)

    def duration(self):
        return max((s.end for s in self.segments), default=0.0)

    def by_id(self):
        return {s.id: s for s in self.segments}

    def with_texts(self, new_texts):
        """Copy with some segment texts replaced ({id: text}); ids and timestamps stay the same."""
        return Transcript([Segment(s.id, s.start, s.end, new_texts.get(s.id, s.text)) for s in self.segments])

    def split_parts(self, max_words, overlap=0):
        """Split into lists of segments of about max_words words. Never cuts a segment. Parts overlap by
        `overlap` segments so context at the edges is not lost."""
        segs, n = self.segments, len(self.segments)
        parts, i = [], 0
        while i < n:
            j, count = i, 0
            while j < n:
                w = len(segs[j].text.split())
                if j > i and count + w > max_words:
                    break
                count += w
                j += 1
            parts.append(segs[i:j])
            if j >= n:
                break
            i = j - overlap if j - overlap > i else j
        return parts
    
    def without_repeated_fillers(self, max_words=3, min_run=3):
        """Drop runs of the same short line repeated min_run+ times IN A ROW (a jingle or music that
        Whisper keeps writing as text). Ordinary replies such as 'Yes.' are never removed.
        Returns (new_transcript, removed_text_list)."""
        def key(s):
            return s.text.strip().lower().rstrip(".!?,")
        segs, kept, removed, i = self.segments, [], set(), 0
        while i < len(segs):
            j = i
            while j < len(segs) and key(segs[j]) == key(segs[i]):
                j += 1
            k = key(segs[i])
            if j - i >= min_run and len(k.split()) <= max_words and k not in _REPLIES:
                removed.add(k)
            else:
                kept.extend(segs[i:j])
            i = j
        return Transcript(kept), sorted(removed)

    @classmethod
    def from_text(cls, text):
        """One segment per non-empty line, no timing (for tests and simple callers)."""
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        return cls([Segment(i, 0.0, 0.0, ln) for i, ln in enumerate(lines, 1)])
    

# hands back transcript and detect language and its confidence score. 

@dataclass
class SttResult:
    transcript: Transcript
    language: object = None              # ISO code such as "en", or None if unknown
    language_probability: object = None


_TS_PREFIX = re.compile(r"\[\d{1,2}:\d{2}:\d{2}\]\s*")


def strip_timestamps(text):
    return _TS_PREFIX.sub("", text or "")
