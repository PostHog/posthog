from typing import Any

import pytest

from products.subscriptions.backend.logic.insight_criteria import snapshot_has_data


@pytest.mark.parametrize(
    "result,expected",
    [
        # Trends series
        ([{"data": [0, 2, 0], "aggregated_value": 2, "label": "$pageview"}], True),
        ([{"data": [0, 0, 0], "aggregated_value": 0, "label": "$pageview", "action": {"order": 1}}], False),
        ([], False),
        # Funnel steps, with and without breakdown
        ([{"count": 0, "name": "step 1"}, {"count": 0, "name": "step 2"}], False),
        ([[{"count": 5}, {"count": 1}], [{"count": 0}, {"count": 0}]], True),
        # Retention cohorts
        ([{"values": [{"count": 0}, {"count": 0}], "label": "Day 0"}], False),
        ([{"values": [{"count": 4}], "label": "Day 0"}], True),
        # HogQL / events table rows
        ([["2024-01-01", 0]], True),
        ([[0]], False),
        ([[None]], False),
        # Unknown dict shape counts as data by its presence
        ([{"source": "/a", "target": "/b"}], True),
    ],
)
def test_snapshot_has_data(result: Any, expected: bool) -> None:
    assert snapshot_has_data({"query_results": {"result": result}}) is expected
