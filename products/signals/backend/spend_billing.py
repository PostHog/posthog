"""Billing decisions and daily recognition for cumulative owner spend."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
import posthoganalytics

from posthog.models import Team

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


def usage_billing_enabled(team_id: int) -> bool | None:
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(id=team_id))

        def enabled(key: str) -> bool | None:
            return posthoganalytics.feature_enabled(
                key,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )

        # Trials keep their existing report meter (and no PR means no charge).
        # Unknown trial status must not silently turn free research into billable usage.
        usage = enabled(USAGE_BILLING_FLAG)
        if usage is not True:
            if usage is None:
                logger.warning("signals.spend.billing_mode_unknown", team_id=team_id)
            return usage
        trial = enabled(SELF_DRIVING_FREE_TRIAL_FLAG)
        if trial is None:
            logger.warning("signals.spend.billing_trial_status_unknown", team_id=team_id)
        return not trial if trial is not None else None
    except Exception:
        logger.exception("signals.spend.billing_flag_unavailable", team_id=team_id)
        return None


def report_usage_billing_mode(
    *, team_id: int, signal_id: str | None = None, scout_run_id: str | None = None
) -> bool | None:
    if signal_id or scout_run_id:
        owner = {"signal_id": signal_id} if signal_id else {"scout_run_id": scout_run_id}
        spend = SignalSpend.objects.for_team(team_id).filter(**owner).first()
        if spend is not None:
            return spend.usage_based_billing
    return usage_billing_enabled(team_id)


def recognize_spend(spend: SignalSpend, *, now: datetime) -> None:
    if not spend.usage_based_billing or spend.billing_exempt or not spend.finalized_at:
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


def spend_billing_credits_by_team(
    begin: datetime, end: datetime, *, organization_id: str | None = None
) -> dict[int, int]:
    if end <= begin:
        return {}
    days = []
    day = begin.astimezone(UTC).date()
    last_day = (end.astimezone(UTC) - timedelta(microseconds=1)).date()
    while day <= last_day:
        days.append(day.isoformat())
        day += timedelta(days=1)
    # Deliberately cross-team: both usage reporting and organization quota use this meter.
    spends = SignalSpend.objects.unscoped().filter(billing_amounts__has_any_keys=days)
    if organization_id is not None:
        spends = spends.filter(team__organization_id=organization_id)
    totals: dict[tuple[int, str], int] = {}
    for team_id, amounts in spends.values_list("team_id", "billing_amounts").iterator(chunk_size=1000):
        for date in days:
            if date in amounts:
                totals[team_id, date] = totals.get((team_id, date), 0) + amounts[date]
    credits: dict[int, int] = {}
    # Round once per team/day, so a period recount equals the daily reports billing sums.
    for (team_id, _), amount in totals.items():
        credits[team_id] = credits.get(team_id, 0) + round(Decimal(amount) / 10_000)
    return {team_id: amount for team_id, amount in credits.items() if amount}


def apply_report_billing(spend: SignalSpend, report: SignalReport) -> None:
    # Existing reports keep their original meter, including work resumed after a flag change.
    if report.usage_based_billing is not True:
        spend.usage_based_billing = report.usage_based_billing
    if report.billing_exempt_reason:
        spend.billing_exempt = True
