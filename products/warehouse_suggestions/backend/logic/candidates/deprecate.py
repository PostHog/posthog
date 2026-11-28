from collections.abc import Mapping
from datetime import datetime

from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.api import dependent_saved_query_ids
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition
from products.warehouse_sources.backend.facade.api import saved_queries_feeding_consumers

from ...facade.contracts import DeprecatePayload
from ...facade.enums import WarehouseSuggestionAssetOutcome, WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from ..reads import Subject
from .base import (
    DEPENDENTS_REJECTION,
    DIRECT_SOURCE_REJECTION,
    FEEDS_CONSUMERS_REJECTION,
    MILLISECONDS_PER_SECOND,
    REFRESH_BYTES_PER_MONTH,
    REFRESH_SECONDS_PER_MONTH,
    Candidate,
    CandidateContext,
    CandidateResult,
    RealizedSavings,
    Rejection,
    certification_outcome,
    stored_cost,
)


class DeprecateCandidate(Candidate):
    kind = WarehouseSuggestionKind.DEPRECATE
    realized_savings_wait_for_read_window = False

    def evaluate(self, context: CandidateContext) -> CandidateResult:
        rules = context.rules.deprecate
        if context.reads.days_with_data < context.rules.window_days:
            return CandidateResult(
                drafts=(),
                rejections=(),
                skipped_reason=(
                    f"needs {context.rules.window_days} days of read data, has {context.reads.days_with_data}"
                ),
            )
        unread = [
            saved_query
            for saved_query in context.inventory.saved_queries.values()
            if context.is_suggestible_view(saved_query)
            and not context.is_read(_subject(saved_query))
            and not _is_done(context, saved_query)
        ]
        unread_ids = [saved_query.id for saved_query in unread]
        dependents = dependent_saved_query_ids(context.team_id, unread_ids)
        feeding_consumers = saved_queries_feeding_consumers(context.team_id, unread_ids)
        drafts = []
        rejections = []
        for saved_query in unread:
            subject = _subject(saved_query)
            reason = self._rejection(
                context,
                saved_query,
                has_dependents=bool(dependents.get(saved_query.id)),
                feeds_consumers=saved_query.id in feeding_consumers,
            )
            if reason is not None:
                rejections.append(Rejection(subject=subject, reason=reason))
                continue
            refreshes = context.reads.refreshes.get(saved_query.id) if saved_query.materializes else None
            seconds = refreshes.duration_ms / MILLISECONDS_PER_SECOND * context.month_scale if refreshes else 0.0
            read_bytes = refreshes.read_bytes * context.month_scale if refreshes else 0.0
            drafts.append(
                self.draft(
                    context,
                    subject,
                    DeprecatePayload(
                        subject_name=saved_query.name,
                        refresh_seconds_per_month=seconds,
                        refresh_bytes_per_month=read_bytes,
                        materialized=saved_query.materializes,
                    ),
                    score=max(seconds / rules.seconds_floor, read_bytes / rules.bytes_floor),
                    score_inputs={REFRESH_SECONDS_PER_MONTH: seconds, REFRESH_BYTES_PER_MONTH: read_bytes},
                )
            )
        return CandidateResult(drafts=tuple(drafts), rejections=tuple(rejections))

    def asset_outcome(
        self, context: CandidateContext, subject: Subject, accepted_at: datetime | None
    ) -> WarehouseSuggestionAssetOutcome:
        if subject.id not in context.inventory.saved_queries:
            return WarehouseSuggestionAssetOutcome.LIVE
        return certification_outcome(context, subject, CertificationStatus.DEPRECATED)

    def realized_savings(
        self, context: CandidateContext, subject: Subject, score_inputs: Mapping[str, float]
    ) -> RealizedSavings | None:
        saved_query = context.inventory.saved_queries.get(subject.id)
        if saved_query is not None and saved_query.materializes:
            return None
        refresh_cost = stored_cost(score_inputs, REFRESH_SECONDS_PER_MONTH, REFRESH_BYTES_PER_MONTH)
        if refresh_cost is None:
            return None
        return RealizedSavings(seconds=refresh_cost.seconds, read_bytes=refresh_cost.read_bytes)

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or context.is_read(subject) or _is_done(context, saved_query)

    def _rejection(
        self,
        context: CandidateContext,
        saved_query: SavedQueryDefinition,
        *,
        has_dependents: bool,
        feeds_consumers: bool,
    ) -> str | None:
        if saved_query.created_at > context.reads.window.starts_at:
            return "created after the read window started"
        if has_dependents:
            return DEPENDENTS_REJECTION
        if feeds_consumers:
            return FEEDS_CONSUMERS_REJECTION
        if context.reads_direct_source(saved_query.id):
            return DIRECT_SOURCE_REJECTION
        return None


def _is_done(context: CandidateContext, saved_query: SavedQueryDefinition) -> bool:
    is_deprecated = context.inventory.certifications.get(_subject(saved_query)) == CertificationStatus.DEPRECATED
    return is_deprecated and not saved_query.materializes


def _subject(saved_query: SavedQueryDefinition) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
