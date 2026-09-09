from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.posthog_ai.evals.product_analytics.scorers import InsightShape


def _output(calls) -> dict:
    return {"raw_log": _raw_tool_log(calls), "prompt": "How are page views doing by browser?"}


def _trends_call(
    display: str | None = None,
    breakdown: str | None = None,
    events: list[str] | None = None,
    status: str = "completed",
) -> tuple:
    query: dict = {"series": [{"kind": "EventsNode", "event": e} for e in (events or ["$pageview"])]}
    if display is not None:
        query["trendsFilter"] = {"display": display}
    if breakdown is not None:
        query["breakdownFilter"] = {"breakdowns": [{"property": breakdown, "type": "event"}]}
    return ("mcp__posthog__query-trends", query, "ok", status)


def _funnel_call(events: list[str], breakdown: str | None = None, viz: str | None = None) -> tuple:
    query: dict = {"series": [{"kind": "EventsNode", "event": e} for e in events], "funnelsFilter": {}}
    if viz is not None:
        query["funnelsFilter"]["funnelVizType"] = viz
    if breakdown is not None:
        query["breakdownFilter"] = {"breakdown": breakdown, "breakdown_type": "event"}
    return ("mcp__posthog__query-funnel", query, "ok")


def _sql_call(status: str = "completed") -> tuple:
    return ("mcp__posthog__execute-sql", {"query": "SELECT 1"}, "1", status)


PAGEVIEWS_BY_BROWSER = {
    "tool": "query-trends",
    "display": ["ActionsLineGraph", "ActionsBar"],
    "breakdown": "$browser",
    "events": ["$pageview"],
}


@pytest.mark.parametrize(
    "calls,shape,score,mismatched",
    [
        ([_trends_call("ActionsLineGraph", "$browser")], PAGEVIEWS_BY_BROWSER, 1.0, []),
        ([_trends_call(None, "$browser")], PAGEVIEWS_BY_BROWSER, 1.0, []),
        ([_trends_call("BoldNumber", "$browser")], PAGEVIEWS_BY_BROWSER, 0.0, ["display"]),
        ([_trends_call("ActionsLineGraph")], PAGEVIEWS_BY_BROWSER, 0.0, ["breakdown"]),
        ([_trends_call("ActionsLineGraph", "$browser", ["signed_up"])], PAGEVIEWS_BY_BROWSER, 0.0, ["events"]),
        ([_trends_call("ActionsLineGraph", "$browser"), _sql_call()], PAGEVIEWS_BY_BROWSER, 1.0, []),
        (
            [_trends_call("BoldNumber", "$browser"), _trends_call("ActionsLineGraph", "$browser")],
            PAGEVIEWS_BY_BROWSER,
            1.0,
            [],
        ),
        (
            [_funnel_call(["signed_up", "uploaded_file"], viz="trends"), _funnel_call(["signed_up", "uploaded_file"])],
            {"tool": "query-funnel", "funnel_viz": "trends"},
            1.0,
            [],
        ),
        ([_sql_call()], PAGEVIEWS_BY_BROWSER, 0.0, ["tool"]),
        ([_trends_call("ActionsLineGraph", "$browser"), _sql_call()], {"tool": "execute-sql"}, 0.0, ["tool"]),
        (
            [("mcp__posthog__query-web-stats", {"breakdownBy": "Page"}, "ok")],
            {"tool": ["query-trends", "query-web-stats"], "display": ["ActionsBarValue"], "breakdown": "$pathname"},
            1.0,
            [],
        ),
        ([_trends_call("ActionsLineGraph", "$browser"), _sql_call("failed")], PAGEVIEWS_BY_BROWSER, 1.0, []),
        ([_sql_call(), _trends_call("ActionsLineGraph", "$browser")], PAGEVIEWS_BY_BROWSER, 1.0, []),
        ([_trends_call("BoldNumber", None, ["signed_up"])], {"tool": "query-trends", "breakdown": None}, 1.0, []),
        ([_trends_call("BoldNumber", "$browser")], {"tool": "query-trends", "breakdown": None}, 0.0, ["breakdown"]),
        (
            [_trends_call("ActionsBar", None, ["downloaded_file", "uploaded_file"])],
            {"tool": "query-trends", "events": ["uploaded_file", "downloaded_file"]},
            1.0,
            [],
        ),
        (
            [_funnel_call(["signed_up", "uploaded_file"], "$device_type")],
            {"tool": "query-funnel", "breakdown": "$device_type", "event_sequence": ["signed_up", "uploaded_file"]},
            1.0,
            [],
        ),
        (
            [_funnel_call(["uploaded_file", "signed_up"])],
            {"tool": "query-funnel", "event_sequence": ["signed_up", "uploaded_file"]},
            0.0,
            ["event_sequence"],
        ),
        ([_funnel_call(["signed_up", "uploaded_file"], viz="trends")], {"funnel_viz": "trends"}, 1.0, []),
        ([_funnel_call(["signed_up", "uploaded_file"])], {"funnel_viz": "trends"}, 0.0, ["funnel_viz"]),
        ([_funnel_call(["signed_up", "uploaded_file"])], {"funnel_viz": "steps"}, 1.0, []),
        ([_sql_call()], {"tool": "execute-sql"}, 1.0, []),
        (
            [("mcp__posthog__read-data-schema", {"query": {"kind": "events"}}, "ok")],
            {"tool": "query-trends"},
            0.0,
            None,
        ),
    ],
)
def test_insight_shape_checks_only_the_expected_keys(calls, shape, score, mismatched) -> None:
    result = InsightShape()._run_eval_sync(_output(calls), {"insight_shape": shape})
    assert result.score == score
    if mismatched is not None:
        assert sorted(result.metadata["mismatches"]) == sorted(mismatched)


def test_insight_shape_skips_without_expectation() -> None:
    assert InsightShape()._run_eval_sync(_output([_trends_call()]), {}).score is None
