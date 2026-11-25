"""Conditions of the inbox list that other reads apply too.

The inbox digest counts the reports that the list returns for `view=actionable&unclaimed=true`. Both read the
conditions from here, so the count and the list cannot disagree.
"""

from django.db.models import Q

from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.implementation_pr import implementation_pr_report_filter
from products.signals.backend.models import SignalReport
from products.signals.backend.report_claims import reports_with_active_claim


def implementation_pr_condition(*, team_id: int, cached: bool, active_only: bool = False) -> Q:
    """Reports with an implementation PR. `cached` reads the columns that implementation_pr_cache.py keeps current,
    in place of the link subqueries."""
    if cached:
        return Q(has_active_implementation_pr=True) if active_only else Q(has_implementation_pr=True)
    return implementation_pr_report_filter(team_id=team_id, active_only=active_only)


def actionable_condition(*, team_id: int, cached: bool) -> Q:
    """The list's `view=actionable`: ready, judged immediately actionable, not already addressed, and with no
    implementation PR."""
    return Q(
        status=SignalReport.Status.READY,
        latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
        latest_already_addressed=False,
    ) & ~implementation_pr_condition(team_id=team_id, cached=cached)


def unclaimed_condition(*, team_id: int, cached: bool) -> Q:
    """The list's `unclaimed=true`: not done, with no active claim and no active implementation PR."""
    return (
        ~Q(status__in={SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING, SignalReport.Status.CLOSED})
        & ~reports_with_active_claim(team_id=team_id)
        & ~implementation_pr_condition(team_id=team_id, cached=cached, active_only=True)
    )
