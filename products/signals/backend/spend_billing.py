from datetime import UTC, date, datetime, time
from uuid import UUID

from django.db.models import Q, QuerySet, Sum
from django.db.models.functions import TruncDate

import structlog
import posthoganalytics

from posthog.models import Team

from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.free_trial import SELF_DRIVING_FREE_TRIAL_FLAG
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend

logger = structlog.get_logger(__name__)
USAGE_BILLING_FLAG = "self-driving-usage-based-billing"


def system_source_exempt(source_product: str | None) -> bool:
    return source_product in {SignalSourceProduct.HEALTH_CHECKS, SignalSourceProduct.ENGINEERING_ANALYTICS}


def scout_spend_exempt(scout: SignalScoutRun) -> bool:
    from products.signals.backend.billing import (  # noqa: PLC0415 — billing uses this module for aggregation
        BILLING_EXEMPT_SCOUT_SKILLS,
        _scout_skill_is_canonical,
    )

    return scout.trial_state is not None or (
        scout.skill_name in BILLING_EXEMPT_SCOUT_SKILLS
        and _scout_skill_is_canonical(scout.team_id, scout.skill_name, version=scout.skill_version)
    )


def trial_spend_exempt(team_id: int) -> bool:
    org_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))
    return (
        posthoganalytics.feature_enabled(
            SELF_DRIVING_FREE_TRIAL_FLAG,
            org_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        is True
    )


def usage_billing_cutoff(organization_id: UUID) -> datetime | None:
    try:
        org_id = str(organization_id)
        value = posthoganalytics.get_feature_flag(
            USAGE_BILLING_FLAG,
            org_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if not isinstance(value, str):
            return None
        cutoff = date.fromisoformat(value)
        if cutoff.isoformat() != value:
            return None
        # Trials, including an unknown trial status, retain the report meter.
        trial = posthoganalytics.feature_enabled(
            SELF_DRIVING_FREE_TRIAL_FLAG,
            org_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        return datetime.combine(cutoff, time.min, UTC) if trial is False else None
    except ValueError:
        logger.warning("signals.spend.billing_cutoff_invalid", organization_id=str(organization_id))
        return None
    except Exception:
        logger.exception("signals.spend.billing_flag_unavailable", organization_id=str(organization_id))
        return None


def usage_billed_reports(cutoffs: dict[UUID, datetime]) -> QuerySet[SignalReport]:
    eligible = Q(pk__in=[])
    for organization_id, cutoff in cutoffs.items():
        eligible |= Q(team__organization_id=organization_id, created_at__gte=cutoff)
    return SignalReport.objects.filter(eligible)


def task_run_uses_usage_billing(team: Team, run_id: UUID) -> bool:
    cutoff = usage_billing_cutoff(team.organization_id)
    return (
        cutoff is not None
        and SignalSpend.objects.for_team(team.id)
        .filter(task_run_id=run_id, created_at__gte=cutoff, billing_exempt=False)
        .exists()
    )


def spend_billing_credits_by_team(begin: datetime, end: datetime, *, cutoffs: dict[UUID, datetime]) -> dict[int, int]:
    if end <= begin or not cutoffs:
        return {}
    eligible = Q(pk__in=[])
    for organization_id, cutoff in cutoffs.items():
        eligible |= Q(team__organization_id=organization_id, created_at__gte=cutoff)
    # Deliberately cross-team: both usage reporting and organization quota use this meter.
    totals = (
        SignalSpend.objects.unscoped()
        .filter(eligible, finalized_at__gte=begin, finalized_at__lt=end, billing_exempt=False)
        .values("team_id", day=TruncDate("finalized_at", tzinfo=UTC))
        .annotate(total_spend=Sum("spend"))
    )
    credits: dict[int, int] = {}
    # Round once per team/day, so a period recount equals the daily reports billing sums.
    for total in totals.iterator(chunk_size=1000):
        team_id = total["team_id"]
        credits[team_id] = credits.get(team_id, 0) + round(total["total_spend"])
    return {team_id: amount for team_id, amount in credits.items() if amount}


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    if report.billing_exempt_reason:
        spend.billing_exempt = True
