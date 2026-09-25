"""Unit tests for the grading logic the experiments evals use.

Exercises ``FirstUpdateMetricShape`` and the metric-shape validators from
``products/posthog_ai/evals/experiments/scorers.py``, and the setup-inference checks from
``setup_scorers.py``, directly, lightweight as it's given hand-built metric dicts and
synthetic ACP log lines, no sandboxed stack.
"""

from __future__ import annotations

import json

import pytest

from products.posthog_ai.eval_harness.scorers.contract import Score
from products.posthog_ai.evals.experiments.scorers import (
    FirstUpdateMetricShape,
    validate_ratio_revenue_metric,
    validate_retention_metric,
)
from products.posthog_ai.evals.experiments.setup_scorers import (
    BUCKETING_DEFAULT,
    BUCKETING_PERSIST_OR_DEVICE_ID,
    CreatedExperiment,
    bucketing_fits,
    closing_texts,
    primary_metric_matches,
    windows_without_unit,
)


def _ratio(numerator: dict, denominator: dict | None = None) -> dict:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "ratio",
        "numerator": numerator,
        "denominator": denominator or {"kind": "EventsNode", "event": "$pageview"},
    }


def _retention(**overrides) -> dict:
    metric = {
        "kind": "ExperimentMetric",
        "metric_type": "retention",
        "start_event": {"kind": "EventsNode", "event": "$pageview"},
        "completion_event": {"kind": "EventsNode", "event": "uploaded_file"},
        "retention_window_start": 0,
        "retention_window_end": 7,
        "retention_window_unit": "day",
        "start_handling": "first_seen",
    }
    metric.update(overrides)
    return metric


RATIO_SUM = _ratio({"kind": "EventsNode", "event": "purchase_completed", "math": "sum", "math_property": "revenue"})
RATIO_IS_SET = _ratio(
    {
        "kind": "EventsNode",
        "event": "purchase_completed",
        "properties": [{"key": "revenue", "value": "is_set", "operator": "is_set", "type": "event"}],
    }
)


@pytest.mark.parametrize(
    "metrics,expected_pass",
    [
        ([RATIO_SUM], True),
        ([{"metric_type": "mean", "source": {}}, RATIO_SUM], True),  # ratio found alongside other metrics
        ([RATIO_IS_SET], False),  # is_set filter does not aggregate
        ([_ratio({"kind": "EventsNode", "event": "purchase_completed", "math_property": "revenue"})], False),  # no math
        ([_ratio({"kind": "EventsNode", "event": "purchase_completed", "math": "sum"})], False),  # no math_property
        (
            [_ratio({"kind": "EventsNode", "event": "purchase_completed", "math": "sum", "math_property": "amount"})],
            False,
        ),
        ([{"metric_type": "mean", "source": {}}], False),  # no ratio metric present
    ],
    ids=["sum", "sum-among-others", "is-set", "missing-math", "missing-math-property", "wrong-property", "no-ratio"],
)
def test_validate_ratio_revenue_metric(metrics: list[dict], expected_pass: bool) -> None:
    passed, reason = validate_ratio_revenue_metric(metrics)
    assert passed is expected_pass
    assert isinstance(reason, str) and reason


@pytest.mark.parametrize(
    "metrics,expected_pass",
    [
        ([_retention()], True),
        ([{"metric_type": "ratio"}, _retention()], True),
        ([_retention(retention_window_start=None)], True),  # required key present even if value is None
        ([{k: v for k, v in _retention().items() if k not in ("retention_window_start", "start_handling")}], False),
        ([{k: v for k, v in _retention().items() if k != "start_handling"}], False),  # missing a required field
        ([{k: v for k, v in _retention().items() if k != "retention_window_start"}], False),
        ([{"metric_type": "ratio"}], False),  # no retention metric present
    ],
    ids=[
        "full",
        "among-others",
        "present-none",
        "missing-both",
        "missing-start-handling",
        "missing-window-start",
        "no-retention",
    ],
)
def test_validate_retention_metric(metrics: list[dict], expected_pass: bool) -> None:
    passed, reason = validate_retention_metric(metrics)
    assert passed is expected_pass
    assert isinstance(reason, str) and reason


def _acp_line(update: dict) -> str:
    return json.dumps(
        {
            "notification": {"method": "session/update", "params": {"update": update}},
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )


def _tool_call(call_id: str, tool_name: str, raw_input: dict, *, is_error: bool = False) -> list[str]:
    """Emit the tool_call + completing tool_call_update pair for one tool invocation."""
    return [
        _acp_line(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "_meta": {"claudeCode": {"toolName": tool_name}},
                "rawInput": raw_input,
            }
        ),
        _acp_line(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": "failed" if is_error else "completed",
                "rawOutput": "error" if is_error else "ok",
            }
        ),
    ]


def _output(*tool_calls: list[str]) -> dict:
    lines: list[str] = []
    for call in tool_calls:
        lines.extend(call)
    return {"raw_log": "\n".join(lines), "prompt": "add a metric"}


def _score(output: dict | None, validator=validate_ratio_revenue_metric) -> Score:
    return FirstUpdateMetricShape()._run_eval_sync(output, expected={"first_update_metric_shape": validator})


def test_first_update_skipped_when_validator_absent() -> None:
    score = FirstUpdateMetricShape()._run_eval_sync(_output(), expected={})
    assert score.score == 1.0
    assert score.metadata.get("skipped") is True


def test_first_update_no_output() -> None:
    assert _score(None).score == 0.0


def test_first_update_never_called() -> None:
    score = _score(_output(_tool_call("c1", "experiment-get", {})))
    assert score.score == 0.0
    assert "never called" in score.metadata["reason"]


def test_first_update_correct_first_try() -> None:
    score = _score(_output(_tool_call("c1", "mcp__posthog__experiment-update", {"metrics": [RATIO_SUM]})))
    assert score.score == 1.0
    assert score.metadata["call_count"] == 1


def test_first_update_only_first_call_counts() -> None:
    # Wrong on the first call, recovered on the second — the first-try methodology must still fail it.
    score = _score(
        _output(
            _tool_call("c1", "experiment-update", {"metrics": [RATIO_IS_SET]}, is_error=True),
            _tool_call("c2", "experiment-update", {"metrics": [RATIO_SUM]}),
        )
    )
    assert score.score == 0.0
    assert score.metadata["call_count"] == 2
    assert score.metadata["first_call_is_error"] is True


def test_first_update_error_call_still_graded_on_shape() -> None:
    # A correctly shaped payload that the API rejected for other reasons still counts as right shape.
    score = _score(_output(_tool_call("c1", "experiment-update", {"metrics": [RATIO_SUM]}, is_error=True)))
    assert score.score == 1.0


def test_first_update_reads_metrics_secondary() -> None:
    score = _score(_output(_tool_call("c1", "experiment-update", {"metrics_secondary": [RATIO_SUM]})))
    assert score.score == 1.0


def test_first_update_no_metrics_array() -> None:
    score = _score(_output(_tool_call("c1", "experiment-update", {"name": "renamed"})))
    assert score.score == 0.0
    assert "no metrics array" in score.metadata["reason"]


def _created(**overrides) -> CreatedExperiment:
    fields: dict = {
        "experiment_id": 1,
        "new_experiment_count": 1,
        "inline_primary": (),
        "inline_secondary": (),
        "linked_primary": (),
        "linked_secondary": (),
        "linked_saved_metric_ids": (),
        "running_time_calculation": {},
        "ensure_experience_continuity": False,
        "bucketing_identifier": "distinct_id",
        "new_flag_ids": (7,),
        "experiment_flag_id": 7,
    }
    return CreatedExperiment(**(fields | overrides))


@pytest.mark.parametrize(
    "mode,continuity,bucketing,expected_pass",
    [
        (BUCKETING_DEFAULT, False, "distinct_id", True),
        (BUCKETING_DEFAULT, True, "distinct_id", False),
        (BUCKETING_DEFAULT, False, "device_id", False),
        (BUCKETING_PERSIST_OR_DEVICE_ID, True, "distinct_id", True),
        (BUCKETING_PERSIST_OR_DEVICE_ID, False, "device_id", True),
        (BUCKETING_PERSIST_OR_DEVICE_ID, False, "distinct_id", False),
    ],
)
def test_bucketing_fits(mode: str, continuity: bool, bucketing: str, expected_pass: bool) -> None:
    created = _created(ensure_experience_continuity=continuity, bucketing_identifier=bucketing)
    assert bucketing_fits(created, mode)[0] is expected_pass


_FUNNEL = {
    "metric_type": "funnel",
    "series": [{"kind": "EventsNode", "event": "$pageview"}, {"kind": "EventsNode", "event": "signed_up"}],
}
_REVENUE = {
    "metric_type": "mean",
    "source": {"kind": "EventsNode", "event": "checkout_completed", "math": "sum", "math_property": "revenue"},
}


@pytest.mark.parametrize(
    "metric,expected_problems",
    [
        (_FUNNEL, 0),
        (_FUNNEL | {"conversion_window": 7}, 1),
        (_FUNNEL | {"conversion_window": 7, "conversion_window_unit": "day"}, 0),
        (_REVENUE | {"conversion_window": 14}, 1),
        (_retention(), 0),
        (_retention(conversion_window=7), 1),
        (_retention(conversion_window=7, conversion_window_unit="day"), 0),
    ],
)
def test_windows_without_unit(metric: dict, expected_problems: int) -> None:
    assert len(windows_without_unit([metric])) == expected_problems


@pytest.mark.parametrize(
    "metric,spec,expected_pass",
    [
        (_FUNNEL, {"metric_types": ["funnel"], "event": "signed_up"}, True),
        (_FUNNEL, {"metric_types": ["funnel"], "event": "signed_up", "requires_window": True}, False),
        (
            _FUNNEL | {"conversion_window": 7, "conversion_window_unit": "day"},
            {"metric_types": ["funnel"], "event": "signed_up", "requires_window": True},
            True,
        ),
        (_FUNNEL, {"metric_types": ["funnel"], "event": "$pageview"}, False),
        (_REVENUE, {"metric_types": ["mean"], "math": "sum", "math_property": "revenue"}, True),
        (
            _REVENUE | {"source": _REVENUE["source"] | {"math": "total"}},
            {"metric_types": ["mean"], "math": "sum"},
            False,
        ),
        (_retention(), {"metric_types": ["retention"]}, True),
        (_retention(), {"metric_types": ["funnel", "mean"], "event": "uploaded_file"}, False),
    ],
)
def test_primary_metric_matches(metric: dict, spec: dict, expected_pass: bool) -> None:
    assert primary_metric_matches(metric, spec) is expected_pass


def _assistant(*blocks: dict) -> dict:
    return {"role": "assistant", "content": list(blocks)}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _tool(name: str) -> dict:
    return {"type": "tool_use", "name": name}


_SUMMARY = "Bucketing: default. Primary metric: upgraded_plan funnel."
_SIGN_OFF = "Left everything as a draft."


@pytest.mark.parametrize(
    "messages,expected",
    [
        ([_assistant(_text(_SUMMARY))], [_SUMMARY]),
        (
            [
                _assistant(_text(_SUMMARY), _tool("mcp__posthog-code-tools__show_actions")),
                _assistant(_text(_SIGN_OFF), _tool("mcp__posthog-code-tools__finish")),
            ],
            [_SUMMARY, _SIGN_OFF],
        ),
        (
            [
                _assistant(_text("Creating it now."), _tool("mcp__posthog__exec")),
                _assistant(_text(_SUMMARY)),
            ],
            [_SUMMARY],
        ),
        ([_assistant(_tool("mcp__posthog__exec"))], []),
    ],
)
def test_closing_texts(messages: list[dict], expected: list[str]) -> None:
    assert closing_texts(messages) == expected
