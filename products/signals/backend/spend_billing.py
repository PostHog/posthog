"""Billing decisions and daily recognition for cumulative owner spend."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet

import structlog
import posthoganalytics

from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.free_trial import SELF_DRIVING_FREE_TRIAL_FLAG
from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend

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
        scout.skill_name in BILLING_EXEMPT_SCOUT_SKILLS and _scout_skill_is_canonical(scout.team_id, scout.skill_name)
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
        older_signal = SignalSpend.objects.unscoped().filter(
            team_id=OuterRef("team_id"), signal_id=OuterRef("triggering_signal_id"), created_at__lt=cutoff
        )
        eligible |= Q(team__organization_id=organization_id, created_at__gte=cutoff) & ~Q(Exists(older_signal))
    return SignalReport.objects.filter(eligible)


def recognize_spend(spend: SignalSpend, *, now: datetime) -> None:
    if spend.billing_exempt or not spend.finalized_at:
        return
    total = int(cost_to_spend(spend.token_cost_microusd, task_count=spend.task_count) * 10_000)
    recognized = sum(spend.billing_amounts.values())
    if total < recognized:
        # Already reported days are immutable. A downward correction needs the refund path.
        logger.error("signals.spend.billing_cost_decreased", team_id=spend.team_id, spend_id=str(spend.id))
        spend.accounting_failed = True
        spend.finalized_at = None
        return
    if total > recognized:
        day = now.astimezone(UTC).date().isoformat()
        spend.billing_amounts[day] = spend.billing_amounts.get(day, 0) + total - recognized


def billing_days(begin: datetime, end: datetime) -> list[str]:
    if end <= begin:
        return []
    days = []
    day = begin.astimezone(UTC).date()
    last_day = (end.astimezone(UTC) - timedelta(microseconds=1)).date()
    while day <= last_day:
        days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def spend_billing_credits_by_team(begin: datetime, end: datetime, *, cutoffs: dict[UUID, datetime]) -> dict[int, int]:
    days = billing_days(begin, end)
    if not days or not cutoffs:
        return {}
    eligible = Q(pk__in=[])
    for organization_id, cutoff in cutoffs.items():
        eligible |= Q(team__organization_id=organization_id, created_at__gte=cutoff)
    # Resumed work on an older report must not acquire a second, spend-based charge.
    reports = usage_billed_reports(cutoffs).filter(id=OuterRef("report_id"), team_id=OuterRef("team_id"))
    # Deliberately cross-team: both usage reporting and organization quota use this meter.
    spends = (
        SignalSpend.objects.unscoped()
        .filter(eligible, billing_exempt=False, billing_amounts__has_any_keys=days)
        .filter(Q(report_id__isnull=True) | Exists(reports))
    )
    totals: dict[tuple[int, str], int] = {}
    for team_id, amounts in spends.values_list("team_id", "billing_amounts").iterator(chunk_size=1000):
        for day in days:
            if day in amounts:
                totals[team_id, day] = totals.get((team_id, day), 0) + amounts[day]
    credits: dict[int, int] = {}
    # Round once per team/day, so a period recount equals the daily reports billing sums.
    for (team_id, _), amount in totals.items():
        credits[team_id] = credits.get(team_id, 0) + round(Decimal(amount) / 10_000)
    return {team_id: amount for team_id, amount in credits.items() if amount}


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    if report.billing_exempt_reason:
        spend.billing_exempt = True
