import json
import shutil
import subprocess

import pytest

from pipeline.errors import PipelineError
from pipeline.orchestrator import run_pipeline
from pipeline.transcript import SttResult, Transcript

# checks ffmpeg is installed or not, if not installed then skip the tests
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

SPOKEN = """Okay, let's start the sprint review.
We deploy the model with cube flow on the cluster.
Should we ship release 2.3 on Friday?
Yes.
So it's agreed, we ship release 2.3 on Friday.
Yes.
Priya, can you send the QA report by Thursday?
Sure, I'll do that.
Someone should probably look into the API costs at some point.
Yes."""

MINUTES = {
    "summary": "Sprint review.",
    "minutes": [{"topic": "Release", "points": ["Release 2.3 ships on Friday."]}],
    "decisions": [{"decision": "Ship release 2.3 on Friday",
                   "evidence": "So it's agreed, we ship release 2.3 on Friday."}],
    "proposals": [],
    "tasks": [
        {"description": "Send the QA report", "owner": "Priya", "deadline": "by Thursday", "status": "assigned",
         "evidence": "Priya, can you send the QA report by Thursday?"},
        {"description": "Look into API costs", "owner": "Rahul", "deadline": "2026-10-10", "status": "assigned",
         "evidence": "Someone should probably look into the API costs at some point."},
        {"description": "Sign vendor contract", "status": "assigned",
         "evidence": "The vendor contract was signed for twelve months with Acme Corp."},
    ],
}
CFG = {"name": "test", "stt": {"model": "fake-stt"}, "llm1": {"model": "fake-1"},
       "llm2": {"model": "fake-2"}, "settings": {}}

# a pretend AI that always gives the same json reply, so we can test the pipeline without calling a real LLM
class FakeLLM:
    def __init__(self, reply):
        self.reply = json.dumps(reply)

    def chat(self, system, user, json_mode=False):
        return self.reply

# a pretend speech-to-text that returns the script
def fake_stt(path, cfg, glossary):
    return SttResult(Transcript.from_text(SPOKEN), "en", 0.99)

# Creates a real 5-second audio file , because the pipeline's audio check needs a real, readable file, even though the content doesn't matter
def make_audio(path, seconds=5):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
                   capture_output=True, check=True)
    return path

# Runs the pipeline with all the fakes plugged in
def run(audio, tmp_path):
    return run_pipeline(audio, CFG, out_root=str(tmp_path / "out"), stt_fn=fake_stt,
                        llm1=FakeLLM({"corrections": [{"line": 2, "from": "cube flow", "to": "Kubeflow"}]}),
                        llm2=FakeLLM(MINUTES))

# runs a normal meeting through the pipeline and checks that the results are right.
def test_end_to_end(tmp_path):
    state = run(make_audio(tmp_path / "meeting.wav"), tmp_path)
    assert state["raw"].count("Yes.") == 3                       # filler bug regression
    assert "cube flow" in state["raw"] and "Kubeflow" in state["refined"]
    tasks = state["record"].tasks
    assert len(tasks) == 2                                        # fabricated task dropped
    assert (tasks[1].owner, tasks[1].deadline, tasks[1].status) == ("unspecified", "unspecified", "suggested")
    data = json.loads(open(state["files"]["meeting_record.json"], encoding="utf-8").read())
    assert [t["status"] for t in data["tasks"]] == [t.status for t in tasks]
    for name in ("raw_transcript.txt", "refined_transcript.txt", "meeting_minutes.md",
                 "key_decisions.md", "action_items.md", "meeting_record.md"):
        assert name in state["files"]


@pytest.mark.parametrize("name,content,error", [
    ("empty.wav", b"", "empty"),
    ("notes.pdf", b"%PDF-1.4", "Unsupported"),
    ("broken.mp3", b"not really audio" * 100, "could not be read"),
])
# feeds the app three bad files and checks that each one gives a clear error message instead of crashing.
def test_bad_files_fail_clearly(tmp_path, name, content, error):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(PipelineError, match=error):
        run(path, tmp_path)