"""
Data checks on the events an insight reads.

Split out of ``facade.api`` for the same reason as ``facade.account_filters``: the implementation
runs a HogQL query, and that import chain is too heavy for the light facade module.
"""

from collections.abc import Mapping
from typing import Any

from posthog.models.team import Team
from posthog.models.user import User

from products.product_analytics.backend import insight_data_checks
from products.product_analytics.backend.facade.contracts import InsightDataChecks, TeamEmailAccess
from products.product_analytics.backend.facade.enums import InsightDataChecksDepth


def run_insight_data_checks(
    query: Mapping[str, Any],
    *,
    team: Team,
    user: User,
    email_access: TeamEmailAccess,
    depth: InsightDataChecksDepth = InsightDataChecksDepth.QUICK,
) -> InsightDataChecks:
    """Check the events an insight query reads for internal users, local traffic, bots and events sent twice.

    The checks read the events as `user`. They do not run when a property they read is hidden from that person.
    The internal users check matches only the member emails and verified domains that `email_access` allows, and
    names the emails it finds only when `email_access` allows person emails.
    A quick check does not run when it would read a lot of data. A full check runs with the insight query's own limits.
    """
    return insight_data_checks.run_insight_data_checks(query, team, user, email_access=email_access, depth=depth)
