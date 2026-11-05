import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import cached_property
from uuid import UUID

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from posthog.schema import (
    CachedInboxUsageQueryResponse,
    InboxUsage,
    InboxUsagePricing,
    InboxUsageQuery,
    InboxUsageQueryResponse,
    InboxUsageScout,
    InboxUsageSource,
)

from posthog.hogql import ast
from posthog.hogql.database.models import IntegerDatabaseField, UUIDDatabaseField
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.models import SignalScoutRun, SignalSpend
from products.signals.backend.pricing import SIGNALS_CREDITS_PER_DOLLAR
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery, _signals_query_context

# Deleting a report must not erase its source attribution from retained spend records.
_SPEND_REPORTS = PostgresTable(
    name="_inbox_usage_reports",
    postgres_table_name="signals_signalreport",
    fields={
        "id": UUIDDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "triggering_signal_id": UUIDDatabaseField(name="triggering_signal_id", nullable=True),
    },
)


def parse_usage_month(month: str | None) -> date:
    if month is None:
        return timezone.now().astimezone(UTC).date().replace(day=1)
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Enter a valid month in YYYY-MM format.")
    try:
        parsed = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise ValueError("Enter a valid month in YYYY-MM format.") from None
    if parsed.year == 9999:
        raise ValueError("The year must be earlier than 9999.")
    return parsed


def _scout_usage(team_id: int, receipts: QuerySet[SignalSpend]) -> list[InboxUsageScout]:
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
        InboxUsageScout(
            scout_config_id=str(row["scout_run__scout_config_id"]) if row["scout_run__scout_config_id"] else None,
            skill_name=row["scout_run__skill_name"] or "unknown",
            display_name=row["scout_run__scout_config__display_name"]
            or row["scout_run__skill_name"]
            or "Unknown scout",
            total_credits=str(row["credits"]),
            exempt_credits=str(row["exempt"]),
            run_count=row["runs"],
            reports_produced=len(
                reports_by_scout.get((row["scout_run__scout_config_id"], row["scout_run__skill_name"]), set())
            ),
            incomplete=bool(row["failed"]),
        )
        for row in rows.order_by("-credits", "scout_run__skill_name", "scout_run__scout_config_id")
    ]


class InboxUsageQueryRunner(AnalyticsQueryRunner[InboxUsageQueryResponse]):
    query: InboxUsageQuery
    cached_response: CachedInboxUsageQueryResponse

    def __post_init__(self) -> None:
        self.ch_user = ClickHouseUser.SIGNALS
        if self.team.parent_team_id and self.team.parent_team_id != self.team.id:
            raise QueryError("Run the usage query in the parent project that owns the spend records.")
        try:
            month = parse_usage_month(self.query.month)
        except ValueError as error:
            raise QueryError(str(error)) from error
        # A default-month query must stop sharing its cache when the UTC month changes.
        self.query = self.query.model_copy(update={"month": f"{month.year:04}-{month.month:02}"})

    def _reads_events_route(self) -> bool:
        return False

    def validate_query_runner_access(self, user: User) -> bool:
        return UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("signal_usage", "viewer")

    @cached_property
    def as_of(self) -> datetime:
        return timezone.now()

    @cached_property
    def period_start(self) -> datetime:
        month = parse_usage_month(self.query.month)
        return datetime(month.year, month.month, 1, tzinfo=UTC)

    @cached_property
    def period_end(self) -> datetime:
        start = self.period_start
        return datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=UTC)

    @cached_property
    def receipts(self) -> QuerySet[SignalSpend]:
        private_runs = SignalScoutRun.objects.for_team(self.team.id).filter(metadata__has_key="scout_trial")
        return (
            SignalSpend.objects.for_team(self.team.id)
            .filter(kind__isnull=False)
            .exclude(scout_run_id__in=private_runs.values("id"))
        )

    @cached_property
    def settled(self) -> QuerySet[SignalSpend]:
        return self.receipts.filter(
            finalized_at__gte=self.period_start, finalized_at__lt=min(self.period_end, self.as_of)
        )

    def _refresh_frequency(self) -> timedelta:
        return timedelta(minutes=5)

    def cache_target_age(self, last_refresh: datetime | None, lazy: bool = False) -> datetime | None:
        return last_refresh + self._refresh_frequency() if last_refresh else None

    def _is_stale(self, last_refresh: datetime | None, lazy: bool = False) -> bool:
        target = self.cache_target_age(last_refresh)
        return target is None or timezone.now() >= target

    def to_query(self) -> ast.SelectQuery:
        # Finalization can follow signal creation by months, so bound metadata by referenced IDs rather than its timestamp.
        signals = parse_select(
            _deduped_signals_subquery(
                include_content=False,
                extra_where="document_id IN (SELECT source_signal_id FROM spend) AND rendering = 'plain'",
            ),
            placeholders={"model_name": ast.Constant(value=EMBEDDING_MODEL.value)},
        )
        query = parse_select(
            """
            WITH spend AS (
                SELECT coalesce(toString(receipt.signal_id), toString(report.triggering_signal_id)) AS source_signal_id,
                       receipt.kind AS kind, receipt.credits AS credits,
                       receipt.billing_exempt AS exempt, receipt.accounting_failed AS failed
                FROM (
                    SELECT signal_id, report_id, kind, credits, billing_exempt, accounting_failed
                    FROM system.signal_spend
                    WHERE finalized_at >= {period_start} AND finalized_at < {period_end}
                      AND kind != 'scout_run'
                ) AS receipt
                LEFT JOIN (SELECT id, triggering_signal_id FROM _inbox_usage_reports) AS report
                    ON receipt.report_id = report.id
            )
            SELECT nullIf(JSONExtractString(source.metadata, 'source_product'), '') AS source_product,
                   nullIf(JSONExtractString(source.metadata, 'source_type'), '') AS source_type,
                   sumIf(spend.credits, spend.kind = 'ad-hoc'),
                   sumIf(spend.credits, spend.kind IN ('research', 'repo_selection')),
                   sumIf(spend.credits, spend.kind IN ('reviewer_triggered_implementation', 'scout_triggered_implementation')),
                   sum(spend.credits), sumIf(spend.credits, spend.exempt), countIf(spend.failed) > 0
            FROM spend
            LEFT JOIN ({signals}) AS source ON spend.source_signal_id = source.document_id
            GROUP BY source_product, source_type
            ORDER BY sum(spend.credits) DESC, source_product, source_type
            LIMIT 10001
            """,
            placeholders={
                "period_start": ast.Constant(value=self.period_start),
                "period_end": ast.Constant(value=min(self.period_end, self.as_of)),
                "signals": signals,
            },
        )

        assert isinstance(query, ast.SelectQuery) and query.ctes is not None
        spend = query.ctes["spend"].expr
        assert isinstance(spend, ast.SelectQuery) and spend.select_from and spend.select_from.next_join
        report = spend.select_from.next_join.table
        assert isinstance(report, ast.SelectQuery) and report.select_from
        report.select_from.table_schema = _SPEND_REPORTS
        return query

    def _sources(self) -> list[InboxUsageSource]:
        if not self.settled.exclude(kind=SignalSpend.Kind.SCOUT_RUN).exists():
            return []
        context = _signals_query_context(self.team)
        with tags_context(product=Product.SIGNALS, feature=Feature.QUERY):
            response = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                context=context,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                ch_user=ClickHouseUser.SIGNALS,
                workload=self.workload,
                query_type="InboxUsageQuery",
            )
        if response.hasMore or len(response.results or []) > 10000:
            raise QueryError("Too many source groups for a usage summary. Use SQL to query a narrower set of sources.")
        return [
            InboxUsageSource(
                source_product=product,
                source_type=source_type,
                processing_credits=str(processing),
                research_credits=str(research),
                implementation_credits=str(implementation),
                total_credits=str(total),
                exempt_credits=str(exempt),
                incomplete=bool(incomplete),
            )
            for product, source_type, processing, research, implementation, total, exempt, incomplete in response.results
            or []
        ]

    def _calculate(self) -> InboxUsageQueryResponse:
        sources = self._sources()
        scouts = _scout_usage(self.team.id, self.settled)
        pending = self.receipts.filter(
            finalized_at__isnull=True,
            created_at__gte=self.period_start,
            created_at__lt=min(self.period_end, self.as_of),
        ).aggregate(credits=Sum("spend", default=0), count=Count("id"))
        untracked_runs = (
            SignalScoutRun.objects.for_team(self.team.id)
            .filter(created_at__gte=self.period_start, created_at__lt=min(self.period_end, self.as_of))
            .exclude(metadata__has_key="scout_trial")
            .exclude(id__in=self.receipts.filter(kind=SignalSpend.Kind.SCOUT_RUN).values("scout_run_id"))
            .count()
        )
        buckets: list[InboxUsageSource | InboxUsageScout] = [*sources, *scouts]
        return InboxUsageQueryResponse(
            results=InboxUsage(
                project_id=self.team.id,
                period_start=self.period_start,
                period_end=self.period_end,
                as_of=self.as_of,
                total_credits=str(sum((Decimal(row.total_credits) for row in buckets), Decimal(0))),
                exempt_credits=str(sum((Decimal(row.exempt_credits) for row in buckets), Decimal(0))),
                unsettled_credits=str(pending["credits"]),
                untracked_scout_run_count=untracked_runs,
                incomplete=bool(pending["count"] or untracked_runs or any(row.incomplete for row in buckets)),
                attribution_incomplete=any(row.source_product is None or row.source_type is None for row in sources),
                sources=sources,
                scouts=scouts,
                pricing=InboxUsagePricing(usd_per_credit=str(Decimal(1) / SIGNALS_CREDITS_PER_DOLLAR)),
            ),
            timings=self.timings.to_list(),
        )
