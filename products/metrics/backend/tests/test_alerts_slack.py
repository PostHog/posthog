import time
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition, MessageLink
from products.metrics.backend.alerts import slack
from products.metrics.backend.alerts.slack import chart_block, render_metrics_slack_message

OCCURRED_AT = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
HISTORY = [(1_000_000 + 240 * index, float(value)) for index, value in enumerate([2, 5, 9, 4, 0, 1])]


def _transition(kind: AlertEventKind = AlertEventKind.FIRING, **overrides: Any) -> AnnouncedTransition:
    fields: dict[str, Any] = {
        "grouping_key": "",
        "kind": kind,
        "episode_started_at": OCCURRED_AT,
        "value": 1.0,
        "labels": {"environment": "staging"},
        "condition": {"kind": "threshold", "operator": "gt", "threshold": 0},
        "source_config": {"query": "sum(rate(errors_total[5m]))"},
        "error_message": None,
        "occurred_at": OCCURRED_AT,
    }
    return AnnouncedTransition(**{**fields, **overrides})


def _render(transition: AnnouncedTransition, history: list[tuple[int, float]]) -> Any:
    with patch.object(slack, "fetch_history", return_value=history):
        return render_metrics_slack_message(
            team_id=1,
            transition=transition,
            alert_name="Checkout errors",
            alert_url="https://example.com/alert",
            project=MessageLink(label="Demo project", url="https://example.com/project/1"),
            image=None,
        )


def test_a_firing_card_leads_with_the_value_and_ends_with_the_actions() -> None:
    content = _render(_transition(), HISTORY)

    types = [block["type"] for block in content.blocks]
    assert types == ["header", "context", "section", "data_visualization", "context", "actions"]
    fields = [field["text"] for field in content.blocks[2]["fields"]]
    assert fields == ["*Value*\n1", "*Fires when*\n&gt; 0"]
    assert content.blocks[0]["text"]["text"] == "🔴 Checkout errors"
    assert "Checkout errors" in content.text


def test_the_card_is_complete_without_a_history() -> None:
    content = _render(_transition(), [])

    assert "data_visualization" not in [block["type"] for block in content.blocks]
    assert content.blocks[-1]["type"] == "actions"


def test_only_a_firing_gets_this_layout() -> None:
    for kind in (AlertEventKind.RESOLVED, AlertEventKind.ERRORED, AlertEventKind.CHECK):
        assert _render(_transition(kind), HISTORY) is None


def test_the_chart_draws_the_threshold_as_a_second_line() -> None:
    block = chart_block(HISTORY, _transition())

    assert block is not None
    series = block["chart"]["series"]
    assert [s["name"] for s in series] == ["Value", "Threshold"]
    assert all(len(s["data"]) == len(HISTORY) for s in series)
    assert block["chart"]["axis_config"]["categories"][-1] == "Alert"
    assert block["chart"]["axis_config"]["categories"][0] == "20m ago"


def test_a_single_point_is_not_a_trend() -> None:
    assert chart_block(HISTORY[:1], _transition()) is None


def test_a_query_cannot_end_its_own_code_span_or_broadcast() -> None:
    content = _render(_transition(source_config={"query": "up{job=`x`} <!channel>"}), [])

    query_line = content.blocks[-2]["elements"][0]["text"]
    assert query_line.count("`") == 2


def _series(metric: dict[str, str], values: list[Any]) -> dict[str, Any]:
    return {"metric": metric, "values": [[1_000_000 + 240 * index, str(value)] for index, value in enumerate(values)]}


@pytest.mark.parametrize(
    "labels,value,result,expected",
    [
        # A label set that groups by the metric name keeps it.
        ({"__name__": "up"}, 1.0, [_series({"__name__": "up", "job": "a"}, [0, 1])], [0.0, 1.0]),
        # Two instances share the group's labels: the one whose latest value fired is charted.
        (
            {"job": "a"},
            9.0,
            [_series({"job": "a", "instance": "1"}, [1, 2]), _series({"job": "a", "instance": "2"}, [5, 9])],
            [5.0, 9.0],
        ),
        # When the reported value matches neither, no chart beats the wrong one.
        (
            {"job": "a"},
            7.0,
            [_series({"job": "a", "instance": "1"}, [1, 2]), _series({"job": "a", "instance": "2"}, [5, 9])],
            [],
        ),
        # Evaluation records an absent grouping label as "", so a series without it still matches.
        ({"job": ""}, 1.0, [_series({"instance": "1"}, [0, 1])], [0.0, 1.0]),
        # NaN and infinity have no JSON form, so they never reach Slack.
        ({}, 2.0, [_series({}, ["NaN", 1, "+Inf", 2])], [1.0, 2.0]),
        # The last point is the value that fired, even when the range read on past the evaluation.
        ({}, 3.0, [_series({}, [1, 2])], [1.0, 3.0]),
    ],
)
def test_history_charts_the_series_that_fired(
    labels: dict[str, str], value: float, result: list[dict[str, Any]], expected: list[float]
) -> None:
    slack._results.clear()
    with patch.object(slack, "_read_range", return_value=result) as read:
        history = slack.fetch_history(1, _transition(labels=labels, value=value))
        slack.fetch_history(1, _transition(labels=labels, value=value))

    assert [point for _, point in history] == expected
    # Every group and destination of one evaluation shares one read.
    assert read.call_count == 1


class _StreamedResponse:
    def __init__(self, body: bytes, status_code: int = 200) -> None:
        self.status_code = status_code
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size: int) -> Any:
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "body,status_code,expected",
    [
        (b'{"status":"success","data":{}}', 200, {"status": "success", "data": {}}),
        (b'{"status":"error"}', 200, None),
        (b'{"status":"success"}', 422, None),
        # Dropped while it streams in, before any of it is decoded.
        (b"x" * (slack.CHART_MAX_BYTES + 1), 200, None),
    ],
)
def test_a_history_body_is_read_only_within_its_byte_cap(
    body: bytes, status_code: int, expected: dict[str, Any] | None
) -> None:
    response = _StreamedResponse(body, status_code)

    assert slack._bounded_json(response, deadline=time.monotonic() + 60) == expected
    assert response.closed


def test_a_history_body_still_arriving_at_the_deadline_is_dropped() -> None:
    response = _StreamedResponse(b'{"status":"success","data":{}}')

    assert slack._bounded_json(response, deadline=time.monotonic() - 1) is None
    assert response.closed
