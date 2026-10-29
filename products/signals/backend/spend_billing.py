from collections.abc import Collection
from datetime import UTC, date, datetime, time
from uuid import UUID

from django.db.models import Q, Sum
from django.db.models.functions import TruncDate

import structlog
import posthoganalytics

from posthog.models import Organization, Team

from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.free_trial import SELF_DRIVING_FREE_TRIAL_FLAG
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend

logger = structlog.get_logger(__name__)


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


def usage_billing_cutoffs(
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
) -> dict[UUID, datetime]:
    organizations = Organization.objects.filter(usage__signals_spend_credits__has_key="billing_start_date")
    if organization_id is not None:
        organizations = organizations.filter(id=organization_id)
    if organization_ids is not None:
        organizations = organizations.filter(id__in=organization_ids)
    cutoffs: dict[UUID, datetime] = {}
    for org_id, value in organizations.values_list("id", "usage__signals_spend_credits__billing_start_date"):
        cutoff = date.fromisoformat(value)
        if cutoff.isoformat() != value:
            raise ValueError(f"Invalid Inbox billing cutoff for organization {org_id}")
        cutoffs[org_id] = datetime.combine(cutoff, time.min, UTC)
    return cutoffs


def usage_billing_cutoff(organization_id: UUID) -> datetime | None:
    return usage_billing_cutoffs(organization_id).get(organization_id)


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


def get_signals_spend_billing_credits_by_team(
    begin: datetime,
    end: datetime,
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass — usage-counter contract
    return list(
        spend_billing_credits_by_team(
            begin, end, cutoffs=usage_billing_cutoffs(organization_id, organization_ids)
        ).items()
    )


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    if report.billing_exempt_reason:
        spend.billing_exempt = True
