from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from products.signals.backend.report_charts import (
    _MAX_CHART_QUERY_CHARS,
    MAX_CHART_CAPTION_LENGTH,
    MAX_CHART_ID_LENGTH,
    MAX_CHART_TITLE_LENGTH,
    ReportChart,
)


class TestReportCharts(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_full_chart",
                {
                    "chart_id": "signups-drop",
                    "title": "Daily signups",
                    "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                    "caption": "The drop starts on the 6th.",
                    "size": "large",
                },
            ),
            # A direct connection without the raw-SQL bypass still goes through the HogQL printer and
            # the resource access check, so it stays a drawable chart.
            (
                "a_warehouse_connection_without_the_raw_sql_bypass",
                {
                    "chart_id": "warehouse-rows",
                    "title": "Rows by day",
                    "query": {
                        "kind": "DataVisualizationNode",
                        "source": {"kind": "HogQLQuery", "query": "SELECT 1", "connectionId": "conn-1"},
                    },
                },
            ),
        ]
    )
    def test_accepts_a_renderable_chart(self, _name: str, content: dict) -> None:
        chart = ReportChart.model_validate(content)
        # The chart round-trips through the JSON it is stored as on the report.
        assert ReportChart.model_validate_json(chart.model_dump_json()) == chart

    @parameterized.expand(
        [
            # A kind the inbox can't draw must fail at write time, not render as an empty box later.
            ("an_undrawable_kind", {"chart_id": "ok", "title": "t", "query": {"kind": "HogQLQuery", "q": "SELECT 1"}}),
            # `chart_id` is the target of a `chart:` markdown link in the summary — a slug that can't
            # survive being parsed as one silently stops resolving the reference.
            (
                "a_reference_unsafe_chart_id",
                {"chart_id": "Signups Drop", "title": "t", "query": {"kind": "InsightVizNode"}},
            ),
            # `kind` is caller-supplied JSON and can be any type. An unhashable one used to raise
            # TypeError straight out of the validator, turning a bad write into a 500 instead of a 400.
            ("an_unhashable_kind", {"chart_id": "ok", "title": "t", "query": {"kind": []}}),
            ("a_dict_kind", {"chart_id": "ok", "title": "t", "query": {"kind": {"nested": 1}}}),
            # Conditional-formatting bytecode runs through `execHog` once per rendered cell, on the
            # reader's main thread, so a chart carrying it can freeze the tab of whoever opens the
            # report. The whole key is refused wherever it sits, not just at the path known today.
            (
                "bytecode_under_conditional_formatting",
                {
                    "chart_id": "ok",
                    "title": "t",
                    "query": {
                        "kind": "DataVisualizationNode",
                        "tableSettings": {"conditionalFormatting": [{"bytecode": ["_H", 1]}]},
                    },
                },
            ),
            (
                "bytecode_at_the_top_level",
                {"chart_id": "ok", "title": "t", "query": {"kind": "InsightVizNode", "bytecode": ["_H", 1]}},
            ),
            # The renderer posts a node's nested source to the query service, where `HogQuery` runs its
            # `code` through `execute_hog` — so an allowed outer kind must not smuggle one underneath.
            (
                "a_nested_hog_query",
                {
                    "chart_id": "ok",
                    "title": "t",
                    "query": {
                        "kind": "DataVisualizationNode",
                        "source": {"kind": "HogQuery", "code": "while (true) {}"},
                    },
                },
            ),
            # `sendRawQuery` skips the HogQL printer and sends the query text verbatim to the external
            # engine, under the session of whoever opens the report.
            (
                "the_raw_sql_bypass",
                {
                    "chart_id": "ok",
                    "title": "t",
                    "query": {
                        "kind": "DataVisualizationNode",
                        "source": {
                            "kind": "HogQLQuery",
                            "query": "SELECT pg_sleep(60)",
                            "connectionId": "conn-1",
                            "sendRawQuery": True,
                        },
                    },
                },
            ),
            # An unknown `size` has no height behind it, so accepting it would store a layout choice
            # the renderer silently ignores rather than telling the author it didn't take.
            ("an_unknown_size", {"chart_id": "ok", "title": "t", "query": {"kind": "InsightVizNode"}, "size": "huge"}),
            # The per-chart bounds are what the report-wide budget is built on: the judge is shown
            # every chart on a report, query bodies included, so the query bound times the per-report
            # cap is the worst case that prompt can cost.
            (
                "an_overlong_chart_id",
                {"chart_id": "c" * (MAX_CHART_ID_LENGTH + 1), "title": "t", "query": {"kind": "InsightVizNode"}},
            ),
            ("a_blank_title", {"chart_id": "ok", "title": "   ", "query": {"kind": "InsightVizNode"}}),
            (
                "an_overlong_title",
                {"chart_id": "ok", "title": "t" * (MAX_CHART_TITLE_LENGTH + 1), "query": {"kind": "InsightVizNode"}},
            ),
            (
                "an_overlong_caption",
                {
                    "chart_id": "ok",
                    "title": "t",
                    "query": {"kind": "InsightVizNode"},
                    "caption": "c" * (MAX_CHART_CAPTION_LENGTH + 1),
                },
            ),
            (
                "an_oversized_query",
                {
                    "chart_id": "ok",
                    "title": "t",
                    "query": {
                        "kind": "InsightVizNode",
                        "source": {"kind": "TrendsQuery", "note": "x" * _MAX_CHART_QUERY_CHARS},
                    },
                },
            ),
        ]
    )
    def test_rejects_an_unrenderable_or_unbounded_chart(self, _name: str, content: dict) -> None:
        with self.assertRaises(ValidationError):
            ReportChart.model_validate(content)

    def test_a_deeply_nested_query_is_rejected_rather_than_blowing_the_stack(self) -> None:
        # 1,500 levels serialize to ~18,000 characters, inside the size bound and past Python's
        # recursion limit, so this reaches the scan rather than being turned away by the length check
        # first. Scanning it recursively raises RecursionError, which nothing on the write path
        # turns into a 400.
        nested: dict = {"kind": "HogQuery", "code": "while (true) {}"}
        for _ in range(1_500):
            nested = {"source": nested}

        with self.assertRaises(ValidationError):
            ReportChart.model_validate({"chart_id": "ok", "title": "t", "query": {"kind": "InsightVizNode", **nested}})
