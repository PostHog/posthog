import json
import math
import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from statistics import mean
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import (
    completed_full_refresh_workflow_ids,
    dependent_saved_query_ids,
    last_query_change_at,
    saved_query_definitions,
    upstream_saved_query_ids,
)
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition
from products.warehouse_sources.backend.facade.api import saved_queries_feeding_consumers

from ...facade.contracts import UnmaterializePayload
from ...facade.enums import WarehouseSuggestionAssetOutcome, WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from ..reads import RefreshRun, Subject, SubjectReads
from .base import (
    DEPENDENTS_REJECTION,
    DIRECT_SOURCE_REJECTION,
    FEEDS_CONSUMERS_REJECTION,
    MILLISECONDS_PER_SECOND,
    READER_ACCESS_REJECTION,
    Candidate,
    CandidateContext,
    CandidateResult,
    QueryCost,
    RealizedSavings,
    Rejection,
    inlining_could_deny_a_reader,
    monthly_cost,
    savings_between,
    stored_cost,
)

INCREMENTAL_REJECTION = "refreshes incrementally, so one refresh does not show what a full read costs"
CALLS_DECISION_FUNCTIONS_REJECTION = "calls jev() or decide(), which would run a model on every read"
READ_TIME_QUANTILE = 0.9
REFRESH_SECONDS_PER_MONTH = "refresh_seconds_per_month"
REFRESH_BYTES_PER_MONTH = "refresh_bytes_per_month"


@frozen
class EffectiveDefinition:
    fingerprint: str
    changed_at: datetime | None


@frozen
class _Proposal:
    saved_query: SavedQueryDefinition
    payload: UnmaterializePayload
    score: float


class UnmaterializeCandidate(Candidate):
    kind = WarehouseSuggestionKind.UNMATERIALIZE

    def evaluate(self, context: CandidateContext) -> CandidateResult:
        proposals: list[_Proposal] = []
        rejections: list[Rejection] = []
        for saved_query in context.inventory.saved_queries.values():
            if not saved_query.materializes or not context.is_suggestible_view(saved_query):
                continue
            subject = _subject(saved_query)
            reads = context.reads.reads_of(subject)
            if reads is None or not context.is_read(subject):
                continue
            outcome = self._propose(context, saved_query, reads)
            if isinstance(outcome, str):
                rejections.append(Rejection(subject=subject, reason=outcome))
            else:
                proposals.append(outcome)
        drafts = []
        for proposal, reason in self._with_graph_rejections(context, proposals):
            subject = _subject(proposal.saved_query)
            if reason is not None:
                rejections.append(Rejection(subject=subject, reason=reason))
                continue
            drafts.append(
                self.draft(
                    context,
                    subject,
                    proposal.payload,
                    score=proposal.score,
                    score_inputs={
                        REFRESH_SECONDS_PER_MONTH: proposal.payload.refresh_seconds_per_month,
                        "live_seconds_per_month": proposal.payload.live_seconds_per_month,
                        REFRESH_BYTES_PER_MONTH: proposal.payload.refresh_bytes_per_month,
                        "live_bytes_per_month": proposal.payload.live_bytes_per_month,
                    },
                )
            )
        return CandidateResult(drafts=tuple(drafts), rejections=tuple(rejections))

    def asset_outcome(
        self, context: CandidateContext, subject: Subject, accepted_at: datetime | None
    ) -> WarehouseSuggestionAssetOutcome:
        saved_query = context.inventory.saved_queries.get(subject.id)
        if saved_query is None:
            return WarehouseSuggestionAssetOutcome.DELETED
        if saved_query.materializes:
            return WarehouseSuggestionAssetOutcome.UNUSED
        return WarehouseSuggestionAssetOutcome.LIVE

    def realized_savings(
        self, context: CandidateContext, subject: Subject, score_inputs: Mapping[str, float]
    ) -> RealizedSavings | None:
        saved_query = context.inventory.saved_queries.get(subject.id)
        if saved_query is None or saved_query.materializes:
            return None
        refresh_cost_before = stored_cost(score_inputs, REFRESH_SECONDS_PER_MONTH, REFRESH_BYTES_PER_MONTH)
        if refresh_cost_before is None:
            return None
        return savings_between(refresh_cost_before, _monthly_read_cost(context, subject))

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or not saved_query.materializes

    def _propose(
        self, context: CandidateContext, saved_query: SavedQueryDefinition, reads: SubjectReads
    ) -> _Proposal | str:
        rules = context.rules.unmaterialize
        if saved_query.refreshes_incrementally:
            return INCREMENTAL_REJECTION
        if saved_query.calls_decision_functions:
            return CALLS_DECISION_FUNCTIONS_REJECTION
        if context.accepted_recently(WarehouseSuggestionKind.MATERIALIZE, saved_query.id):
            return f"was materialized on a suggestion in the last {context.rules.lifecycle.flip_cooldown_days} days"
        definition = effective_definition(context.team_id, saved_query)
        runs = context.reads.refresh_runs.get(saved_query.id, ())
        current_runs = _current_definition_runs(context, saved_query.id, definition, runs)
        if len(current_runs) < rules.min_runs:
            return (
                f"has {len(current_runs)} completed full refreshes of its current query, "
                f"needs {rules.min_runs} to know its cost"
            )
        payload = _payload(context, saved_query, reads, runs, current_runs, definition)
        seconds_saved = payload.refresh_seconds_per_month - payload.live_seconds_per_month
        bytes_saved = payload.refresh_bytes_per_month - payload.live_bytes_per_month
        clears_time = (
            seconds_saved >= rules.min_seconds_saved
            and seconds_saved >= rules.min_saved_share * payload.refresh_seconds_per_month
        )
        clears_bytes = (
            bytes_saved >= rules.min_bytes_saved
            and bytes_saved >= rules.min_saved_share * payload.refresh_bytes_per_month
        )
        if not clears_time and not clears_bytes:
            return "computing it on each read would not save enough over refreshing it"
        if payload.read_seconds > rules.max_read_seconds:
            return f"a read could take {payload.read_seconds:.0f} seconds, over {rules.max_read_seconds:.0f}"
        return _Proposal(
            saved_query=saved_query,
            payload=payload,
            score=max(seconds_saved / rules.min_seconds_saved, bytes_saved / rules.min_bytes_saved),
        )

    def _with_graph_rejections(
        self, context: CandidateContext, proposals: list[_Proposal]
    ) -> list[tuple[_Proposal, str | None]]:
        ids = [proposal.saved_query.id for proposal in proposals]
        dependents = dependent_saved_query_ids(context.team_id, ids)
        feeding_consumers = saved_queries_feeding_consumers(context.team_id, ids)
        return [
            (proposal, _graph_rejection(context, proposal.saved_query.id, dependents, feeding_consumers))
            for proposal in proposals
        ]


def _graph_rejection(
    context: CandidateContext,
    saved_query_id: UUID,
    dependents: Mapping[UUID, frozenset[UUID]],
    feeding_consumers: frozenset[UUID],
) -> str | None:
    if dependents.get(saved_query_id):
        return DEPENDENTS_REJECTION
    if saved_query_id in feeding_consumers:
        return FEEDS_CONSUMERS_REJECTION
    if context.reads_direct_source(saved_query_id):
        return DIRECT_SOURCE_REJECTION
    if inlining_could_deny_a_reader(context.team_id, saved_query_id):
        return READER_ACCESS_REJECTION
    return None


def effective_definition(team_id: int, saved_query: SavedQueryDefinition) -> EffectiveDefinition:
    upstream_ids = upstream_saved_query_ids(team_id, saved_query.id)
    upstream_queries = [upstream.hogql for upstream in saved_query_definitions(team_id, ids=upstream_ids)]
    return EffectiveDefinition(
        fingerprint=definition_fingerprint([saved_query.hogql, *upstream_queries]),
        changed_at=last_query_change_at(team_id, {saved_query.id, *upstream_ids}),
    )


def definition_fingerprint(queries: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(queries)).encode()).hexdigest()


def _current_definition_runs(
    context: CandidateContext, saved_query_id: UUID, definition: EffectiveDefinition, runs: Sequence[RefreshRun]
) -> list[RefreshRun]:
    since = context.reads.window.starts_at
    if definition.changed_at is not None:
        since = max(since, definition.changed_at)
    workflow_ids = completed_full_refresh_workflow_ids(context.team_id, saved_query_id, since=since)
    return [run for run in runs if run.workflow_id in workflow_ids]


def _payload(
    context: CandidateContext,
    saved_query: SavedQueryDefinition,
    reads: SubjectReads,
    runs: Sequence[RefreshRun],
    current_runs: Sequence[RefreshRun],
    definition: EffectiveDefinition,
) -> UnmaterializePayload:
    scale = context.month_scale
    reads_per_month = (reads.human_reads + reads.background_reads) * scale
    runs_per_month = len(runs) * scale
    seconds_per_run = mean(run.duration_ms for run in current_runs) / MILLISECONDS_PER_SECOND
    bytes_per_run = mean(run.read_bytes for run in current_runs)
    return UnmaterializePayload(
        subject_name=saved_query.name,
        refresh_seconds_per_month=runs_per_month * seconds_per_run,
        refresh_bytes_per_month=runs_per_month * bytes_per_run,
        live_seconds_per_month=reads_per_month * seconds_per_run,
        live_bytes_per_month=reads_per_month * bytes_per_run,
        read_seconds=_read_time_quantile_ms(current_runs) / MILLISECONDS_PER_SECOND,
        query_fingerprint=definition.fingerprint,
    )


def _read_time_quantile_ms(runs: Sequence[RefreshRun]) -> int:
    durations = sorted(run.duration_ms for run in runs)
    return durations[math.ceil(READ_TIME_QUANTILE * len(durations)) - 1]


def _monthly_read_cost(context: CandidateContext, subject: Subject) -> QueryCost:
    reads = context.reads.reads_of(subject)
    if reads is None:
        return QueryCost(seconds=0.0, read_bytes=0.0)
    return monthly_cost(
        context,
        duration_ms=reads.human_duration_ms + reads.background_duration_ms,
        read_bytes=reads.human_read_bytes + reads.background_read_bytes,
    )


def _subject(saved_query: SavedQueryDefinition) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
