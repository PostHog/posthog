from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.posthog_ai.evals.product_analytics.scorers import AnswerFromTypedQuery, InsightShape


def _output(calls) -> dict:
    return {"raw_log": _raw_tool_log(calls), "prompt": "How are page views doing by browser?"}


def _trends_call(
    display: str | None = None,
    breakdown: str | None = None,
    events: list[str] | None = None,
    status: str = "completed",
    compare: bool | None = None,
) -> tuple:
    query: dict = {"series": [{"kind": "EventsNode", "event": e} for e in (events or ["$pageview"])]}
    if display is not None:
        query["trendsFilter"] = {"display": display}
    if breakdown is not None:
        query["breakdownFilter"] = {"breakdowns": [{"property": breakdown, "type": "event"}]}
    if compare is not None:
        query["compareFilter"] = {"compare": compare}
    return ("mcp__posthog__query-trends", query, "ok", status)


def _funnel_call(
    events: list[str], breakdown: str | None = None, viz: str | None = None, include_filter: bool = True
) -> tuple:
    query: dict = {"series": [{"kind": "EventsNode", "event": e} for e in events]}
    if include_filter or viz is not None:
        query["funnelsFilter"] = {}
    if viz is not None:
        query["funnelsFilter"]["funnelVizType"] = viz
    if breakdown is not None:
        query["breakdownFilter"] = {"breakdown": breakdown, "breakdown_type": "event"}
    return ("mcp__posthog__query-funnel", query, "ok")


def _saved_call(display: str, wrapped: bool = True, status: str = "completed") -> tuple:
    source = {"kind": "TrendsQuery", **_trends_call(display, "file_type", ["uploaded_file"])[1]}
    query = {"kind": "InsightVizNode", "source": source} if wrapped else source
    return ("mcp__posthog__insight-create", {"name": "Uploads by file type", "query": query}, "ok", status)


UPLOADS_BY_FILE_TYPE = {
    "tool": "query-trends",
    "display": ["ActionsBarValue"],
    "breakdown": "file_type",
    "events": ["uploaded_file"],
}


def _scorecard_call(maths: list[str | None], formula: bool = False, test_accounts: bool | None = None) -> tuple:
    series = [{"kind": "EventsNode", "event": "uploaded_file", **({"math": m} if m else {})} for m in maths]
    query: dict = {"series": series}
    if formula:
        query["trendsFilter"] = {"formulaNodes": [{"formula": "A-B"}]}
    if test_accounts is not None:
        query["filterTestAccounts"] = test_accounts
    return ("mcp__posthog__query-trends", query, "ok")


_NODES = [{"kind": "EventsNode", "event": "uploaded_file"}, {"kind": "EventsNode", "event": "downloaded_file"}]
_DAU_NODES = [{**node, "math": "dau"} for node in _NODES]


def _filtered_call(series_key: str | None = None, query_key: str | None = None) -> tuple:
    node: dict = {"kind": "EventsNode", "event": "uploaded_file"}
    if series_key:
        node["properties"] = [{"key": series_key, "operator": "is_set", "type": "event"}]
    query: dict = {"series": [node]}
    if query_key:
        query["properties"] = {"type": "AND", "values": [{"key": query_key, "value": "/pricing/", "type": "event"}]}
    return ("mcp__posthog__query-trends", query, "ok")


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
            [_trends_call("ActionsLineGraph", "$browser"), _trends_call("BoldNumber", "$browser")],
            PAGEVIEWS_BY_BROWSER,
            0.0,
            ["display"],
        ),
        (
            [_funnel_call(["signed_up", "uploaded_file"], viz="trends"), _funnel_call(["signed_up", "uploaded_file"])],
            {"tool": "query-funnel", "funnel_viz": "trends"},
            0.0,
            ["funnel_viz"],
        ),
        ([_saved_call("ActionsBarValue")], UPLOADS_BY_FILE_TYPE, 1.0, []),
        ([_saved_call("ActionsBarValue", wrapped=False)], UPLOADS_BY_FILE_TYPE, 1.0, []),
        (
            [_trends_call("ActionsBarValue", "file_type", ["uploaded_file"]), _saved_call("ActionsBar")],
            UPLOADS_BY_FILE_TYPE,
            0.0,
            ["display"],
        ),
        (
            [
                _trends_call("ActionsBarValue", "file_type", ["uploaded_file"]),
                _saved_call("ActionsBar", status="failed"),
            ],
            UPLOADS_BY_FILE_TYPE,
            1.0,
            [],
        ),
        (
            [
                _trends_call("ActionsBarValue", "file_type", ["uploaded_file"]),
                (
                    "mcp__posthog__insight-create",
                    {"name": "Uploads", "query": {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery"}}},
                    "ok",
                ),
            ],
            UPLOADS_BY_FILE_TYPE,
            0.0,
            ["tool"],
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
            [
                (
                    "mcp__posthog__query-trends",
                    {"series": [{"kind": "ActionsNode", "id": 13, "name": "Interacted with file"}]},
                    "ok",
                )
            ],
            {"tool": "query-trends", "events": [13]},
            1.0,
            [],
        ),
        (
            [
                (
                    "mcp__posthog__query-funnel",
                    {
                        "series": [
                            {"kind": "EventsNode", "event": "signed_up"},
                            {"kind": "ActionsNode", "id": 13, "name": "Interacted with file"},
                        ]
                    },
                    "ok",
                )
            ],
            {"tool": "query-funnel", "event_sequence": ["signed_up", 13]},
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
        (
            [_funnel_call(["signed_up", "uploaded_file"], include_filter=False)],
            {"funnel_viz": "steps"},
            1.0,
            [],
        ),
        ([_trends_call("Metric", compare=True)], {"compare": True}, 1.0, []),
        ([_trends_call("Metric")], {"compare": True}, 0.0, ["compare"]),
        ([_sql_call()], {"tool": "execute-sql"}, 1.0, []),
        (
            [
                _sql_call(),
                ("mcp__posthog__execute-sql", {"query": "SELECT * FROM system.information_schema.tables"}, "ok"),
            ],
            {"tool": "execute-sql"},
            1.0,
            [],
        ),
        (
            [("mcp__posthog__read-data-schema", {"query": {"kind": "events"}}, "ok")],
            {"tool": "query-trends"},
            0.0,
            None,
        ),
        ([_scorecard_call(["dau", None])], {"math": ["total", "dau"]}, 1.0, []),
        ([_scorecard_call([None, None])], {"math": ["total", "dau"]}, 0.0, ["math"]),
        ([_scorecard_call(["median", "p95"])], {"math": ["p95"]}, 1.0, []),
        ([_scorecard_call(["dau", None], formula=True)], {"formula": True}, 1.0, []),
        ([_scorecard_call(["dau", None])], {"formula": True}, 0.0, ["formula"]),
        ([_scorecard_call(["dau"], test_accounts=True)], {"filter_test_accounts": True}, 1.0, []),
        ([_scorecard_call(["dau"])], {"filter_test_accounts": True}, 0.0, ["filter_test_accounts"]),
        (
            [("mcp__posthog__query-trends", {"series": [{"kind": "GroupNode", "math": "dau", "nodes": _NODES}]}, "ok")],
            {"math": ["dau"]},
            1.0,
            [],
        ),
        (
            [("mcp__posthog__query-trends", {"series": [{"kind": "GroupNode", "nodes": _DAU_NODES}]}, "ok")],
            {"math": ["dau"]},
            0.0,
            ["math"],
        ),
        ([_filtered_call(series_key="file_name")], {"filtered_on": ["file_name"]}, 1.0, []),
        ([_filtered_call(query_key="$pathname")], {"filtered_on": ["$pathname", "$current_url"]}, 1.0, []),
        ([_filtered_call()], {"filtered_on": ["file_name"]}, 0.0, ["filtered_on"]),
    ],
)
def test_insight_shape_checks_only_the_expected_keys(calls, shape, score, mismatched) -> None:
    result = InsightShape()._run_eval_sync(_output(calls), {"insight_shape": shape})
    assert result.score == score
    if mismatched is not None:
        assert sorted(result.metadata["mismatches"]) == sorted(mismatched)


def test_insight_shape_skips_without_expectation() -> None:
    assert InsightShape()._run_eval_sync(_output([_trends_call()]), {}).score is None


def _result(tool: str, text: str, query: dict | None = None) -> tuple:
    return (f"mcp__posthog__{tool}", query or {}, {"content": [{"type": "text", "text": text}]})


_TYPED = _result("query-trends", "Date range|Uploads|Unique uploaders\n2026-10-12 to 2026-10-19|21|917")
_SQL = _result("execute-sql", "uploads|downloads\n20|846", {"query": "SELECT count() FROM events"})
_CATALOG = _result("execute-sql", "id|name\n42|Weekly logins", {"query": "SELECT id, name FROM system.insights"})
_SQL_LINK = "[Uploads](https://us.example.com/project/1/sql?open_query=SELECT%20count()%20FROM%20events)"


@pytest.mark.parametrize(
    "calls,answer,score",
    [
        ([_TYPED], "Oct 12 to Oct 19: 21 uploads and 917 unique uploaders.", 1.0),
        (
            [_TYPED, _SQL],
            f"There were 21 uploads and 917 downloads.\n\n{_SQL_LINK}\n\nA rolling window gives 20 and 846.",
            1.0,
        ),
        ([_TYPED, _SQL], "There were 20 uploads and 846 downloads.", 0.0),
        ([_SQL], "There were 20 uploads and 846 downloads.", 0.0),
        ([_CATALOG, _TYPED], "No saved insight exists. There were 21 uploads.", 1.0),
        ([_CATALOG], "Insight 42 already tracks weekly logins.", None),
        ([_result("execute-sql", "n\n846", {"query": "SELECT count() FROM system.insights, events"})], "846", 0.0),
        (
            [_result("execute-sql", "n\n846", {"query": "SELECT count() FROM `events` JOIN system.insights i ON 1"})],
            "846",
            0.0,
        ),
        ([_TYPED, _SQL], "Uploads rose by a third.", None),
        ([_result("query-trends", "Net|-42"), _result("execute-sql", "net\n42")], "Net upgrades: 42.", 0.0),
        ([_result("query-trends", "Net|-42"), _result("execute-sql", "net\n42")], "Net upgrades: -42.", 1.0),
        (
            [
                _result("query-funnel", "Step|Conversion\nUploaded file|45\n\nExample: 90% of users convert."),
                _result("execute-sql", "rate\n90"),
            ],
            "Conversion is 90%.",
            0.0,
        ),
        ([_result("query-trends", "Signups|2026")], "There were 2,026 signups.", 1.0),
        (
            [
                _result(
                    "query-trends",
                    '{"query": {"trendsFilter": {"smoothingIntervals": 30}}, "results": [{"label": "x", "count": 917}]}',
                ),
                _result("execute-sql", "users\n30"),
            ],
            "30 users uploaded a file.",
            0.0,
        ),
    ],
)
def test_answer_from_typed_query_traces_reported_values(calls, answer, score) -> None:
    output = {
        "raw_log": _raw_tool_log(calls),
        "prompt": "How many uploads in the last 7 days?",
        "messages": [{"role": "assistant", "content": [{"type": "text", "text": answer}]}],
    }

    result = AnswerFromTypedQuery()._run_eval_sync(output, {"answer_from_typed_query": {}})

    assert result.score == score
