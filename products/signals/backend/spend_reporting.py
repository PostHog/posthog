from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery, _signals_query_context


@frozen
class SpendAmount:
    total_spend: float | None
    incomplete: bool


@frozen
class ScoutSpend:
    skill_name: str
    spend: SpendAmount


@frozen
class SpendOverview:
    period_start: datetime
    period_end: datetime
    scouts: list[ScoutSpend]
    scout_spend: SpendAmount


@frozen
class SourceSpend:
    source_product: str
    source_type: str
    signal_count: int
    spend: SpendAmount


@frozen
class ReportSpend:
    generation: SpendAmount
    implementation: SpendAmount
    shared_scout_runs: SpendAmount


class SpendReporting:
    def __init__(self, team: Team) -> None:
        self.team = team
        self.team_id = self.team.id

    def _amount(self, receipts: QuerySet[SignalSpend]) -> SpendAmount:
        totals = receipts.aggregate(
            total=Sum("spend"),
            incomplete=Count("id", filter=Q(accounting_failed=True) | Q(finalized_at__isnull=True)),
        )
        return SpendAmount(
            total_spend=float(totals["total"]) if totals["total"] is not None else None,
            incomplete=bool(totals["incomplete"]),
        )

    def scouts(self) -> SpendOverview:
        team = self.team.parent_team or self.team
        end = timezone.now()
        start = end - timedelta(days=30)
        runs = (
            SignalScoutRun.objects.for_team(team.id)
            .filter(created_at__gte=start, created_at__lt=end)
            .exclude(metadata__has_key="scout_trial")
        )
        run_counts = dict(runs.values("skill_name").annotate(count=Count("id")).values_list("skill_name", "count"))
        receipts = SignalSpend.objects.for_team(team.id).filter(
            kind=SignalSpend.Kind.SCOUT_RUN, scout_run_id__in=runs.values("id")
        )
        by_skill = {
            row["scout_run__skill_name"]: SpendAmount(
                total_spend=float(row["total"]),
                incomplete=bool(row["incomplete"]) or row["tracked"] < run_counts[row["scout_run__skill_name"]],
            )
            for row in receipts.values("scout_run__skill_name").annotate(
                total=Sum("spend"),
                tracked=Count("scout_run_id", distinct=True),
                incomplete=Count("id", filter=Q(accounting_failed=True) | Q(finalized_at__isnull=True)),
            )
        }
        scouts = [
            ScoutSpend(skill_name=name, spend=by_skill.get(name, SpendAmount(total_spend=None, incomplete=False)))
            for name in sorted(run_counts)
        ]
        total = self._amount(receipts)
        return SpendOverview(
            period_start=start,
            period_end=end,
            scouts=scouts,
            scout_spend=SpendAmount(
                total_spend=total.total_spend if run_counts else 0,
                incomplete=total.incomplete
                or any(scout.spend.incomplete or scout.spend.total_spend is None for scout in scouts),
            ),
        )

    def sources(self) -> list[SourceSpend]:
        tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
        # Signal timestamps do not change when spend metadata is republished, so this bounds all
        # versions of a signal without losing its latest receipt or counting it more than once.
        query = f"""
            SELECT
                JSONExtractString(metadata, 'source_product') AS source_product,
                JSONExtractString(metadata, 'source_type') AS source_type,
                count() AS signal_count,
                countIf(isNotNull(toFloat64OrNull(JSONExtractRaw(metadata, 'total_spend')))) AS tracked_count,
                sum(toFloat64OrNull(JSONExtractRaw(metadata, 'total_spend'))) AS total_spend,
                countIf(length(JSONExtractArrayRaw(metadata, 'spend_accounting_failed_stages')) > 0) AS failed_count
            FROM ({_deduped_signals_subquery(include_content=False, extra_where="timestamp >= {period_start} AND timestamp < {period_end} AND rendering = 'plain'")})
            GROUP BY source_product, source_type
            ORDER BY total_spend DESC, source_product, source_type
        """
        end = timezone.now()
        response = execute_hogql_query(
            query=query,
            team=self.team,
            context=_signals_query_context(self.team),
            ch_user=ClickHouseUser.SIGNALS,
            workload=Workload.ONLINE,
            query_type="SignalsSourceSpend",
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "period_start": ast.Constant(value=end - timedelta(days=30)),
                "period_end": ast.Constant(value=end),
            },
        )
        return [
            SourceSpend(
                source_product=product,
                source_type=source_type,
                signal_count=count,
                spend=SpendAmount(
                    total_spend=float(total) if tracked else None, incomplete=tracked < count or failed > 0
                ),
            )
            for product, source_type, count, tracked, total, failed in response.results or []
        ]

    def report(self, report: SignalReport) -> ReportSpend:
        tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
        query = f"""
            SELECT groupArray(document_id)
            FROM ({_deduped_signals_subquery(include_content=False, candidate_document_filter="JSONExtractString(metadata, 'report_id') = {report_id}")})
            WHERE JSONExtractString(metadata, 'report_id') = {{report_id}}
        """
        response = execute_hogql_query(
            query=query,
            team=self.team,
            context=_signals_query_context(self.team),
            ch_user=ClickHouseUser.SIGNALS,
            workload=Workload.ONLINE,
            query_type="SignalsReportSpend",
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "report_id": ast.Constant(value=str(report.id)),
            },
        )
        signal_ids = {UUID(signal_id) for row in response.results or [] for signal_id in row[0]}
        if report.triggering_signal_id:
            signal_ids.add(report.triggering_signal_id)
        if report.pending_triggering_signal_id:
            signal_ids.add(report.pending_triggering_signal_id)
        receipts = SignalSpend.objects.for_team(self.team_id).filter(kind__isnull=False)
        shared_runs = (
            SignalScoutRun.objects.for_team(self.team_id)
            .filter(emitted_report_ids__contains=[str(report.id)])
            .exclude(metadata__has_key="scout_trial")
        )
        return ReportSpend(
            generation=self._amount(receipts.filter(signal_id__in=signal_ids)),
            implementation=self._amount(receipts.filter(report_id=report.id)),
            shared_scout_runs=self._amount(receipts.filter(scout_run_id__in=shared_runs.values("id"))),
        )
