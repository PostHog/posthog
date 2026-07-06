"""Tests for metric aggregation and PostHog capture wiring."""

from __future__ import annotations

from products.signals.eval.agentic.metrics import EVAL_SOURCE, aggregate, capture_suite
from products.signals.eval.agentic.results import CaseResult, SuiteResult
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


def test_case_passed_semantics():
    suite = _suite()
    assert suite.cases[0].passed is True  # all ok-scores passed
    assert suite.cases[1].passed is False  # an ok-score failed


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
