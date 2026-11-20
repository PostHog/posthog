"""Usage, estimated spend and spend settings for the managed warehouse console."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from products.managed_warehouse.backend.facade.contracts import (
    ConsoleSettings,
    UsageBreakdownRow,
    UsageBudget,
    UsageComputeSummary,
    UsageDailyPoint,
    UsageStorageSummary,
    UsageSummary,
)
from products.managed_warehouse.backend.logic import console_pricing
from products.managed_warehouse.backend.logic.console_labels import (
    member_display_names,
    principal_label,
    principal_team_ids,
    source_label,
    sql_editor_user_ids,
    team_display_names,
)
from products.managed_warehouse.backend.logic.console_upstream import call_control_plane, malformed_body_guard
from products.managed_warehouse.backend.models import ManagedWarehouseOrgSettings
from products.managed_warehouse.backend.presentation import hogtower

Period = Literal["current_month", "last_month"]
BreakdownBy = Literal["source", "principal", "team"]

BREAKDOWN_LIMIT = 20
OTHER_KEY = "other"
CONTROL_PLANE_OTHER_KEY = "__other__"
# Scaling a few hours of usage to a whole month gives meaningless numbers, so the console shows
# no forecast until a full day of the month has passed.
MIN_FORECAST_ELAPSED_SECONDS = 86400
UNATTRIBUTED_LABEL = "Unattributed"


def _month_bounds(period: Period, today: date) -> tuple[date, date]:
    this_month = today.replace(day=1)
    start = this_month if period == "current_month" else (this_month - timedelta(days=1)).replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month


def _int(value: Any) -> int:
    return int(value) if value is not None else 0


def _label_breakdown_key(
    group_by: BreakdownBy, key: str, member_names: dict[int, str], team_names: dict[int, str]
) -> str:
    if group_by == "source":
        return source_label(key)
    if group_by == "principal":
        return principal_label(key, member_names, team_names)
    return f"Project {key}" if key else UNATTRIBUTED_LABEL


def _key(row: dict[str, Any]) -> str:
    return "" if row["key"] is None else str(row["key"])


def _breakdown(
    all_rows: list[dict[str, Any]], group_by: BreakdownBy, organization_id: str, compute_cost: Decimal
) -> tuple[UsageBreakdownRow, ...]:
    # hogtower folds the keys beyond its own limit into one row. It joins our Other row below.
    rows = [r for r in all_rows if _key(r) != CONTROL_PLANE_OTHER_KEY]
    control_plane_other = [r for r in all_rows if _key(r) == CONTROL_PLANE_OTHER_KEY]
    total_billable = sum(_int(r.get("billable_bytes")) for r in all_rows)
    member_names = (
        member_display_names(organization_id, sql_editor_user_ids(_key(r) for r in rows))
        if group_by == "principal"
        else {}
    )

    team_names = (
        team_display_names(organization_id, principal_team_ids(_key(r) for r in rows))
        if group_by == "principal"
        else {}
    )

    def share(billable: int) -> Decimal:
        return compute_cost * billable / total_billable if total_billable else Decimal(0)

    ranked = sorted(rows, key=lambda r: (-_int(r.get("billable_bytes")), -_int(r.get("queries")), _key(r)))
    result = [
        UsageBreakdownRow(
            key=_key(r),
            label=_label_breakdown_key(group_by, _key(r), member_names, team_names),
            queries=_int(r.get("queries")),
            billable_bytes=_int(r.get("billable_bytes")),
            estimated_cost_share_usd=share(_int(r.get("billable_bytes"))),
        )
        for r in ranked[:BREAKDOWN_LIMIT]
    ]
    rest = ranked[BREAKDOWN_LIMIT:] + control_plane_other
    if rest:
        rest_billable = sum(_int(r.get("billable_bytes")) for r in rest)
        result.append(
            UsageBreakdownRow(
                key=OTHER_KEY,
                label="Other",
                queries=sum(_int(r.get("queries")) for r in rest),
                billable_bytes=rest_billable,
                estimated_cost_share_usd=share(rest_billable),
            )
        )
    return tuple(result)


def _forecast(billable_bytes: int, byte_seconds: Decimal, month_start: date, now: datetime) -> Decimal:
    month_seconds = console_pricing.seconds_in_month(month_start)
    elapsed = (now - datetime(month_start.year, month_start.month, month_start.day, tzinfo=UTC)).total_seconds()
    factor = Decimal(month_seconds) / Decimal(max(elapsed, MIN_FORECAST_ELAPSED_SECONDS))
    scaled_bytes = int(Decimal(billable_bytes) * factor)
    gib_months = console_pricing.storage_gib_months(byte_seconds * factor, month_start)
    return console_pricing.compute_cost_usd(scaled_bytes) + console_pricing.storage_cost_usd(gib_months)


def _forecast_or_none(billable_bytes: int, byte_seconds: Decimal, month_start: date, now: datetime) -> Decimal | None:
    elapsed = (now - datetime(month_start.year, month_start.month, month_start.day, tzinfo=UTC)).total_seconds()
    if elapsed < MIN_FORECAST_ELAPSED_SECONDS:
        return None
    return _forecast(billable_bytes, byte_seconds, month_start, now)


def _seconds_covered(day: date, now: datetime) -> int:
    """Seconds of ``day`` that usage can cover: a whole day, or for today only the time since 00:00 UTC.

    The floor of one hour stops the first minutes of a day from producing a spike.
    """
    if day != now.date():
        return 86400
    since_midnight = (now - datetime(day.year, day.month, day.day, tzinfo=UTC)).total_seconds()
    return int(max(since_midnight, 3600))


def _average_stored_bytes(byte_seconds: Decimal, period_start: date, period_end: date, now: datetime) -> int:
    """Average bytes stored over the part of the period that has passed. Display only: pricing uses GiB-months."""
    start = datetime(period_start.year, period_start.month, period_start.day, tzinfo=UTC)
    end = datetime(period_end.year, period_end.month, period_end.day, tzinfo=UTC)
    elapsed = (min(now, end) - start).total_seconds()
    return int(byte_seconds / Decimal(elapsed)) if elapsed > 0 else 0


def build_usage_summary(
    organization_id: str, *, period: Period, group_by: BreakdownBy, now: datetime | None = None
) -> UsageSummary:
    now = now or datetime.now(UTC)
    today = now.date()
    period_start, period_end = _month_bounds(period, today)
    query_end = min(period_end, today + timedelta(days=1))

    def fetch(by: str) -> dict[str, Any]:
        return call_control_plane(
            lambda: hogtower.get_usage(organization_id, date_from=period_start, date_to=query_end, group_by=by)
        )

    by_day = fetch("day")
    by_breakdown = fetch(group_by)

    with malformed_body_guard():
        return _summarize(
            organization_id, period, group_by, now, (period_start, period_end, query_end), by_day, by_breakdown
        )


def _summarize(
    organization_id: str,
    period: Period,
    group_by: BreakdownBy,
    now: datetime,
    bounds: tuple[date, date, date],
    by_day: dict[str, Any],
    by_breakdown: dict[str, Any],
) -> UsageSummary:
    period_start, period_end, query_end = bounds
    day_rows = {str(r["key"]): r for r in by_day.get("compute", [])}
    storage_by_day = {str(r["day"]): Decimal(str(r["byte_seconds"])) for r in by_day.get("storage", [])}

    billable = sum(_int(r.get("billable_bytes")) for r in day_rows.values())
    failed = sum(_int(r.get("failed_billable_bytes")) for r in day_rows.values())
    logical = sum(_int(r.get("logical_bytes_scanned")) for r in day_rows.values())
    queries = sum(_int(r.get("queries")) for r in day_rows.values())
    byte_seconds = sum(storage_by_day.values(), Decimal(0))

    compute_cost = console_pricing.compute_cost_usd(billable)
    gib_months = console_pricing.storage_gib_months(byte_seconds, period_start)
    storage_cost = console_pricing.storage_cost_usd(gib_months)
    total = compute_cost + storage_cost

    daily = []
    day = period_start
    while day < query_end:
        row = day_rows.get(day.isoformat(), {})
        daily.append(
            UsageDailyPoint(
                date=day,
                billable_bytes=_int(row.get("billable_bytes")),
                queries=_int(row.get("queries")),
                storage_average_bytes=int(storage_by_day.get(day.isoformat(), Decimal(0)) / _seconds_covered(day, now)),
            )
        )
        day += timedelta(days=1)

    budget = get_console_settings(organization_id).monthly_budget_usd
    share_used = total / budget if budget else None

    return UsageSummary(
        period_start=period_start,
        period_end=period_end,
        compute=UsageComputeSummary(
            billable_bytes=billable,
            failed_billable_bytes=failed,
            logical_bytes=logical,
            queries=queries,
            free_bytes=console_pricing.COMPUTE_FREE_BYTES,
            estimated_cost_usd=compute_cost,
        ),
        storage=UsageStorageSummary(
            gib_months=gib_months,
            average_bytes=_average_stored_bytes(byte_seconds, period_start, period_end, now),
            free_gib_months=console_pricing.STORAGE_FREE_GIB_MONTHS,
            estimated_cost_usd=storage_cost,
        ),
        total_estimated_cost_usd=total,
        forecast_total_usd=(
            _forecast_or_none(billable, byte_seconds, period_start, now) if period == "current_month" else None
        ),
        daily=tuple(daily),
        breakdown=_breakdown(by_breakdown.get("compute", []), group_by, organization_id, compute_cost),
        budget=UsageBudget(monthly_budget_usd=budget, share_used=share_used),
    )


def get_console_settings(organization_id: str) -> ConsoleSettings:
    row = ManagedWarehouseOrgSettings.objects.filter(organization_id=organization_id).first()
    if row is None:
        return ConsoleSettings(max_scan_bytes_per_query=None, monthly_budget_usd=None)
    return ConsoleSettings(
        max_scan_bytes_per_query=row.max_scan_bytes_per_query, monthly_budget_usd=row.monthly_budget_usd
    )


def update_console_settings(organization_id: str, *, changes: Mapping[str, int | Decimal | None]) -> ConsoleSettings:
    """Write only the settings in ``changes``, so a concurrent change to another setting survives."""
    defaults: dict[str, Any] = dict(changes)
    if (
        "monthly_budget_usd" in changes
        and get_console_settings(organization_id).monthly_budget_usd != changes["monthly_budget_usd"]
    ):
        # A new budget starts a fresh alert cycle.
        defaults.update(budget_alert_month=None, budget_alert_threshold=None)
    ManagedWarehouseOrgSettings.objects.update_or_create(organization_id=organization_id, defaults=defaults)
    return get_console_settings(organization_id)


def get_max_scan_bytes_per_query(organization_id: str) -> int | None:
    return (
        ManagedWarehouseOrgSettings.objects.filter(organization_id=organization_id)
        .values_list("max_scan_bytes_per_query", flat=True)
        .first()
    )


@dataclass(frozen=True)
class SpendEstimate:
    month_start: date
    total_usd: Decimal
    forecast_usd: Decimal


def estimate_month_to_date_spend(organization_id: str, *, now: datetime | None = None) -> SpendEstimate:
    """Month-to-date estimated spend and forecast for the current UTC month, with one control plane call."""
    now = now or datetime.now(UTC)
    today = now.date()
    month_start, _ = _month_bounds("current_month", today)
    by_day = call_control_plane(
        lambda: hogtower.get_usage(
            organization_id, date_from=month_start, date_to=today + timedelta(days=1), group_by="day"
        )
    )
    billable = sum(_int(r.get("billable_bytes")) for r in by_day.get("compute", []))
    byte_seconds = sum((Decimal(str(r["byte_seconds"])) for r in by_day.get("storage", [])), Decimal(0))
    total = console_pricing.compute_cost_usd(billable) + console_pricing.storage_cost_usd(
        console_pricing.storage_gib_months(byte_seconds, month_start)
    )
    return SpendEstimate(
        month_start=month_start,
        total_usd=total,
        forecast_usd=_forecast(billable, byte_seconds, month_start, now),
    )
