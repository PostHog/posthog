from collections.abc import Collection
from datetime import UTC, date, datetime
from uuid import UUID

from django.db.models import DateTimeField, F, Q, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncDate
from django.db.models.lookups import GreaterThan, LessThanOrEqual
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.models import Team

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


def uses_spend_billing(team_id: int, *, started_at: datetime | None = None) -> bool:
    cutoff = Team.objects.values_list("organization__usage__signals_spend_credits__billing_start_date", flat=True).get(
        id=team_id
    )
    return bool(cutoff and (started_at or timezone.now()).astimezone(UTC).date() >= date.fromisoformat(cutoff))


def _spend_credits_by_team(
    begin: datetime,
    end: datetime,
    *,
    organization_id: str | UUID | None = None,
    organization_ids: Collection[str | UUID] | None = None,
    include_running: bool,
) -> dict[int, int]:
    if end <= begin:
        return {}
    eligible = Q(usage_billing=True, billing_exempt=False)
    if organization_id is not None:
        eligible &= Q(team__organization_id=organization_id)
    if organization_ids is not None:
        eligible &= Q(team__organization_id__in=organization_ids)
    # Running costs belong in quota checks before their final receipt becomes billable.
    now = timezone.now()
    period = Q(finalized_at__gte=begin, finalized_at__lt=end)
    if include_running and begin <= now < end:
        period_start = Cast(KeyTextTransform("0", "team__organization__usage__period"), DateTimeField())
        period_end = Cast(KeyTextTransform("1", "team__organization__usage__period"), DateTimeField())
        period |= Q(
            LessThanOrEqual(period_start, Value(now)),
            GreaterThan(period_end, Value(now)),
            finalized_at__isnull=True,
            accounting_failed=False,
            created_at__gte=period_start,
        )
    usage_at = Coalesce("finalized_at", Value(now)) if include_running else F("finalized_at")
    # Deliberately cross-team: both usage reporting and organization quota use this aggregation.
    totals = (
        SignalSpend.objects.unscoped()
        .alias(usage_at=usage_at)
        .filter(eligible, period)
        .values("team_id", day=TruncDate("usage_at", tzinfo=UTC))
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
) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass -- usage-counter contract
    return list(
        _spend_credits_by_team(
            begin, end, organization_id=organization_id, organization_ids=organization_ids, include_running=False
        ).items()
    )


def get_signals_spend_quota_credits_by_team(
    begin: datetime,
    end: datetime,
    organization_id: str | UUID | None = None,
) -> list[tuple[int, int]]:  # nosemgrep: tuple-return-prefer-dataclass -- usage-counter contract
    return list(_spend_credits_by_team(begin, end, organization_id=organization_id, include_running=True).items())


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    if report.billing_exempt_reason:
        spend.billing_exempt = True
