from django.test import SimpleTestCase

from parameterized import parameterized

from products.exports.backend.facade.api import _enable_legend_for_multi_series


class TestEnableLegendForMultiSeries(SimpleTestCase):
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
                "single_series_untouched",
                {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}},
                None,
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
        ]
    )
    def test_legend_defaulting(self, _name, query, expected_show_legend):
        _enable_legend_for_multi_series(query)
        self.assertEqual(query["source"].get("trendsFilter", {}).get("showLegend"), expected_show_legend)

    @parameterized.expand([("non_dict", "SELECT 1"), ("non_insight_kind", {"kind": "DataTableNode"}), ("none", None)])
    def test_ignores_non_insight_shapes(self, _name, query):
        _enable_legend_for_multi_series(query)
