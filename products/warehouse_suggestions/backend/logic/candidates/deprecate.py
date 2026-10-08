from uuid import UUID

from products.data_modeling.backend.facade.api import dependent_saved_query_ids, upstream_table_refs
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition

from ...facade.contracts import DeprecatePayload
from ...facade.enums import WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from ..reads import Subject
from .base import MILLISECONDS_PER_SECOND, Candidate, CandidateContext, CandidateResult, Rejection


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
            and not _is_read(context, _subject(saved_query))
        ]
        dependents = dependent_saved_query_ids(context.team_id, [saved_query.id for saved_query in unread])
        drafts = []
        rejections = []
        for saved_query in unread:
            subject = _subject(saved_query)
            reason = self._rejection(context, saved_query, has_dependents=bool(dependents.get(saved_query.id)))
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

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is None or not saved_query.materializes or _is_read(context, subject)

    def _rejection(
        self, context: CandidateContext, saved_query: SavedQueryDefinition, *, has_dependents: bool
    ) -> str | None:
        if saved_query.created_at > context.reads.window.starts_at:
            return "created after the read window started"
        if has_dependents:
            return "other views read from it"
        if self._reads_direct_source(context, saved_query.id):
            return "reads a direct-connection source, whose reads are not logged"
        return None

    def _reads_direct_source(self, context: CandidateContext, saved_query_id: UUID) -> bool:
        return any(
            ref.warehouse_table_id is not None and UUID(ref.warehouse_table_id) in context.inventory.direct_table_ids
            for ref in upstream_table_refs(context.team_id, saved_query_id)
        )


def _is_read(context: CandidateContext, subject: Subject) -> bool:
    reads = context.reads.reads_of(subject)
    if reads is None:
        return False
    return context.rules.deprecate.counts_background_reads or reads.human_requests > 0


def _subject(saved_query: SavedQueryDefinition) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=saved_query.id)
