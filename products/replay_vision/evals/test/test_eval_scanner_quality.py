from __future__ import annotations

import time
import random
import asyncio
import datetime as dt
from typing import Any

import pytest

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.replay_vision.backend.temporal.types import ScannerSnapshot
from products.replay_vision.evals import collector
from products.replay_vision.evals.collector import _parse_ts, build_llm_inputs, order_candidates
from products.replay_vision.evals.dataset import GoldenCase
from products.replay_vision.evals.eval_scanner_quality import build_case
from products.replay_vision.evals.scorers import (
    LabeledOutcome,
    OutputStability,
    ScanCompleted,
    ScoreAlignment,
    SummaryAlignment,
)


def _eval(scorer: Scorer, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
    # eval_async is the entrypoint the harness dispatches through.
    return asyncio.run(scorer.eval_async(output, expected))


def _monitor_output(verdict: str) -> dict[str, Any]:
    return {"model_output": {"verdict": verdict, "reasoning": "r", "confidence": 0.9}}


def _golden(
    scanner_type: str,
    label_is_correct: bool | None,
    recorded_output: dict[str, Any],
    case_id: str = "0199aaaa-0000-7000-8000-000000000001",
    scale: dict[str, Any] | None = None,
) -> GoldenCase:
    scanner_config: dict[str, Any] = {"prompt": "watch for rage clicks"}
    if scanner_type == "classifier":
        scanner_config["tags"] = ["a", "b"]
    if scanner_type == "scorer":
        scanner_config["scale"] = {"min": 1, "max": 5} if scale is None else scale
    return GoldenCase(
        case_id=case_id,
        scanner_id="s1",
        scanner_name="Test scanner",
        scanner_type=scanner_type,
        session_id="sess-1",
        team_id=2,
        team_name="Team",
        snapshot=ScannerSnapshot(
            name="Test scanner",
            scanner_type=scanner_type,
            scanner_version=1,
            model="gemini-3.6-flash",
            provider="google",
            emits_signals=False,
            scanner_config=scanner_config,
        ),
        recorded_output=recorded_output,
        label_is_correct=label_is_correct,
        collected_at="2026-07-30T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    "is_correct,fresh_verdict,expected_score,expected_outcome",
    [
        (True, "yes", 1.0, "kept"),
        (True, "no", 0.0, "regressed"),
        (False, "no", 1.0, "fixed"),
        (False, "yes", 0.0, "still_wrong"),
    ],
)
def test_labeled_outcome_scores_thumbs_semantics(
    is_correct: bool, fresh_verdict: str, expected_score: float, expected_outcome: str
) -> None:
    expected = {"labeled_outcome": {"is_correct": is_correct, "recorded_primary": "Verdict: yes"}}
    score = _eval(LabeledOutcome(), _monitor_output(fresh_verdict), expected)
    assert score.score == expected_score
    assert score.metadata["outcome"] == expected_outcome


@pytest.mark.parametrize(
    "scorer",
    [LabeledOutcome(), OutputStability(), ScoreAlignment()],
    ids=lambda s: s._name(),
)
def test_inapplicable_cases_skip_instead_of_failing(scorer: Any) -> None:
    # None means "skipped" in the aggregate; returning 0.0 here would silently drag every
    # experiment's mean down for cases the scorer was never meant to grade.
    score = _eval(scorer, _monitor_output("yes"), {})
    assert score.score is None


def test_labeled_outcome_fails_when_scan_produced_nothing() -> None:
    expected = {"labeled_outcome": {"is_correct": True, "recorded_primary": "Verdict: yes"}}
    score = _eval(LabeledOutcome(), {"model_output": None, "error": "boom"}, expected)
    assert score.score == 0.0


@pytest.mark.parametrize(
    "fresh,expected_score",
    [
        (3.0, 1.0),
        (4.0, 0.75),
        (1.0, 0.5),
        (None, 0.0),
    ],
)
def test_score_alignment_normalizes_distance_by_scale(fresh: float | None, expected_score: float) -> None:
    expected = {"score_alignment": {"recorded_score": 3.0, "scale_min": 1.0, "scale_max": 5.0}}
    output = {"model_output": {"score": fresh} if fresh is not None else None}
    score = _eval(ScoreAlignment(), output, expected)
    assert score.score == pytest.approx(expected_score)


def test_score_alignment_skips_zero_width_scale() -> None:
    # min == max used to divide by zero and kill the case; a degenerate scale is inapplicable, not failing.
    expected = {"score_alignment": {"recorded_score": 3.0, "scale_min": 3.0, "scale_max": 3.0}}
    score = _eval(ScoreAlignment(), {"model_output": {"score": 3.0}}, expected)
    assert score.score is None
    assert score.metadata["reason"] == "zero-width scale"


@pytest.mark.parametrize(
    "scale,expected_bounds",
    [
        ({}, (0.0, 1.0)),
        ({"min": 1, "max": 5}, (1, 5)),
        ({"min": 1}, None),
        ({"max": 5}, None),
    ],
)
def test_build_case_only_defaults_scale_bounds_as_a_pair(
    scale: dict[str, Any], expected_bounds: tuple[float, float] | None
) -> None:
    case = build_case(_golden("scorer", None, {"score": 3.0}, scale=scale))
    spec = case.expected.get("score_alignment")
    if expected_bounds is None:
        assert spec is None
    else:
        assert spec is not None
        assert (spec["scale_min"], spec["scale_max"]) == expected_bounds


def test_output_stability_compares_primary_outcomes() -> None:
    expected = {"output_stability": {"recorded_primary": "Verdict: yes"}}
    assert _eval(OutputStability(), _monitor_output("yes"), expected).score == 1.0
    assert _eval(OutputStability(), _monitor_output("no"), expected).score == 0.0


def test_scan_completed_fails_on_schema_breakage() -> None:
    assert _eval(ScanCompleted(), _monitor_output("yes"), {}).score == 1.0
    failed = _eval(ScanCompleted(), {"model_output": None, "error": "required step rejected"}, {})
    assert failed.score == 0.0
    assert "rejected" in failed.metadata["reason"]


def test_summary_alignment_prepare_gates_on_reference() -> None:
    # _prepare directly: going through eval_async would call the LLM judge.
    judge = SummaryAlignment()
    skipped = judge._prepare(_monitor_output("yes"), {})
    assert isinstance(skipped, Score)
    assert skipped.score is None
    spec = {"summary_alignment": {"reference": {"title": "t", "summary": "s"}}}
    no_output = judge._prepare({"model_output": None}, spec)
    assert isinstance(no_output, Score)
    assert no_output.score == 0.0
    prepared = judge._prepare({"model_output": {"title": "t2", "summary": "s2"}}, spec)
    assert isinstance(prepared, dict)
    assert "t2" in prepared["output"]
    assert "t" in prepared["expected"]


@pytest.mark.parametrize(
    "scanner_type,label_is_correct,recorded_output,expected_key",
    [
        ("monitor", True, {"verdict": "yes"}, "labeled_outcome"),
        ("monitor", None, {"verdict": "yes"}, "output_stability"),
        ("classifier", False, {"tags": ["a"]}, "labeled_outcome"),
        ("scorer", None, {"score": 3.0}, "score_alignment"),
        ("scorer", True, {"score": 3.0}, "score_alignment"),
        ("summarizer", None, {"title": "t", "summary": "s"}, "summary_alignment"),
    ],
)
def test_build_case_routes_to_the_right_scorer(
    scanner_type: str, label_is_correct: bool | None, recorded_output: dict[str, Any], expected_key: str
) -> None:
    case = build_case(_golden(scanner_type, label_is_correct, recorded_output))
    assert list(case.expected.keys()) == [expected_key]


@pytest.mark.parametrize(
    "scanner_type,recorded_output",
    [
        ("scorer", {"score": 3.0}),
        ("summarizer", {"title": "t", "summary": "s"}),
    ],
)
def test_build_case_never_trusts_a_thumbs_downed_reference(scanner_type: str, recorded_output: dict[str, Any]) -> None:
    case = build_case(_golden(scanner_type, False, recorded_output))
    assert case.expected == {}


def test_case_names_do_not_collide_on_shared_uuid_prefix() -> None:
    # UUIDv7 ids minted in the same minute share their leading characters; a truncated name
    # collapsed such cases into one dataset entry, scoring one against another session's video.
    goldens = [
        _golden("monitor", True, {"verdict": "yes"}, case_id="0199aaaa-0000-7000-8000-000000000001"),
        _golden("monitor", True, {"verdict": "yes"}, case_id="0199aaaa-0000-7000-8000-000000000002"),
    ]
    cases = [build_case(golden) for golden in goldens]
    assert cases[0].name != cases[1].name
    golden_by_case_id = {case.metadata["case_id"]: golden for case, golden in zip(cases, goldens)}
    assert len(golden_by_case_id) == len(goldens)


def test_order_candidates_puts_labeled_first_per_type() -> None:
    def candidate(scanner_type: str, obs_id: str, labeled: bool) -> dict[str, Any]:
        observation: dict[str, Any] = {"id": obs_id, "label": {"is_correct": True} if labeled else None}
        return {"observation": observation, "scanner": {}, "scanner_type": scanner_type}

    candidates = [
        candidate("monitor", "u1", False),
        candidate("monitor", "l1", True),
        candidate("monitor", "u2", False),
        candidate("scorer", "u3", False),
        candidate("monitor", "l2", True),
    ]
    ordered = order_candidates(candidates, random.Random(42))
    monitor_ids = [c["observation"]["id"] for c in ordered["monitor"]]
    assert monitor_ids[:2] == ["l1", "l2"]
    assert sorted(monitor_ids[2:]) == ["u1", "u2"]
    assert [c["observation"]["id"] for c in ordered["scorer"]] == ["u3"]
    assert ordered == order_candidates(candidates, random.Random(42))


def test_parse_ts_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="no timezone"):
        _parse_ts("2026-08-01T12:00:00")
    assert _parse_ts("2026-08-01T12:00:00+12:00") == dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=dt.UTC)


_SESSION_START = "2026-08-01T12:00:00+12:00"
_SESSION_END = "2026-08-01T12:05:00+12:00"


class _FakeApi:
    project_id = 2

    def hogql(self, query: str, values: dict[str, Any] | None = None) -> list[list[Any]]:
        if "session_replay_events" in query:
            return [["d1", _SESSION_START, _SESSION_END, 3, 4, 5, 60_000, 0, "https://example.com/a"]]
        # Field order: DEFAULT_EVENT_FIELDS + _EXTRA_FIELDS.
        return [
            [
                "$pageview",
                "2026-08-01T12:00:10+12:00",
                "",
                [],
                [],
                "w1",
                "https://example.com/a",
                None,
                "00000000-0000-0000-0000-00000000000a",
                [],
                [],
                [],
            ],
            [
                "$autocapture",
                "2026-08-01T12:01:10+12:00",
                "",
                [],
                [],
                "w1",
                "https://example.com/b",
                "click",
                "00000000-0000-0000-0000-00000000000b",
                [],
                [],
                [],
            ],
        ]


def test_event_offsets_do_not_depend_on_local_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    def offsets_under(tz: str) -> dict[str, int]:
        monkeypatch.setenv("TZ", tz)
        time.tzset()
        inputs = build_llm_inputs(_FakeApi(), 2, "sess-1")  # type: ignore[arg-type]
        assert inputs is not None
        return inputs.event_timestamps

    try:
        utc_offsets = offsets_under("UTC")
        nz_offsets = offsets_under("Pacific/Auckland")
    finally:
        monkeypatch.undo()
        time.tzset()
    assert utc_offsets == nz_offsets
    assert utc_offsets["00000000-0000-0000-0000-00000000000a"] == 10_000
    assert utc_offsets["00000000-0000-0000-0000-00000000000b"] == 70_000


class _PagedApi:
    def __init__(self, pages: list[list[list[Any]]]) -> None:
        self._pages = pages
        self._served = 0

    def hogql(self, query: str, values: dict[str, Any] | None = None) -> list[list[Any]]:
        page = self._pages[self._served] if self._served < len(self._pages) else []
        self._served += 1
        return page


def test_fetch_events_caps_total_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector, "_EVENTS_PER_PAGE", 2)
    monkeypatch.setattr(collector, "_MAX_TOTAL_EVENT_ROWS", 5)
    row = ["$pageview", _SESSION_START, "u"]
    api = _PagedApi([[row, row], [row, row], [row, row], [row, row]])
    start = dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=dt.UTC)
    fetched = collector._fetch_events(api, "sess-1", start, start + dt.timedelta(minutes=5))  # type: ignore[arg-type]
    assert len(fetched.rows) == 5
    assert fetched.truncated
