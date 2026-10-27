from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from functools import cached_property
from uuid import UUID

from posthog.hogql.database.database import Database

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.api import (
    IncrementalConfig,
    MissingDagNodeError,
    SavedQueryFrequencyBounds,
    definition_database,
    get_saved_query_columns,
    propose_incremental_config,
    saved_query_target_bounds,
    upstream_table_refs,
)
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition

from ...facade.contracts import MaterializePayload, SourceRef
from ...facade.enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshIntervalBasis,
    WarehouseSuggestionRefreshMode,
    WarehouseSuggestionSubjectKind,
)
from ..reads import Subject, SubjectReads
from .base import (
    DAYS_PER_MONTH,
    MILLISECONDS_PER_SECOND,
    Candidate,
    CandidateContext,
    CandidateResult,
    QueryCost,
    RealizedSavings,
    Rejection,
    monthly_cost,
    savings_between,
    stored_cost,
)

SECONDS_PER_MONTH = DAYS_PER_MONTH * 24 * 60 * 60
READ_SECONDS_PER_MONTH = "read_seconds_per_month"
READ_BYTES_PER_MONTH = "read_bytes_per_month"
HUMAN_READS_PER_MONTH = "human_reads_per_month"


@frozen
class SavingsEstimate:
    interval: timedelta
    read_seconds: float
    read_bytes: float
    seconds_saved: float
    bytes_saved: float
    clears_a_floor: bool
    score: float


@frozen
class ClassifiedSources:
    live: tuple[SourceRef, ...]
    unknown: tuple[SourceRef, ...]


@frozen
class _Proposal:
    payload: MaterializePayload
    estimate: SavingsEstimate


class _IncrementalProposer:
    """Proposes incremental keys for one team run, building the team database at most once."""

    def __init__(self, team_id: int) -> None:
        self._team_id = team_id

    @cached_property
    def _database(self) -> Database | None:
        try:
            return definition_database(self._team_id)
        except Exception as error:
            capture_exception(error)
            return None

    def config_for(self, saved_query: SavedQueryDefinition) -> IncrementalConfig | None:
        if self._database is None:
            return None
        column_types = get_saved_query_columns(self._team_id, saved_query.id)
        return propose_incremental_config(saved_query.hogql, column_types, database=self._database)


class MaterializeCandidate(Candidate):
    kind = WarehouseSuggestionKind.MATERIALIZE

    def evaluate(self, context: CandidateContext) -> CandidateResult:
        drafts = []
        rejections = []
        incremental = _IncrementalProposer(context.team_id)
        for saved_query in context.inventory.saved_queries.values():
            subject = Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
            reads = context.reads.reads_of(subject)
            if reads is None or reads.human_requests == 0 or not self._is_unmaterialized(context, saved_query):
                continue
            outcome = self._propose(context, saved_query, reads, incremental)
            if isinstance(outcome, str):
                rejections.append(Rejection(subject=subject, reason=outcome))
                continue
            drafts.append(
                self.draft(
                    context,
                    subject,
                    outcome.payload,
                    score=outcome.estimate.score,
                    score_inputs={
                        "seconds_saved_per_month": outcome.estimate.seconds_saved,
                        "bytes_saved_per_month": outcome.estimate.bytes_saved,
                        READ_SECONDS_PER_MONTH: outcome.estimate.read_seconds,
                        READ_BYTES_PER_MONTH: outcome.estimate.read_bytes,
                        HUMAN_READS_PER_MONTH: reads.human_reads * context.month_scale,
                        "refresh_interval_seconds": outcome.estimate.interval.total_seconds(),
                    },
                )
            )
        return CandidateResult(drafts=tuple(drafts), rejections=tuple(rejections))

    def asset_outcome(
        self, context: CandidateContext, subject: Subject, accepted_at: datetime | None
    ) -> WarehouseSuggestionAssetOutcome:
        saved_query = context.inventory.saved_queries.get(subject.id)
        if saved_query is None or not saved_query.materializes:
            return WarehouseSuggestionAssetOutcome.DELETED
        reads = context.reads.reads_of(subject)
        if reads is not None and (accepted_at is None or reads.last_read_at > accepted_at):
            return WarehouseSuggestionAssetOutcome.LIVE
        return WarehouseSuggestionAssetOutcome.UNUSED

    def realized_savings(
        self, context: CandidateContext, subject: Subject, score_inputs: Mapping[str, float]
    ) -> RealizedSavings | None:
        saved_query = context.inventory.saved_queries.get(subject.id)
        refreshes = context.reads.refreshes.get(subject.id)
        if saved_query is None or not saved_query.materializes or refreshes is None or refreshes.runs == 0:
            return None
        reads = context.reads.reads_of(subject)
        reads_per_month = (reads.human_reads if reads else 0) * context.month_scale
        cost_without = _read_cost_before_at(score_inputs, reads_per_month)
        if cost_without is None:
            return None
        cost_now = monthly_cost(
            context,
            duration_ms=(reads.human_duration_ms if reads else 0) + refreshes.duration_ms,
            read_bytes=(reads.human_read_bytes if reads else 0) + refreshes.read_bytes,
        )
        return savings_between(cost_without, cost_now)

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or saved_query.materializes

    def _is_unmaterialized(self, context: CandidateContext, saved_query: SavedQueryDefinition) -> bool:
        return not saved_query.materializes and context.is_suggestible_view(saved_query)

    def _propose(
        self,
        context: CandidateContext,
        saved_query: SavedQueryDefinition,
        reads: SubjectReads,
        incremental: _IncrementalProposer,
    ) -> _Proposal | str:
        if context.accepted_recently(WarehouseSuggestionKind.UNMATERIALIZE, saved_query.id):
            return f"was unmaterialized on a suggestion in the last {context.rules.lifecycle.flip_cooldown_days} days"
        rejection = self._read_floor_rejection(context, reads)
        if rejection is not None:
            return rejection
        frequency = saved_query_target_bounds(context.team_id, saved_query.id)
        if frequency is None:
            capture_exception(MissingDagNodeError(f"Saved query {saved_query.id} has no DAG node"))
            return "it has no node in a DAG"
        intervals = allowed_intervals(context, frequency.bounds.allowed, reads)
        if not intervals:
            return f"its sources allow no refresh interval up to {context.rules.refresh.max_interval}"
        refresh = refresh_cost(context, saved_query.id, reads)
        estimate = next(
            (
                estimate
                for estimate in (estimate_savings(context, reads, interval, refresh) for interval in intervals)
                if estimate.clears_a_floor
            ),
            None,
        )
        if estimate is None:
            return "savings stay under the floors at every allowed refresh interval"
        sources = _classify_sources(context, saved_query.id, frequency)
        freshness_today = int(frequency.max_data_age.total_seconds()) or None
        interval_seconds = int(estimate.interval.total_seconds())
        payload = MaterializePayload(
            subject_name=saved_query.name,
            refresh_interval_seconds=interval_seconds,
            saves_seconds_per_month=estimate.seconds_saved,
            saves_bytes_per_month=estimate.bytes_saved,
            freshness_today_seconds=freshness_today,
            freshness_after_seconds=interval_seconds + (freshness_today or 0),
            live_sources=sources.live,
            unknown_sources=sources.unknown,
            refresh_interval_basis=interval_basis(
                estimate.interval,
                frequency.bounds.allowed,
                intervals,
                limited_by_sources=frequency.bounds.floor is not None,
            ),
        )
        return _Proposal(
            payload=_with_refresh_mode(
                payload, incremental.config_for(saved_query), context.rules.materialize.incremental_lookback_seconds
            ),
            estimate=estimate,
        )

    def _read_floor_rejection(self, context: CandidateContext, reads: SubjectReads) -> str | None:
        rules = context.rules.materialize
        min_days = context.scaled_floor(rules.min_days)
        min_requests = context.scaled_floor(rules.min_requests)
        if reads.human_days < min_days:
            return f"read on {reads.human_days} days, needs {min_days}"
        if reads.human_requests < min_requests:
            return f"read {reads.human_requests} times, needs {min_requests}"
        if max(reads.human_users, len(reads.surfaces)) < rules.min_users_or_surfaces:
            return f"read by too few people or surfaces, needs {rules.min_users_or_surfaces}"
        if reads.alone_reads < rules.min_alone_reads:
            return f"read on its own {reads.alone_reads} times, needs {rules.min_alone_reads} to know its cost"
        return None


def allowed_intervals(context: CandidateContext, allowed: Iterable[timedelta], reads: SubjectReads) -> list[timedelta]:
    refresh = context.rules.refresh
    intervals = sorted(interval for interval in allowed if interval <= refresh.max_interval)
    read_day_share = reads.human_days / context.days_observed
    if read_day_share < refresh.min_read_day_share_below_max_interval:
        return [interval for interval in intervals if interval >= refresh.max_interval]
    return [interval for interval in intervals if interval >= read_interval(reads)]


def read_interval(reads: SubjectReads) -> timedelta:
    return timedelta(days=reads.human_days) / max(reads.human_requests, 1)


def interval_basis(
    interval: timedelta, allowed: Iterable[timedelta], read_allowed: list[timedelta], *, limited_by_sources: bool
) -> WarehouseSuggestionRefreshIntervalBasis:
    if interval == min(allowed):
        if limited_by_sources:
            return WarehouseSuggestionRefreshIntervalBasis.SOURCE_SYNC
        return WarehouseSuggestionRefreshIntervalBasis.FASTEST_SCHEDULE
    if interval == read_allowed[0]:
        return WarehouseSuggestionRefreshIntervalBasis.READ_RATE
    return WarehouseSuggestionRefreshIntervalBasis.SAVINGS


def _with_refresh_mode(
    payload: MaterializePayload, config: IncrementalConfig | None, lookback_seconds: int
) -> MaterializePayload:
    if config is None:
        return payload
    return replace(
        payload,
        refresh_mode=WarehouseSuggestionRefreshMode.INCREMENTAL,
        incremental_key=config.incremental_key,
        unique_key=config.unique_key,
        lookback_seconds=lookback_seconds,
    )


def refresh_cost(context: CandidateContext, saved_query_id: UUID, reads: SubjectReads) -> QueryCost:
    refreshes = context.reads.refreshes.get(saved_query_id)
    if refreshes is not None and refreshes.runs > 0:
        return QueryCost(
            seconds=refreshes.duration_ms / MILLISECONDS_PER_SECOND / refreshes.runs,
            read_bytes=refreshes.read_bytes / refreshes.runs,
        )
    return QueryCost(
        seconds=reads.alone_duration_ms_p90 / MILLISECONDS_PER_SECOND, read_bytes=reads.alone_read_bytes_p90
    )


def estimate_savings(
    context: CandidateContext, reads: SubjectReads, interval: timedelta, refresh: QueryCost
) -> SavingsEstimate:
    rules = context.rules.materialize
    scale = context.month_scale
    refreshes_per_month = SECONDS_PER_MONTH / interval.total_seconds()
    body_seconds = reads.alone_duration_ms_median / MILLISECONDS_PER_SECOND
    read_seconds = reads.human_duration_ms / MILLISECONDS_PER_SECOND * scale
    read_bytes = reads.human_read_bytes * scale
    seconds_saved = min(read_seconds, reads.human_reads * body_seconds * scale) - refreshes_per_month * refresh.seconds
    bytes_saved = (
        min(read_bytes, reads.human_reads * reads.alone_read_bytes_median * scale)
        - refreshes_per_month * refresh.read_bytes
    )
    clears_time = seconds_saved >= rules.min_seconds_saved and seconds_saved >= rules.min_saved_share * read_seconds
    clears_bytes = bytes_saved >= rules.min_bytes_saved and bytes_saved >= rules.min_saved_share * read_bytes
    return SavingsEstimate(
        interval=interval,
        read_seconds=read_seconds,
        read_bytes=read_bytes,
        seconds_saved=seconds_saved,
        bytes_saved=bytes_saved,
        clears_a_floor=clears_time or clears_bytes,
        score=max(seconds_saved / rules.min_seconds_saved, bytes_saved / rules.min_bytes_saved),
    )


def _read_cost_before_at(score_inputs: Mapping[str, float], reads_per_month: float) -> QueryCost | None:
    cost_before = stored_cost(score_inputs, READ_SECONDS_PER_MONTH, READ_BYTES_PER_MONTH)
    reads_before = score_inputs.get(HUMAN_READS_PER_MONTH)
    if cost_before is None or not reads_before:
        return None
    volume = reads_per_month / reads_before
    return QueryCost(seconds=cost_before.seconds * volume, read_bytes=cost_before.read_bytes * volume)


def _classify_sources(
    context: CandidateContext, saved_query_id: UUID, frequency: SavedQueryFrequencyBounds
) -> ClassifiedSources:
    best_effort_table_ids = {
        identity.warehouse_table_id
        for node_id in frequency.best_effort_source_ids
        if (identity := frequency.identities.get(node_id)) is not None and identity.warehouse_table_id is not None
    }
    live = []
    unknown = []
    for ref in sorted(upstream_table_refs(context.team_id, saved_query_id), key=lambda ref: ref.name):
        table_id = UUID(ref.warehouse_table_id) if ref.warehouse_table_id else None
        if table_id is None and not ref.is_posthog_table:
            continue
        source = SourceRef(name=ref.name, warehouse_table_id=table_id)
        if table_id is None or table_id in context.inventory.direct_table_ids:
            live.append(source)
        elif ref.warehouse_table_id in best_effort_table_ids:
            unknown.append(source)
    return ClassifiedSources(live=tuple(live), unknown=tuple(unknown))
