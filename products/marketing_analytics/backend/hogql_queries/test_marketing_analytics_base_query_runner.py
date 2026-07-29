from parameterized import parameterized

from posthog.schema import (
    InfinityValue,
    MarketingAnalyticsAggregatedQueryResponse,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQueryResponse,
    WebAnalyticsItemKind,
)

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner import (
    strip_infinity_sentinels,
)


def _item(change_pct: float | None) -> MarketingAnalyticsItem:
    return MarketingAnalyticsItem(
        key="Cost",
        kind=WebAnalyticsItemKind.CURRENCY,
        value=100.0,
        previous=0.0,
        changeFromPreviousPct=change_pct,
        hasComparison=True,
    )


class TestStripInfinitySentinels:
    @parameterized.expand(
        [
            (float(InfinityValue.NUMBER_999999), None),
            (float(InfinityValue.NUMBER__999999), None),
            (42.0, 42.0),
            (0.0, 0.0),
            (None, None),
        ]
    )
    def test_table_response_cells(self, change_pct: float | None, expected: float | None) -> None:
        response = MarketingAnalyticsTableQueryResponse(results=[[_item(change_pct), _item(7.0)]])
        strip_infinity_sentinels(response)
        assert response.results[0][0].changeFromPreviousPct == expected
        assert response.results[0][1].changeFromPreviousPct == 7.0

    def test_aggregated_response_dict_results(self) -> None:
        response = MarketingAnalyticsAggregatedQueryResponse(
            results={"cost": _item(float(InfinityValue.NUMBER_999999)), "clicks": _item(12.0)}
        )
        strip_infinity_sentinels(response)
        assert response.results["cost"].changeFromPreviousPct is None
        assert response.results["clicks"].changeFromPreviousPct == 12.0
