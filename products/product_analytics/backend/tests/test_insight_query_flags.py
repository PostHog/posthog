from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.product_analytics.backend.insight_test_account_filters import (
    plan_default_filters_update,
    plan_test_account_filter_update,
)

TRENDS_SOURCE: dict[str, Any] = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}
SQL_QUERY: dict[str, Any] = {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}}


class TestInsightQueryFlagPlanning(SimpleTestCase):
    @parameterized.expand(
        [
            ("test_accounts", plan_test_account_filter_update, "filterTestAccounts"),
            ("default_filters", plan_default_filters_update, "applyDefaultFilters"),
        ]
    )
    def test_sets_only_its_own_flag_on_the_source_of_a_wrapped_query(self, _name, plan, flag) -> None:
        query = {"kind": "InsightVizNode", "source": TRENDS_SOURCE}

        update = plan(query, enabled=True)

        assert update.supported
        assert update.query == {"kind": "InsightVizNode", "source": {**TRENDS_SOURCE, flag: True}}
        assert "filterTestAccounts" not in query["source"]
        assert "applyDefaultFilters" not in query["source"]

    @parameterized.expand(
        [
            ("test_accounts", plan_test_account_filter_update, "filterTestAccounts"),
            ("default_filters", plan_default_filters_update, "applyDefaultFilters"),
        ]
    )
    def test_reports_an_insight_that_already_has_the_value_as_unchanged(self, _name, plan, flag) -> None:
        update = plan({"kind": "InsightVizNode", "source": {**TRENDS_SOURCE, flag: True}}, enabled=True)

        assert update.supported
        assert not update.changed

    @parameterized.expand(
        [
            ("test_accounts", plan_test_account_filter_update),
            ("default_filters", plan_default_filters_update),
        ]
    )
    def test_leaves_queries_without_the_flag_unsupported(self, _name, plan) -> None:
        assert not plan(SQL_QUERY, enabled=True).supported
