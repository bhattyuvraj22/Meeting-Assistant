"""The 'orchestra': runs the stages in order and yields progress events."""
import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from . import audio, download, minutes, refine, render, stt
from .errors import ConfigError, PipelineError
from .llm_client import LLM
from .logging_setup import close_run_logger, get_run_logger
from .settings import Settings
from .transcript import SttResult, Transcript

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_RUN_DIR = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")

# It reads all the prompts for the AI from the prompts/ folder and returns them ready to use
def load_prompts():
    def read(name):
        try:
            return (PROMPTS / name).read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"Cannot read prompts/{name}: {e.strerror or e}")

    # Optional shared rules: only needed by prompts that contain a {RULES} placeholder.
    rules_file = PROMPTS / "minutes_rules.txt"
    rules = read(rules_file.name).strip() if rules_file.exists() else None

    def with_rules(name):
        text = read(name)
        if "{RULES}" not in text:
            return text  # self-contained prompt: its rules are written inline
        if rules is None:
            raise ConfigError(f"prompts/{name} uses {{RULES}} but prompts/{rules_file.name} does not exist.")
        return text.replace("{RULES}", rules)

    return {"refine": read("refine.txt"), "single": with_rules("minutes.txt"),
            "extract": with_rules("minutes_extract.txt"), "reduce": read("minutes_reduce.txt")}

# Every run creates a new folder in outputs/. This function deletes the oldest folders so the disk doesn't fill up
def cleanup_old_runs(out_root, keep, current=None):
    root = Path(out_root)
    if not root.exists():
        return
    runs = sorted(d for d in root.iterdir() if d.is_dir() and _RUN_DIR.match(d.name))
    for d in runs[:max(0, len(runs) - max(1, keep))]:
        if d.name != current:
            shutil.rmtree(d, ignore_errors=True)

# checks that the settings: part of config.yaml is correct
def _settings(cfg):
    try:
        return Settings.model_validate(cfg.get("settings") or {})
    except ValidationError as e:
        raise ConfigError("Invalid settings: " + "; ".join(str(x.get("loc")) + " " + x.get("msg", "") for x in e.errors()))


# This runs the entire process from audio to meeting notes. While it works, 
# it keeps sending status updates like "Transcribing..." so the web page can show live progress.
# If something fails, it tells you at which step and keeps whatever was produced so far.
def run_pipeline_iter(audio_path, cfg, out_root="outputs", glossary="", stt_fn=None, llm1=None, llm2=None,audio_url=None):
    state = {"warnings": [], "files": {}, "file_list": [], "corrections": [], "stage_seconds": {}}
    started, stage, log = time.monotonic(), "audio", None

    def say(msg):
        return f"{msg} ({time.monotonic() - started:.0f}s)"

    def save(name, content):
        path = Path(state["out_dir"]) / name
        path.write_text(content, encoding="utf-8")
        state["files"][name] = str(path)
        state["file_list"] = list(state["files"].values())

    def timed_stage(name):
        nonlocal stage, t_stage
        if t_stage is not None:
            state["stage_seconds"][stage] = round(time.monotonic() - t_stage, 1)
            log.info("stage %s finished in %.1fs", stage, state["stage_seconds"][stage])
        stage, t_stage = name, time.monotonic()

    t_stage = None
    try:
        st = _settings(cfg)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        out_dir = Path(out_root) / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        state.update(out_dir=str(out_dir), run_id=run_id)
        log = get_run_logger(out_dir, run_id)
        log.info("run %s profile=%s stt=%s llm1=%s llm2=%s", run_id, cfg.get("name"),
                 cfg["stt"]["model"], cfg["llm1"]["model"], cfg["llm2"]["model"])
        cleanup_old_runs(out_root, st.keep_runs, current=run_id)
        prompts = load_prompts()

        # ---- audio
        timed_stage("audio")
        if audio_url:
            yield stage, say("Downloading audio from the link..."), state
            audio_path = download.download_audio(audio_url, out_dir)
        yield stage, say("Checking audio file..."), state
        wav, duration = audio.validate_and_convert(audio_path, out_dir, st.min_audio_seconds)

        # ---- speech to text
        timed_stage("stt")
        yield stage, say(f"Transcribing {duration / 60:.1f} min of audio ({cfg['stt']['model']})..."), state
        run_stt = stt_fn or (lambda p, c, g: stt.transcribe(p, c, glossary=g, work_dir=out_dir))
        res = run_stt(wav, cfg["stt"], glossary)
        if not isinstance(res, SttResult):
            res = SttResult(Transcript.from_text(str(res)), "en", 1.0)
        raw = res.transcript
        raw, fillers = raw.without_repeated_fillers()
        if fillers:
            state["warnings"].append("Removed repeated filler lines (likely music or noise): " + ", ".join(fillers))
        if not raw.plain().strip():
            raise PipelineError("No speech was detected in the recording.")
        words_per_min = raw.word_count() / (duration / 60) if duration else 0
        if res.language and res.language != "en" and (res.language_probability is None or res.language_probability >= 0.5):
            state["warnings"].append(f"Detected language '{res.language}'. This app is built for English meetings; "
                                     "results may be unreliable.")
        if words_per_min < st.min_words_per_minute:
            state["warnings"].append(f"Only {words_per_min:.0f} words per minute were recognised; the recording "
                                     "may be mostly silence, music or unclear audio.")
            segs = raw.segments
            for prev, cur in zip(segs, segs[1:]):
                if cur.start - prev.end > 20:
                    state["warnings"].append(f"No speech recognised between {prev.ts} and {cur.ts}; "
                                             "content from that part may be missing.")
        state.update(raw=raw.display(), raw_obj=raw, language=res.language, language_probability=res.language_probability)
        save("raw_transcript.txt", state["raw"])
        yield stage, say("Transcription done. Refining..."), state

        # ---- refinement (LLM 1)
        timed_stage("refine")
        llm1 = llm1 or LLM(cfg["llm1"])
        for kind, payload in refine.refine_iter(raw, llm1, prompts["refine"], st.refine_max_words, glossary):
            if kind == "progress":
                yield stage, say(payload), state
            else:
                refined, applied, warns = payload
        state.update(refined=refined.display(), refined_obj=refined, corrections=applied)
        state["warnings"] += warns
        save("refined_transcript.txt", state["refined"])
        yield stage, say(f"Refinement done ({len(applied)} correction(s)). Writing minutes..."), state

        # ---- minutes (LLM 2)
        timed_stage("minutes")
        llm2 = llm2 or LLM(cfg["llm2"])
        for kind, payload in minutes.generate_iter(refined, llm2, prompts, st):
            if kind == "progress":
                yield stage, say(payload), state
            else:
                record, warns = payload
        state["warnings"] += warns
        for name, llm in (("LLM 1", llm1), ("LLM 2", llm2)):
            for opt in getattr(llm, "dropped_options", []):
                state["warnings"].append(f"{name}: the provider did not accept the '{opt}' option, so it was not used.")

        # ---- save
        timed_stage("save")
        meta = {"run_id": run_id, "profile": cfg.get("name"), "stt_model": cfg["stt"]["model"],
                "llm1_model": cfg["llm1"]["model"], "llm2_model": cfg["llm2"]["model"],
                "audio_seconds": round(duration, 1),
                "source_link": audio_url,
                "language": res.language,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "stage_seconds": state["stage_seconds"],
                "llm_usage": {"llm1": getattr(llm1, "usage", None), "llm2": getattr(llm2, "usage", None)},
                "refinement_changes": applied, "warnings": state["warnings"]}
        state.update(record=record, meta=meta, minutes_md=render.minutes_md(record),
                     decisions_md=render.decisions_md(record), proposals_md=render.proposals_md(record),
                     tasks_md=render.tasks_md(record))
        save("meeting_minutes.md", state["minutes_md"])
        save("key_decisions.md", state["decisions_md"])
        save("proposals.md", state["proposals_md"])
        save("action_items.md", state["tasks_md"])
        save("meeting_record.md", render.full_md(record, meta))
        save("meeting_record.json", json.dumps({**record.model_dump(), "meta": meta}, indent=2, ensure_ascii=False))
        timed_stage("done")
        meta["stage_seconds"] = state["stage_seconds"]
        for w in state["warnings"]:
            log.warning("%s", w)
        log.info("usage llm1=%s llm2=%s", meta["llm_usage"]["llm1"], meta["llm_usage"]["llm2"])
        log.info("run finished in %.1fs", time.monotonic() - started)
        state["files"]["run.log"] = str(out_dir / "run.log")
        state["file_list"] = list(state["files"].values())
        yield "done", say("Done. Files are ready to download."), state
    except PipelineError as e:
        if log:
            log.error("[%s] %s", stage, e)
        yield "failed", f"[{stage}] {e}", state
    except Exception as e:  # unexpected: still show something useful
        if log:
            log.exception("unexpected error in stage %s", stage)
        yield "failed", f"[{stage}] Unexpected error: {type(e).__name__}: {e}", state
    finally:
        if log:
            close_run_logger(log)

# Non-streaming helper (scripts/tests). Returns the final state or raises PipelineError
def run_pipeline(audio_path, cfg, **kw):
    final = None
    for stage, msg, state in run_pipeline_iter(audio_path, cfg, **kw):
        final = (stage, msg, state)
    if final[0] == "failed":
        raise PipelineError(final[1])
    return final[2]
