import hashlib
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import dependent_saved_query_ids
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition
from products.warehouse_sources.backend.facade.api import saved_queries_feeding_consumers

from ...facade.contracts import DematerializePayload
from ...facade.enums import WarehouseSuggestionAssetOutcome, WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from ..reads import Subject, SubjectReads, SubjectRefreshes
from .base import (
    DEPENDENTS_REJECTION,
    DIRECT_SOURCE_REJECTION,
    FEEDS_CONSUMERS_REJECTION,
    MILLISECONDS_PER_SECOND,
    Candidate,
    CandidateContext,
    CandidateResult,
    Rejection,
)

INCREMENTAL_REJECTION = "refreshes incrementally, so one refresh does not show what a full read costs"
CALLS_MODELS_REJECTION = "calls a model per row, which would run on every read"


@frozen
class _Proposal:
    saved_query: SavedQueryDefinition
    payload: DematerializePayload
    score: float


class DematerializeCandidate(Candidate):
    kind = WarehouseSuggestionKind.DEMATERIALIZE

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
                        "refresh_seconds_per_month": proposal.payload.refresh_seconds_per_month,
                        "live_seconds_per_month": proposal.payload.live_seconds_per_month,
                        "refresh_bytes_per_month": proposal.payload.refresh_bytes_per_month,
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

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or not saved_query.materializes

    def _propose(
        self, context: CandidateContext, saved_query: SavedQueryDefinition, reads: SubjectReads
    ) -> _Proposal | str:
        rules = context.rules.dematerialize
        refreshes = context.reads.refreshes.get(saved_query.id)
        runs = refreshes.runs if refreshes else 0
        if refreshes is None or runs < rules.min_runs:
            return f"refreshed {runs} times, needs {rules.min_runs} to know its cost"
        if saved_query.refreshes_incrementally:
            return INCREMENTAL_REJECTION
        if saved_query.calls_models:
            return CALLS_MODELS_REJECTION
        if context.accepted_recently(WarehouseSuggestionKind.MATERIALIZE, saved_query.id):
            return f"was materialized on a suggestion in the last {context.rules.lifecycle.flip_cooldown_days} days"
        payload = _payload(context, saved_query, reads, refreshes)
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
    return None


def _payload(
    context: CandidateContext, saved_query: SavedQueryDefinition, reads: SubjectReads, refreshes: SubjectRefreshes
) -> DematerializePayload:
    scale = context.month_scale
    reads_per_month = (reads.human_reads + reads.background_reads) * scale
    seconds_per_run = refreshes.duration_ms / MILLISECONDS_PER_SECOND / refreshes.runs
    bytes_per_run = refreshes.read_bytes / refreshes.runs
    return DematerializePayload(
        subject_name=saved_query.name,
        refresh_seconds_per_month=refreshes.duration_ms / MILLISECONDS_PER_SECOND * scale,
        refresh_bytes_per_month=refreshes.read_bytes * scale,
        live_seconds_per_month=reads_per_month * seconds_per_run,
        live_bytes_per_month=reads_per_month * bytes_per_run,
        read_seconds=refreshes.p90_duration_ms / MILLISECONDS_PER_SECOND,
        query_fingerprint=query_fingerprint(saved_query.hogql),
    )


def query_fingerprint(hogql: str) -> str:
    return hashlib.sha256(hogql.encode()).hexdigest()


def _subject(saved_query: SavedQueryDefinition) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
