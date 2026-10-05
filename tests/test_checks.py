from pipeline.checks import (
    deadline_supported,
    is_hedged,
    owner_supported,
    refine_ok,
    validate_correction,
)
from pipeline.schema import Task
from pipeline.settings import DEFAULT_HEDGES
from pipeline.transcript import Transcript


# a correct term fix ("cube flow" -> "Kubeflow") must be accepted
def test_good_term_fix_is_accepted():
    assert validate_correction("We deploy with cube flow today.", "cube flow", "Kubeflow")[0]


# a fix that changes a number (40 -> 14, 2 -> 3) must be rejected
def test_number_change_is_rejected():
    assert not validate_correction("The budget is 40 lakh.", "40 lakh", "14 lakh")[0]
    assert not refine_ok("We ship 2 builds.", "We ship 3 builds.")[0]


# a fix that removes "not" (flips the meaning) must be rejected
def test_negation_change_is_rejected():
    assert not validate_correction("We are not moving.", "not moving", "moving")[0]


# swapping one person's name for another (Rahul -> Priya) must be blocked
def test_name_swap_is_blocked():
    assert not validate_correction("Then Rahul will review it.", "Rahul", "Priya")[0]


# a deadline is valid only if it was actually said; an invented date is not
def test_deadlines_must_be_spoken():
    assert deadline_supported("by Friday", "please send it by Friday")
    assert not deadline_supported("2026-10-10", "please send it by Friday")


# an owner is valid only if the name was spoken; "unspecified" is always fine
def test_owners_must_be_spoken():
    assert owner_supported("Priya", "Priya will do it")
    assert not owner_supported("Rahul", "Priya will do it")
    assert owner_supported("unspecified", "anything")


# tentative wording ("should probably") is hedged; a clear instruction is not
def test_hedge_detection():
    assert is_hedged("Someone should probably look into it", DEFAULT_HEDGES)
    assert not is_hedged("Priya, send the report by Friday", DEFAULT_HEDGES)


# a Task with no status defaults to "suggested"
def test_missing_status_is_suggested():
    assert Task(description="Look into costs").status == "suggested"


# normal replies ("Yes.", "Okay.") are never removed as filler
def test_filler_filter_keeps_real_replies():
    t = Transcript.from_text("Ship Friday?\nYes.\nAgreed then.\nYes.\nPriya does QA.\nYes.\nOkay.\nOkay.\nOkay.")
    kept, removed = t.without_repeated_fillers()
    assert len(kept) == len(t) and removed == []


# the same junk line repeated 3+ times in a row (a jingle) is removed
def test_filler_filter_drops_jingle_runs():
    t = Transcript.from_text("Hello all.\nEmergent AI.\nEmergent AI.\nEmergent AI.\nLet's start.")
    kept, removed = t.without_repeated_fillers()
    assert len(kept) == 2 and removed == ["emergent ai"]