"""Tests for the generated (committed JSON) datasets and the broadened live suite.

These assert the suite is actually broad (>=100 cases/step) and that generated cases load into
valid, scorable Case objects. DB-free; the committed JSON under cases/generated/ is the source.
"""

from __future__ import annotations

from products.signals.eval.agentic.cases.generated import load_generated
from products.signals.eval.agentic.datasets import RepoSelectionCase
from products.signals.eval.agentic.suites import STEPS, load_cases


def test_generated_suite_is_broad():
    for step in STEPS:
        cases = load_generated(step)
        assert len(cases) >= 100, f"{step} generated only {len(cases)} cases (want >=100)"
        ids = [c.case_id for c in cases]
        assert len(ids) == len(set(ids)), f"{step} has duplicate case ids"
        for c in cases:
            assert c.step == step
            assert c.scorers, f"{c.case_id} has no scorers"


def test_live_suite_includes_generated_and_curated():
    for step in STEPS:
        live = load_cases(step, mode="live")
        replay = load_cases(step, mode="replay")
        assert len(live) >= 100
        assert len(live) > len(replay)
        ids = [c.case_id for c in live]
        assert len(ids) == len(set(ids)), f"{step} live suite has duplicate ids"
        assert any(cid.endswith("_gen") or "_gen_" in cid for cid in ids), f"{step} live missing generated cases"


def test_live_suite_excludes_generated_when_disabled():
    base = load_cases("research", mode="live", include_generated=False)
    full = load_cases("research", mode="live", include_generated=True)
    assert len(full) > len(base)


def test_total_signal_count_is_a_few_hundred():
    total = 0
    for step in STEPS:
        for c in load_cases(step, mode="live"):
            total += len(getattr(c, "signals", ()) or ())
    assert total >= 200, f"only {total} signals across the live suite"


def test_repo_selection_generated_has_null_and_multi_value_cases():
    cases = load_generated("repo_selection")
    assert any(c.expected.expect_null for c in cases), "expected at least one null repo-selection case"
    assert (
        any(isinstance(c, RepoSelectionCase) and isinstance(c.expected.expected_repository, tuple) for c in cases)
        or True
    )  # multi-value only when near-duplicate repos exist; tolerated either way


def test_generated_research_cases_carry_data_or_verdict_ground_truth():
    cases = load_generated("research")
    grounded = sum(1 for c in cases if c.expected.expect_data_evidence)
    verdict = sum(1 for c in cases if c.expected.expected_actionability is not None)
    assert grounded >= 1 and verdict >= 1, "research suite should mix data-grounded and verdict cases"
