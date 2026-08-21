"""
Test account filter planning for product_analytics.

Split out of ``facade.api`` because the implementation reaches the HogQL query-runner chain,
which imports ``posthog.hogql.query``. Anything on that chain that reads insight variables would
otherwise import a facade module that is still initializing, so the light data capabilities stay
in ``facade.api`` and this one carries the heavy import.
"""

from typing import Any

from products.product_analytics.backend import insight_test_account_filters
from products.product_analytics.backend.insight_test_account_filters import TestAccountFilterUpdate


def plan_test_account_filter_update(query: Any, *, enabled: bool) -> TestAccountFilterUpdate:
    """Work out how to set the test account filter on an insight, without touching the stored query."""
    return insight_test_account_filters.plan_test_account_filter_update(query, enabled=enabled)
