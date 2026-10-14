from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.product_analytics.backend.chart_events import chart_events

SERIES = {"kind": "EventsNode", "event": "signed up"}
STEPS = [SERIES, {"kind": "EventsNode", "event": "paid"}]


class TestChartEvents(BaseTest):
    @parameterized.expand(
        [
            ("weekly_active", {"kind": "TrendsQuery", "series": [{**SERIES, "math": "weekly_active"}]}),
            (
                "sum_of_a_session_property",
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            **SERIES,
                            "math": "avg",
                            "math_property": "$session_duration",
                            "math_property_type": "session_properties",
                        }
                    ],
                },
            ),
            ("compare", {"kind": "TrendsQuery", "series": [SERIES], "compareFilter": {"compare": True}}),
            ("formula", {"kind": "TrendsQuery", "series": [SERIES, SERIES], "trendsFilter": {"formula": "A / B"}}),
            ("total_value", {"kind": "TrendsQuery", "series": [SERIES], "trendsFilter": {"display": "ActionsPie"}}),
            (
                "property_breakdown",
                {"kind": "TrendsQuery", "series": [SERIES], "breakdownFilter": {"breakdown": "$browser"}},
            ),
            (
                "histogram_breakdown",
                {
                    "kind": "TrendsQuery",
                    "series": [SERIES],
                    "breakdownFilter": {"breakdown": "price", "breakdown_histogram_bin_count": 5},
                },
            ),
            (
                "funnel_exclusion",
                {
                    "kind": "FunnelsQuery",
                    "series": STEPS,
                    "funnelsFilter": {
                        "exclusions": [{"kind": "EventsNode", "event": "left", "funnelFromStep": 0, "funnelToStep": 1}]
                    },
                },
            ),
            ("funnel_trends", {"kind": "FunnelsQuery", "series": STEPS, "funnelsFilter": {"funnelVizType": "trends"}}),
            (
                "funnel_time_to_convert",
                {"kind": "FunnelsQuery", "series": STEPS, "funnelsFilter": {"funnelVizType": "time_to_convert"}},
            ),
            (
                "stickiness_criteria",
                {
                    "kind": "StickinessQuery",
                    "series": [SERIES],
                    "stickinessFilter": {"stickinessCriteria": {"operator": "gte", "value": 3}},
                },
            ),
        ]
    )
    def test_finds_the_events_the_chart_reads(self, _name: str, source: dict[str, Any]) -> None:
        assert chart_events(source, self.team, self.user) is not None
