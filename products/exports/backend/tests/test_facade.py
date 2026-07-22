from django.test import SimpleTestCase

from parameterized import parameterized

from products.exports.backend.facade.api import _validate_adhoc_export_context
from products.exports.backend.tasks.image_exporter import _insight_query_wants_legend


class TestValidateAdhocExportContext(SimpleTestCase):
    def test_accepts_insight_viz_wrapped_source(self):
        _validate_adhoc_export_context(
            {"source": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}}}
        )

    @parameterized.expand(
        [
            ("bare_trends_query", {"source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}}),
            ("data_table", {"source": {"kind": "DataTableNode"}}),
            ("non_dict_source", {"source": "SELECT 1"}),
            ("missing_source", {}),
        ]
    )
    def test_rejects_unwrapped_sources(self, _name, export_context):
        with self.assertRaises(ValueError):
            _validate_adhoc_export_context(export_context)


class TestInsightQueryWantsLegend(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "two_series_gets_legend",
                {
                    "kind": "InsightVizNode",
                    "source": {"kind": "TrendsQuery", "series": [{"event": "a"}, {"event": "b"}]},
                },
                True,
            ),
            (
                "breakdown_gets_legend",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"event": "a"}],
                        "breakdownFilter": {"breakdown": "$browser"},
                    },
                },
                True,
            ),
            (
                "single_series_skipped",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}},
                False,
            ),
            (
                "explicit_false_respected",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"event": "a"}, {"event": "b"}],
                        "trendsFilter": {"showLegend": False},
                    },
                },
                False,
            ),
            ("non_insight_kind", {"kind": "DataTableNode"}, False),
        ]
    )
    def test_legend_defaulting(self, _name, query, expected):
        self.assertEqual(_insight_query_wants_legend(query), expected)
