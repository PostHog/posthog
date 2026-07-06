"""Tests for metric aggregation, PostHog capture wiring, and run orchestration helpers."""

from __future__ import annotations

import io

from parameterized import parameterized

from products.signals.eval.agentic.datasets import EvalCase
from products.signals.eval.agentic.metrics import EVAL_SOURCE, aggregate, capture_suite, print_report
from products.signals.eval.agentic.results import CaseResult, SuiteResult
from products.signals.eval.agentic.run import stable_sample
from products.signals.eval.agentic.scoring import Score


def _suite() -> SuiteResult:
    return SuiteResult(
        step="research",
        mode="replay",
        cases=[
            CaseResult(
                case_id="c1",
                step="research",
                mode="replay",
                scores=[
                    Score.boolean("actionability_correct", True),
                    Score.numeric("code_paths_found", 1.0, threshold=1.0),
                ],
            ),
            CaseResult(
                case_id="c2",
                step="research",
                mode="replay",
                scores=[
                    Score.boolean("actionability_correct", False),
                    Score.numeric("code_paths_found", 0.0, threshold=1.0),
                    Score(name="judge", value=0.0, passed=False, status="skipped"),
                ],
            ),
        ],
    )


def test_aggregate_counts_pass_rate_and_mean_excluding_non_ok():
    agg = aggregate(_suite())
    assert agg["actionability_correct"]["n"] == 2
    assert agg["actionability_correct"]["pass_rate"] == 0.5
    # skipped judge score is excluded from aggregation entirely
    assert "judge" not in agg
    assert abs(agg["code_paths_found"]["mean"] - 0.5) < 1e-9


@parameterized.expand(
    [
        ("all_ok_pass", [Score.boolean("a", True)], None, True),
        ("ok_fail", [Score.boolean("a", False)], None, False),
        (
            "skipped_excluded",
            [Score.boolean("a", True), Score(name="j", value=0.0, passed=False, status="skipped")],
            None,
            True,
        ),
        ("errored_scorer_fails_case", [Score.boolean("a", True), Score.errored("j", "boom")], None, False),
        ("runner_error_fails_case", [], "RunnerError: sandbox down", False),
    ]
)
def test_case_passed_semantics(_name, scores, error, expected):
    case = CaseResult(case_id="c", step="research", mode="replay", scores=scores, error=error)
    assert case.passed is expected


class _FakeClient:
    def __init__(self):
        self.events: list[dict] = []

    def capture(self, *, distinct_id, event, properties):
        self.events.append({"distinct_id": distinct_id, "event": event, "properties": properties})


def test_capture_suite_emits_ai_evaluation_events():
    client = _FakeClient()
    capture_suite(client, _suite())
    assert client.events, "expected captured events"
    assert all(e["event"] == "$ai_evaluation" for e in client.events)
    sources = {e["properties"]["$ai_eval_source"] for e in client.events}
    assert sources == {EVAL_SOURCE}
    names = {e["properties"]["$ai_metric_name"] for e in client.events}
    assert "actionability_correct" in names


def test_capture_suite_emits_errored_event_for_crashed_case():
    client = _FakeClient()
    suite = SuiteResult(
        step="research",
        mode="live",
        cases=[CaseResult(case_id="boom", step="research", mode="live", error="RunnerError: sandbox down")],
    )
    capture_suite(client, suite, run_id="r1")
    assert len(client.events) == 1
    props = client.events[0]["properties"]
    assert props["$ai_evaluation_result"] == 0.0
    assert props["$ai_status"] == "error"
    assert props["$ai_error_message"] == "RunnerError: sandbox down"
    assert props["$ai_reasoning"] == "RunnerError: sandbox down"


def test_capture_suite_stamps_run_identity_and_runtime():
    client = _FakeClient()
    suite = _suite()
    suite.cases[0].runtime = {"adapter": "codex", "model": "gpt-5.5", "effort": "high"}
    capture_suite(client, suite, run_id="run-1")
    assert all(e["properties"]["$ai_eval_run_id"] == "run-1" for e in client.events)
    assert all(e["properties"]["$ai_eval_mode"] == "replay" for e in client.events)
    c1 = [e for e in client.events if e["properties"]["$ai_experiment_item_name"] == "c1"]
    assert c1 and all(e["properties"]["$ai_model"] == "gpt-5.5" for e in c1)
    assert c1[0]["properties"]["$ai_runtime_adapter"] == "codex"
    c2 = [e for e in client.events if e["properties"]["$ai_experiment_item_name"] == "c2"]
    assert c2 and all("$ai_model" not in e["properties"] for e in c2)


def test_print_report_shows_run_id_runtime_and_scorer_error():
    suite = _suite()
    suite.cases[0].runtime = {"adapter": "codex", "model": "gpt-5.5", "effort": "high"}
    suite.cases[1].scores.append(Score.errored("crashy", "AttributeError: nope"))
    buf = io.StringIO()
    print_report(suite, run_id="run-9", file=buf)
    out = buf.getvalue()
    assert "run_id=run-9" in out
    assert "codex/gpt-5.5/high" in out
    assert "AttributeError: nope" in out
    assert "scores errored: 1, skipped: 1" in out


def test_stable_sample_membership_survives_added_case():
    cases = [EvalCase(case_id=f"case-{i}", step="research") for i in range(8)]
    base = stable_sample(cases, 4, 1337)
    assert [c.case_id for c in stable_sample(cases, 4, 1337)] == [c.case_id for c in base]
    grown = stable_sample([*cases, EvalCase(case_id="case-new", step="research")], 4, 1337)
    # the new case can displace at most one member; the rest of the subset must be unchanged
    assert len({c.case_id for c in base} & {c.case_id for c in grown}) >= 3
