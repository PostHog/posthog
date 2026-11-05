from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.test.test_eval_scorers import _raw_tool_log
from products.posthog_ai.evals.product_analytics.explain_chart_scorers import ExplainChartEndsInvestigation

QUERY = ("mcp__posthog__query-trends", {"kind": "TrendsQuery"}, "{}")
EXPLAIN = ("mcp__posthog__explain-chart", {"insightId": 1, "headline": "h", "chapters": []}, "{}")
RENDER = ("mcp__posthog__render-ui", {"tool_name": "explain-chart"}, "{}")
NOTEBOOK = ("mcp__posthog__notebooks-create-markdown", {"title": "Findings"}, "{}")


@pytest.mark.parametrize(
    "calls,expected_score",
    [
        ([QUERY, EXPLAIN, RENDER], 1.0),
        ([QUERY, EXPLAIN, QUERY, EXPLAIN], 1.0),
        ([QUERY, EXPLAIN, QUERY], 0.0),
        ([QUERY, EXPLAIN, NOTEBOOK], 0.0),
        ([QUERY], None),
    ],
    ids=["render_after", "explained_again_after_more_queries", "query_after", "notebook_after", "never_explained"],
)
def test_explain_chart_ends_investigation(calls: list[tuple], expected_score: float | None) -> None:
    score = ExplainChartEndsInvestigation()._run_eval_sync({"raw_log": _raw_tool_log(calls), "prompt": "why"})

    assert score.score == expected_score
