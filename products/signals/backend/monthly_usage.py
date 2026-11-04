from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import batched
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.signals.backend.models import SignalScoutRun, SignalSpend
from products.signals.backend.pricing import SIGNALS_CREDITS_PER_DOLLAR
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery, _signals_query_context

if TYPE_CHECKING:
    from posthog.models import Team


@frozen
class UsageSource:
    source_product: str | None
    source_type: str | None


@frozen(frozen=False)
class MonthlySourceUsage:
    source_product: str | None
    source_type: str | None
    processing_credits: Decimal = Decimal(0)
    research_credits: Decimal = Decimal(0)
    implementation_credits: Decimal = Decimal(0)
    total_credits: Decimal = Decimal(0)
    exempt_credits: Decimal = Decimal(0)
    incomplete: bool = False


@frozen
class MonthlyScoutUsage:
    scout_config_id: UUID | None
    skill_name: str
    display_name: str
    total_credits: Decimal
    exempt_credits: Decimal
    run_count: int
    reports_produced: int
    incomplete: bool


@frozen
class UsagePricing:
    currency: str = "USD"
    usd_per_credit: Decimal = Decimal(1) / SIGNALS_CREDITS_PER_DOLLAR


@frozen
class MonthlyUsage:
    project_id: int
    period_start: datetime
    period_end: datetime
    as_of: datetime
    total_credits: Decimal
    exempt_credits: Decimal
    unsettled_credits: Decimal
    untracked_scout_run_count: int
    incomplete: bool
    attribution_incomplete: bool
    sources: list[MonthlySourceUsage]
    scouts: list[MonthlyScoutUsage]
    pricing: UsagePricing


def _signal_sources(team: "Team", signal_ids: set[str]) -> dict[str, UsageSource]:
    sources: dict[str, UsageSource] = {}
    if not signal_ids:
        return sources
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    query = f"""
        SELECT document_id,
               JSONExtractString(metadata, 'source_product'),
               JSONExtractString(metadata, 'source_type')
        FROM ({_deduped_signals_subquery(include_content=False, extra_where="document_id IN {signal_ids} AND rendering = 'plain'")})
        LIMIT {{batch_size}}
    """
    for batch in batched(sorted(signal_ids), 1000, strict=False):
        result = execute_hogql_query(
            query=query,
            team=team,
            context=_signals_query_context(team),
            ch_user=ClickHouseUser.SIGNALS,
            workload=Workload.ONLINE,
            query_type="SignalsMonthlyUsageSources",
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "signal_ids": ast.Tuple(exprs=[ast.Constant(value=signal_id) for signal_id in batch]),
                "batch_size": ast.Constant(value=len(batch)),
            },
        )
        for signal_id, product, source_type in result.results or []:
            sources[str(signal_id)] = UsageSource(source_product=product or None, source_type=source_type or None)
    return sources


def _source_usage(team: "Team", receipts: QuerySet[SignalSpend]) -> list[MonthlySourceUsage]:
    rows = (
        receipts.exclude(kind=SignalSpend.Kind.SCOUT_RUN)
        .annotate(source_signal_id=Coalesce("signal_id", "report__triggering_signal_id"))
        .values("source_signal_id", "kind")
        .annotate(
            credits=Sum("spend"),
            exempt=Sum("spend", filter=Q(billing_exempt=True), default=0),
            failed=Count("id", filter=Q(accounting_failed=True)),
        )
    )
    unknown = UsageSource(source_product=None, source_type=None)
    totals: dict[UsageSource, MonthlySourceUsage] = {}
    for batch in batched(rows.iterator(chunk_size=1000), 1000, strict=False):
        sources = _signal_sources(team, {str(row["source_signal_id"]) for row in batch if row["source_signal_id"]})
        for row in batch:
            source = sources.get(str(row["source_signal_id"]), unknown)
            usage = totals.setdefault(
                source, MonthlySourceUsage(source_product=source.source_product, source_type=source.source_type)
            )
            amount = row["credits"]
            if row["kind"] == SignalSpend.Kind.AD_HOC:
                usage.processing_credits += amount
            elif row["kind"] in {SignalSpend.Kind.RESEARCH, SignalSpend.Kind.REPO_SELECTION}:
                usage.research_credits += amount
            else:
                usage.implementation_credits += amount
            usage.total_credits += amount
            usage.exempt_credits += row["exempt"]
            usage.incomplete |= bool(row["failed"])
    return sorted(
        totals.values(), key=lambda row: (-row.total_credits, row.source_product or "", row.source_type or "")
    )


def _scout_usage(team_id: int, receipts: QuerySet[SignalSpend]) -> list[MonthlyScoutUsage]:
    scout_receipts = receipts.filter(kind=SignalSpend.Kind.SCOUT_RUN)
    reports_by_scout: dict[tuple[UUID | None, str], set[str]] = {}
    for config_id, skill, report_ids in (
        SignalScoutRun.objects.for_team(team_id)
        .filter(id__in=scout_receipts.values("scout_run_id"))
        .values_list("scout_config_id", "skill_name", "emitted_report_ids")
        .iterator(chunk_size=1000)
    ):
        reports_by_scout.setdefault((config_id, skill), set()).update(report_ids or [])
    rows = scout_receipts.values(
        "scout_run__scout_config_id", "scout_run__skill_name", "scout_run__scout_config__display_name"
    ).annotate(
        credits=Sum("spend"),
        exempt=Sum("spend", filter=Q(billing_exempt=True), default=0),
        runs=Count("scout_run_id", distinct=True),
        failed=Count("id", filter=Q(accounting_failed=True)),
    )
    return [
        MonthlyScoutUsage(
            scout_config_id=row["scout_run__scout_config_id"],
            skill_name=row["scout_run__skill_name"] or "unknown",
            display_name=row["scout_run__scout_config__display_name"]
            or row["scout_run__skill_name"]
            or "Unknown scout",
            total_credits=row["credits"],
            exempt_credits=row["exempt"],
            run_count=row["runs"],
            reports_produced=len(
                reports_by_scout.get((row["scout_run__scout_config_id"], row["scout_run__skill_name"]), set())
            ),
            incomplete=bool(row["failed"]),
        )
        for row in rows.order_by("-credits", "scout_run__skill_name", "scout_run__scout_config_id")
    ]


def monthly_usage(*, team: "Team", month: date | None = None) -> MonthlyUsage:
    team = team.parent_team or team
    now = timezone.now()
    selected_month = month or now.astimezone(UTC).date()
    start = datetime(selected_month.year, selected_month.month, 1, tzinfo=UTC)
    end = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=UTC)
    private_runs = SignalScoutRun.objects.for_team(team.id).filter(metadata__has_key="scout_trial")
    receipts = (
        SignalSpend.objects.for_team(team.id)
        .filter(kind__isnull=False)
        .exclude(scout_run_id__in=private_runs.values("id"))
    )
    settled = receipts.filter(finalized_at__gte=start, finalized_at__lt=min(end, now))
    sources = _source_usage(team, settled)
    scouts = _scout_usage(team.id, settled)
    unsettled = receipts.filter(finalized_at__isnull=True, created_at__gte=start, created_at__lt=min(end, now))
    pending = unsettled.aggregate(credits=Sum("spend", default=0), count=Count("id"))
    untracked_runs = (
        SignalScoutRun.objects.for_team(team.id)
        .filter(created_at__gte=start, created_at__lt=min(end, now))
        .exclude(metadata__has_key="scout_trial")
        .exclude(id__in=receipts.filter(kind=SignalSpend.Kind.SCOUT_RUN).values("scout_run_id"))
        .count()
    )
    buckets: list[MonthlySourceUsage | MonthlyScoutUsage] = [*sources, *scouts]
    return MonthlyUsage(
        project_id=team.id,
        period_start=start,
        period_end=end,
        as_of=now,
        total_credits=sum((row.total_credits for row in buckets), Decimal(0)),
        exempt_credits=sum((row.exempt_credits for row in buckets), Decimal(0)),
        unsettled_credits=pending["credits"],
        untracked_scout_run_count=untracked_runs,
        incomplete=bool(pending["count"] or untracked_runs or any(row.incomplete for row in buckets)),
        attribution_incomplete=any(row.source_product is None or row.source_type is None for row in sources),
        sources=sources,
        scouts=scouts,
        pricing=UsagePricing(),
    )
