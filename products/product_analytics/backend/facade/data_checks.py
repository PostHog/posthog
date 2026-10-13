"""
Data checks on the events an insight reads.

Split out of ``facade.api`` for the same reason as ``facade.account_filters``: the implementation
runs a HogQL query, and that import chain is too heavy for the light facade module.
"""

from collections.abc import Mapping
from typing import Any

from posthog.models.team import Team

from products.product_analytics.backend import insight_data_checks
from products.product_analytics.backend.facade.contracts import InsightDataChecks


def run_insight_data_checks(query: Mapping[str, Any], *, team: Team) -> InsightDataChecks:
    """Check the events an insight query reads for local traffic, bots and events sent twice."""
    return insight_data_checks.run_insight_data_checks(query, team)
