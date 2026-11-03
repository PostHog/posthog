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
    Candidate,
    CandidateContext,
    CandidateResult,
    Rejection,
    certification_outcome,
)


class DeprecateCandidate(Candidate):
    kind = WarehouseSuggestionKind.DEPRECATE

    def evaluate(self, context: CandidateContext) -> CandidateResult:
        rules = context.rules.deprecate
        if context.reads.days_with_data < rules.min_days_with_data:
            return CandidateResult(
                drafts=(),
                rejections=(),
                skipped_reason=(
                    f"needs {rules.min_days_with_data} days of read data, has {context.reads.days_with_data}"
                ),
            )
        unread = [
            saved_query
            for saved_query in context.inventory.saved_queries.values()
            if saved_query.materializes
            and context.is_suggestible_view(saved_query)
            and not context.is_read(_subject(saved_query))
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
            refreshes = context.reads.refreshes.get(saved_query.id)
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
                    ),
                    score=max(seconds / rules.seconds_floor, read_bytes / rules.bytes_floor),
                    score_inputs={"refresh_seconds_per_month": seconds, "refresh_bytes_per_month": read_bytes},
                )
            )
        return CandidateResult(drafts=tuple(drafts), rejections=tuple(rejections))

    def asset_outcome(
        self, context: CandidateContext, subject: Subject, accepted_at: datetime | None
    ) -> WarehouseSuggestionAssetOutcome:
        return certification_outcome(context, subject, CertificationStatus.DEPRECATED)

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or not saved_query.materializes or context.is_read(subject)

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


def _subject(saved_query: SavedQueryDefinition) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
