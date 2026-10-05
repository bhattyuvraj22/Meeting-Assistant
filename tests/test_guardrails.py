from pipeline import guardrails
from pipeline.schema import UNSPECIFIED, Decision, Record, Task
from pipeline.settings import Settings
from pipeline.transcript import Transcript

TR = Transcript.from_text(
    "Priya, can you send the QA report by Thursday?\n"
    "Sure, I'll do that.\n"
    "Maybe we should move to the new server.\n"
    "Someone should probably look into the API costs at some point.")

FAR = Transcript.from_text(
    "Rahul presented the roadmap.\n"
    "Thanks.\n"
    "Next item.\n"
    "Okay.\n"
    "Can someone fix the login timeout bug by Friday?\n"
    "I'll do it.")


# helper (not a test): builds a Record from the given items, runs the guardrails on TR, returns (record, warnings)
def run(**items):
    rec = Record(summary="s", **items)
    warnings = guardrails.apply(rec, TR, Settings())
    return rec, warnings


# a genuine task (real owner, real deadline, real quote) must pass through unchanged
def test_real_task_is_kept_unchanged():
    rec, _ = run(tasks=[Task(description="Send the QA report", owner="Priya", deadline="by Thursday",
                             status="assigned", evidence="Priya, can you send the QA report by Thursday?")])
    t = rec.tasks[0]
    assert (t.owner, t.deadline, t.status) == ("Priya", "by Thursday", "assigned")


# a task whose quote is not in the transcript must be dropped, with a warning
def test_fabricated_task_is_dropped():
    rec, warnings = run(tasks=[Task(description="Sign vendor contract", status="assigned",
                                    evidence="The vendor contract was signed for twelve months with Acme Corp.")])
    assert rec.tasks == [] and any("Dropped task" in w for w in warnings)


# an owner and a date that were never said must be reset to "unspecified"
def test_invented_owner_and_date_become_unspecified():
    rec, _ = run(tasks=[Task(description="Send the QA report", owner="Rahul", deadline="2026-10-09",
                             status="assigned", evidence="Priya, can you send the QA report by Thursday?")])
    assert rec.tasks[0].owner == UNSPECIFIED and rec.tasks[0].deadline == UNSPECIFIED


# a tentative "someone should probably..." task marked assigned must become "suggested"
def test_hedged_task_becomes_suggested():
    rec, _ = run(tasks=[Task(description="Look into API costs", status="assigned",
                             evidence="Someone should probably look into the API costs at some point.")])
    assert rec.tasks[0].status == "suggested"


# a tentative "maybe we should..." decision must move to proposals
def test_hedged_decision_becomes_proposal():
    rec, _ = run(decisions=[Decision(decision="Move to the new server",
                                     evidence="Maybe we should move to the new server.")])
    assert rec.decisions == [] and len(rec.proposals) == 1


# an owner named far from the task (outside the nearby lines) is not trusted; the stated deadline stays
def test_owner_named_elsewhere_is_not_trusted():
    rec = Record(summary="s", tasks=[Task(description="Fix the login timeout bug", owner="Rahul",
                                          deadline="by Friday", status="assigned",
                                          evidence="Can someone fix the login timeout bug by Friday? I'll do it.")])
    guardrails.apply(rec, FAR, Settings())
    assert rec.tasks[0].owner == UNSPECIFIED and rec.tasks[0].deadline == "by Friday"


# a quote that drops "not" or changes 2.3 to 2.4 must be rejected, leaving no decisions
def test_flipped_negation_or_number_is_dropped():
    tr = Transcript.from_text("We will not ship on Friday.\nRelease 2.3 ships next month.")
    rec = Record(summary="s", decisions=[
        Decision(decision="Ship on Friday", evidence="We will ship on Friday."),
        Decision(decision="Release 2.4 ships next month", evidence="Release 2.4 ships next month.")])
    guardrails.apply(rec, tr, Settings())
    assert rec.decisions == []


# a hedge followed by clear agreement ("Yes, agreed") stays a decision
def test_confirmed_after_hedge_stays_a_decision():
    tr = Transcript.from_text("Maybe we launch on Monday? Yes, agreed, Monday it is.")
    rec = Record(summary="s", decisions=[Decision(decision="Launch on Monday",
                                                  evidence="Maybe we launch on Monday? Yes, agreed, Monday it is.")])
    guardrails.apply(rec, tr, Settings())
    assert len(rec.decisions) == 1 and rec.proposals == []


# a number in the summary that was never said ("5 engineers") must be flagged with a warning
def test_invented_number_in_summary_is_flagged():
    rec = Record(summary="The team will hire 5 engineers.")
    warnings = guardrails.apply(rec, TR, Settings())
    assert any("5" in w and "summary" in w for w in warnings)