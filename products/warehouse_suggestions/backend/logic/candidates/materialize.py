from collections.abc import Iterable
from datetime import timedelta
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.api import (
    MissingDagNodeError,
    SavedQueryFrequencyBounds,
    check_incremental_eligibility,
    saved_query_target_bounds,
    upstream_table_refs,
)
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition

from ...facade.contracts import MaterializePayload, SourceRef
from ...facade.enums import WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from ..reads import Subject, SubjectReads
from .base import DAYS_PER_MONTH, MILLISECONDS_PER_SECOND, Candidate, CandidateContext, CandidateResult, Rejection

SECONDS_PER_MONTH = DAYS_PER_MONTH * 24 * 60 * 60


@frozen
class SavingsEstimate:
    interval: timedelta
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


class MaterializeCandidate(Candidate):
    kind = WarehouseSuggestionKind.MATERIALIZE

    def evaluate(self, context: CandidateContext) -> CandidateResult:
        drafts = []
        rejections = []
        for saved_query in context.inventory.saved_queries.values():
            subject = Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
            reads = context.reads.reads_of(subject)
            if reads is None or reads.human_requests == 0 or not self._is_unmaterialized(context, saved_query):
                continue
            outcome = self._propose(context, saved_query, reads)
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
                        "refresh_interval_seconds": outcome.estimate.interval.total_seconds(),
                    },
                )
            )
        return CandidateResult(drafts=tuple(drafts), rejections=tuple(rejections))

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or saved_query.materializes

    def _is_unmaterialized(self, context: CandidateContext, saved_query: SavedQueryDefinition) -> bool:
        return not saved_query.materializes and context.is_suggestible_view(saved_query)

    def _propose(
        self, context: CandidateContext, saved_query: SavedQueryDefinition, reads: SubjectReads
    ) -> _Proposal | str:
        rejection = self._read_floor_rejection(context, reads)
        if rejection is not None:
            return rejection
        if (
            context.rules.materialize.require_incremental_eligibility
            and not check_incremental_eligibility(saved_query.hogql, None).eligible
        ):
            return "its query cannot refresh incrementally"
        frequency = saved_query_target_bounds(context.team_id, saved_query.id)
        if frequency is None:
            capture_exception(MissingDagNodeError(f"Saved query {saved_query.id} has no DAG node"))
            return "it has no node in a DAG"
        intervals = allowed_intervals(context, frequency.bounds.allowed, reads)
        if not intervals:
            return f"its sources allow no refresh interval up to {context.rules.refresh.max_interval}"
        estimate = next(
            (
                estimate
                for estimate in (estimate_savings(context, reads, interval) for interval in intervals)
                if estimate.clears_a_floor
            ),
            None,
        )
        if estimate is None:
            return "savings stay under the floors at every allowed refresh interval"
        sources = _classify_sources(context, saved_query.id, frequency)
        freshness_today = int(frequency.max_data_age.total_seconds()) or None
        interval_seconds = int(estimate.interval.total_seconds())
        return _Proposal(
            payload=MaterializePayload(
                subject_name=saved_query.name,
                refresh_interval_seconds=interval_seconds,
                saves_seconds_per_month=estimate.seconds_saved,
                saves_bytes_per_month=estimate.bytes_saved,
                freshness_today_seconds=freshness_today,
                freshness_after_seconds=interval_seconds + (freshness_today or 0),
                live_sources=sources.live,
                unknown_sources=sources.unknown,
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
    return intervals


def estimate_savings(context: CandidateContext, reads: SubjectReads, interval: timedelta) -> SavingsEstimate:
    rules = context.rules.materialize
    scale = context.month_scale
    refreshes_per_month = SECONDS_PER_MONTH / interval.total_seconds()
    body_seconds = reads.alone_duration_ms_median / MILLISECONDS_PER_SECOND
    read_seconds = reads.human_duration_ms / MILLISECONDS_PER_SECOND * scale
    read_bytes = reads.human_read_bytes * scale
    seconds_saved = min(read_seconds, reads.human_reads * body_seconds * scale) - refreshes_per_month * body_seconds
    bytes_saved = (
        min(read_bytes, reads.human_reads * reads.alone_read_bytes_median * scale)
        - refreshes_per_month * reads.alone_read_bytes_median
    )
    clears_time = seconds_saved >= rules.min_seconds_saved and seconds_saved >= rules.min_saved_share * read_seconds
    clears_bytes = bytes_saved >= rules.min_bytes_saved and bytes_saved >= rules.min_saved_share * read_bytes
    return SavingsEstimate(
        interval=interval,
        seconds_saved=seconds_saved,
        bytes_saved=bytes_saved,
        clears_a_floor=clears_time or clears_bytes,
        score=max(seconds_saved / rules.min_seconds_saved, bytes_saved / rules.min_bytes_saved),
    )


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
        source = SourceRef(name=ref.name, warehouse_table_id=table_id)
        if table_id is None or table_id in context.inventory.direct_table_ids:
            live.append(source)
        elif ref.warehouse_table_id in best_effort_table_ids:
            unknown.append(source)
    return ClassifiedSources(live=tuple(live), unknown=tuple(unknown))
