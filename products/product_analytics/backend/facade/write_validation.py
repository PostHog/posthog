"""
Insight write validation for product_analytics.

Split out of ``facade.api`` for the same reason as ``facade.account_filters``: the
implementation reaches the HogQL query-runner chain, which imports ``posthog.hogql.query``.
Anything on that chain that reads insight variables would otherwise import a facade module
that is still initializing.
"""

from typing import Any

from rest_framework.request import Request

from posthog.models import Team

from products.product_analytics.backend import insight_write_validation
from products.product_analytics.backend.insight_write_validation import Writer


def validate_insight_write(
    *,
    query: dict[str, Any] | None,
    filters: dict[str, Any] | None,
    unchanged_query: dict[str, Any] | None = None,
    team: Team,
    user: Writer,
    request: Request | None = None,
) -> None:
    """Record, and once enforced reject, an insight write that no runner could execute."""
    insight_write_validation.validate_insight_write(
        query=query,
        filters=filters,
        unchanged_query=unchanged_query,
        team=team,
        user=user,
        request=request,
    )
