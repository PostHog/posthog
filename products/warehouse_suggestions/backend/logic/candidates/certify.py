from ...facade.contracts import CertifyPayload
from ...facade.enums import WarehouseSuggestionKind, WarehouseSuggestionSubjectKind
from ..reads import Subject, SubjectReads
from .base import Candidate, CandidateContext, CandidateResult, Rejection


class CertifyCandidate(Candidate):
    kind = WarehouseSuggestionKind.CERTIFY

    def evaluate(self, context: CandidateContext) -> CandidateResult:
        ranked = sorted(
            (
                (subject, reads)
                for subject, reads in context.reads.subjects.items()
                if reads.human_requests > 0 and self._is_certifiable(context, subject)
            ),
            key=lambda item: (_traffic(item[1]), str(item[0].id)),
            reverse=True,
        )
        top_count = max(1, round(len(ranked) * context.rules.certify.top_share)) if ranked else 0
        drafts = []
        rejections = []
        for position, (subject, reads) in enumerate(ranked):
            reason = self._rejection(context, subject, reads, in_top_share=position < top_count)
            if reason is not None:
                rejections.append(Rejection(subject=subject, reason=reason))
                continue
            drafts.append(
                self.draft(
                    context,
                    subject,
                    CertifyPayload(subject_name=context.inventory.name_of(subject) or ""),
                    score=float(_traffic(reads)),
                    score_inputs={"human_requests": reads.human_requests, "human_users": reads.human_users},
                )
            )
        return CandidateResult(drafts=tuple(drafts), rejections=tuple(rejections))

    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool:
        return context.inventory.name_of(subject) is None or subject in context.inventory.certified

    def _is_certifiable(self, context: CandidateContext, subject: Subject) -> bool:
        if subject.kind == WarehouseSuggestionSubjectKind.TABLE:
            return subject.id in context.inventory.table_names
        saved_query = context.inventory.saved_queries.get(subject.id)
        return saved_query is not None and context.is_suggestible_view(saved_query)

    def _rejection(
        self, context: CandidateContext, subject: Subject, reads: SubjectReads, *, in_top_share: bool
    ) -> str | None:
        rules = context.rules.certify
        min_days = context.scaled_floor(rules.min_days)
        if not in_top_share:
            return f"outside the top {rules.top_share:.0%} by requests times people"
        if subject in context.inventory.certified:
            return "already has a certification"
        if reads.human_users < rules.min_users:
            return f"read by {reads.human_users} people, needs {rules.min_users}"
        if reads.human_days < min_days:
            return f"read on {reads.human_days} days, needs {min_days}"
        if len(reads.surfaces) < rules.min_surfaces:
            return f"read from {len(reads.surfaces)} surfaces, needs {rules.min_surfaces}"
        return None


def _traffic(reads: SubjectReads) -> int:
    return reads.human_requests * reads.human_users
