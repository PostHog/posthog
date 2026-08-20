"""
Facade for product_analytics.

The public entry point core and other products import product-analytics
functionality from; ``facade.models`` carries the sanctioned model-class
crossings. Functions here stay thin and delegate to ``backend.logic``.
"""

from typing import Any

from products.product_analytics.backend import insight_test_account_filters, logic
from products.product_analytics.backend.insight_test_account_filters import TestAccountFilterUpdate
from products.product_analytics.backend.models.insight_variable import InsightVariable


def map_stale_to_latest(stale_variables: dict, latest_variables: list[InsightVariable]) -> dict:
    """Refresh an insight's stored variables against the team's latest ``InsightVariable`` rows."""
    return logic.map_stale_to_latest(stale_variables, latest_variables)


def plan_test_account_filter_update(query: Any, *, enabled: bool) -> TestAccountFilterUpdate:
    """Work out how to set the test account filter on an insight, without touching the stored query."""
    return insight_test_account_filters.plan_test_account_filter_update(query, enabled=enabled)


def get_query_specific_instructions(kind: str) -> str:
    """Analysis guidance for a query kind, used by LLM insight and subscription summaries."""
    return logic.get_query_specific_instructions(kind)
