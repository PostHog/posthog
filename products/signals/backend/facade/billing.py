"""Signals credit usage, for the usage report and the quota checks in core."""

import uuid
from collections.abc import Collection
from datetime import datetime

from posthog.dataclasses import frozen

from products.signals.backend import billing


@frozen
class TeamSignalsCredits:
    team_id: int
    credits: int


def signals_billing_credits_by_team(
    begin: datetime,
    end: datetime,
    *,
    organization_id: str | uuid.UUID | None = None,
    organization_ids: Collection[str | uuid.UUID] | None = None,
) -> list[TeamSignalsCredits]:
    """Billable signals credits in ``[begin, end)`` for each team with non-zero usage.

    Covers every organization unless ``organization_id`` or ``organization_ids`` narrows the scan.
    """
    rows = billing.get_signals_billing_credits_by_team(
        begin, end, organization_id=organization_id, organization_ids=organization_ids
    )
    return [TeamSignalsCredits(team_id=team_id, credits=credits) for team_id, credits in rows]


def credited_refund_credits_for_org(organization_id: str | uuid.UUID, begin: datetime, end: datetime) -> int:
    """Credits that credited-path refunds returned for the org's pull request runs created in ``[begin, end)``."""
    return billing.credited_refund_credits_for_org(organization_id, begin, end)
