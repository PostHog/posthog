import hashlib
from abc import ABC, abstractmethod
from collections.abc import Mapping
from math import ceil
from typing import Any, ClassVar

from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.contracts import SavedQueryDefinition

from ...facade.contracts import PAYLOAD_VERSION, SuggestionDraft, SuggestionPayload
from ...facade.enums import WarehouseSuggestionKind
from ..inventory import TeamInventory
from ..reads import Subject, TeamReads
from ..rules import Rules, rules_version

DAYS_PER_MONTH = 30
MILLISECONDS_PER_SECOND = 1000


@frozen
class CandidateContext:
    team_id: int
    reads: TeamReads
    inventory: TeamInventory
    rules: Rules
    run_id: str

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
