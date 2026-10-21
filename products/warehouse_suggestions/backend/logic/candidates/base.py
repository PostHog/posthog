import hashlib
from abc import ABC, abstractmethod
from collections.abc import Collection, Mapping
from datetime import datetime
from math import ceil
from typing import Any, ClassVar
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.api import upstream_table_refs
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition

from ...facade.contracts import PAYLOAD_VERSION, SuggestionDraft, SuggestionPayload
from ...facade.enums import WarehouseSuggestionAssetOutcome, WarehouseSuggestionKind
from ..inventory import TeamInventory
from ..reads import Subject, TeamReads
from ..rules import Rules, rules_version

DAYS_PER_MONTH = 30
MILLISECONDS_PER_SECOND = 1000
DEPENDENTS_REJECTION = "other views read from it"
FEEDS_CONSUMERS_REJECTION = "its refreshes feed person or account properties, a destination or a workflow"
DIRECT_SOURCE_REJECTION = "reads a direct-connection source, whose reads are not logged"


def reads_direct_source(team_id: int, saved_query_id: UUID, direct_table_ids: Collection[UUID]) -> bool:
    if not direct_table_ids:
        return False
    return any(
        ref.warehouse_table_id is not None and UUID(ref.warehouse_table_id) in direct_table_ids
        for ref in upstream_table_refs(team_id, saved_query_id)
    )


@frozen
class CandidateContext:
    team_id: int
    reads: TeamReads
    inventory: TeamInventory
    rules: Rules
    run_id: str
    recent_accepts: Mapping[WarehouseSuggestionKind, frozenset[UUID]]

    def accepted_recently(self, kind: WarehouseSuggestionKind, saved_query_id: UUID) -> bool:
        return saved_query_id in self.recent_accepts.get(kind, frozenset())

    def is_read(self, subject: Subject) -> bool:
        reads = self.reads.reads_of(subject)
        if reads is None:
            return False
        return self.rules.deprecate.counts_background_reads or reads.human_requests > 0

    def reads_direct_source(self, saved_query_id: UUID) -> bool:
        return reads_direct_source(self.team_id, saved_query_id, self.inventory.direct_table_ids)

    @property
    def days_observed(self) -> int:
        return max(1, min(self.reads.days_with_data, self.rules.window_days))

    @property
    def month_scale(self) -> float:
        return DAYS_PER_MONTH / self.days_observed

    def scaled_floor(self, floor: int) -> int:
        return max(1, ceil(floor * self.days_observed / self.rules.window_days))

    def is_suggestible_view(self, saved_query: SavedQueryDefinition) -> bool:
        return (
            not saved_query.is_test
            and not saved_query.is_managed
            and saved_query.origin not in self.rules.subjects.excluded_view_origins
        )


@frozen
class Rejection:
    subject: Subject
    reason: str


@frozen
class CandidateResult:
    drafts: tuple[SuggestionDraft, ...]
    rejections: tuple[Rejection, ...]
    skipped_reason: str | None = None


class Candidate(ABC):
    kind: ClassVar[WarehouseSuggestionKind]

    @abstractmethod
    def evaluate(self, context: CandidateContext) -> CandidateResult: ...

    @abstractmethod
    def is_resolved(self, context: CandidateContext, subject: Subject) -> bool: ...

    @abstractmethod
    def asset_outcome(
        self, context: CandidateContext, subject: Subject, accepted_at: datetime | None
    ) -> WarehouseSuggestionAssetOutcome: ...

    def draft(
        self,
        context: CandidateContext,
        subject: Subject,
        payload: SuggestionPayload,
        *,
        score: float,
        score_inputs: Mapping[str, float],
    ) -> SuggestionDraft:
        return SuggestionDraft(
            kind=self.kind,
            fingerprint=fingerprint(self.kind, subject),
            subject_kind=subject.kind,
            subject_id=subject.id,
            payload=payload,
            payload_version=PAYLOAD_VERSION,
            rules_version=rules_version(context.rules),
            evidence=evidence_of(context, subject),
            evidence_window_start=context.reads.window.starts_at,
            evidence_window_end=context.reads.window.ends_at,
            score=score,
            score_inputs=dict(score_inputs),
            run_id=context.run_id,
        )


def fingerprint(kind: WarehouseSuggestionKind, subject: Subject) -> str:
    return hashlib.sha256(f"{kind}:{subject.kind}:{subject.id}".encode()).hexdigest()


def evidence_of(context: CandidateContext, subject: Subject) -> dict[str, Any]:
    reads = context.reads.reads_of(subject)
    if reads is None:
        return {"days_with_data": context.reads.days_with_data, "human_requests": 0, "human_users": 0}
    return {
        "days_with_data": context.reads.days_with_data,
        "human_requests": reads.human_requests,
        "human_users": reads.human_users,
        "human_days": reads.human_days,
        "background_requests": reads.background_requests,
        "requests_by_surface": {surface.value: count for surface, count in reads.requests_by_surface.items()},
        "last_read_at": reads.last_read_at.isoformat(),
    }


def certification_outcome(
    context: CandidateContext, subject: Subject, expected_status: CertificationStatus
) -> WarehouseSuggestionAssetOutcome:
    status = context.inventory.certifications.get(subject)
    if status is None:
        return WarehouseSuggestionAssetOutcome.DELETED
    if status == expected_status:
        return WarehouseSuggestionAssetOutcome.LIVE
    return WarehouseSuggestionAssetOutcome.UNUSED
