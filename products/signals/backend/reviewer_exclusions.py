"""Standing instructions that keep a person off automatic reviewer selection in one area.

A person who left an area records one instruction, and every automatic writer (research, scouts,
custom agents) honors it through `ReviewerRules.prepare`. An instruction applies to a report when the
report's selected repository matches and, for a path instruction, when one of its finding paths is
under the prefix. When the report or the instruction cannot answer that question, the selection
stays unresolved instead of guessing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import SuggestedReviewerEntry
from products.signals.backend.models import (
    SignalReportArtefact,
    SignalReviewerExclusion,
    SignalReviewerExclusionRevision,
)

SubjectMatch = Literal["none", "match", "ambiguous"]


@frozen
class StandingExclusion:
    id: str
    subject: SuggestedReviewerEntry
    repository: str
    path_prefix: str


@frozen
class Suppression:
    exclusion_id: str
    reviewer: SuggestedReviewerEntry


@frozen
class ExclusionReview:
    kept: tuple[SuggestedReviewerEntry, ...]
    suppressed: tuple[Suppression, ...]
    unresolved: bool


def _normalized_path(path: str) -> str:
    return path.strip().removeprefix("./").strip("/")


def _subject_match(subject: SuggestedReviewerEntry, candidate: SuggestedReviewerEntry) -> SubjectMatch:
    uuids = (subject.user_uuid, candidate.user_uuid)
    logins = (
        subject.github_login.lower() if subject.github_login else None,
        candidate.github_login.lower() if candidate.github_login else None,
    )
    agree = any(left is not None and left == right for left, right in (uuids, logins))
    disagree = any(left is not None and right is not None and left != right for left, right in (uuids, logins))
    if not agree:
        return "none"
    # One identity says it is the subject and the other says it is not, so nobody can tell.
    return "ambiguous" if disagree else "match"


class StandingExclusions:
    """The team's active instructions, read against one report's area evidence."""

    def __init__(
        self,
        *,
        exclusions: tuple[StandingExclusion, ...],
        repository: str | None,
        paths: tuple[str, ...],
    ) -> None:
        self.exclusions = exclusions
        self.repository = repository
        self.paths = paths

    @classmethod
    def load(cls, *, team_id: int, report_id: str) -> StandingExclusions:
        exclusions = tuple(
            StandingExclusion(
                id=str(row.id),
                subject=SuggestedReviewerEntry(
                    user_uuid=str(row.subject_user_uuid) if row.subject_user_uuid else None,
                    github_login=row.subject_github_login.lower() if row.subject_github_login else None,
                ),
                repository=row.repository.strip().lower(),
                path_prefix=_normalized_path(row.path_prefix),
            )
            for row in SignalReviewerExclusion.objects.for_team(team_id)
            .filter(status=SignalReviewerExclusion.Status.ACTIVE)
            .order_by("created_at", "id")
        )
        if not exclusions:
            return cls(exclusions=(), repository=None, paths=())
        artefacts = SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id)
        selection = (
            artefacts.filter(type=SignalReportArtefact.ArtefactType.REPO_SELECTION)
            .order_by("-created_at", "-id")
            .values_list("content", flat=True)
            .first()
        )
        repository = cls._read_repository(selection)
        paths: tuple[str, ...] = ()
        if any(exclusion.path_prefix for exclusion in exclusions):
            paths = cls._read_paths(
                artefacts.filter(type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING).values_list(
                    "content", flat=True
                )
            )
        return cls(exclusions=exclusions, repository=repository, paths=paths)

    @staticmethod
    def _read_repository(content: str | None) -> str | None:
        try:
            data = json.loads(content or "")
        except ValueError:
            return None
        repository = data.get("repository") if isinstance(data, dict) else None
        return repository.strip().lower() if isinstance(repository, str) and repository.strip() else None

    @staticmethod
    def _read_paths(contents: Iterable[str]) -> tuple[str, ...]:
        paths: dict[str, None] = {}
        for content in contents:
            try:
                data = json.loads(content)
            except ValueError:
                continue
            found = data.get("relevant_code_paths") if isinstance(data, dict) else None
            for path in found if isinstance(found, list) else ():
                if isinstance(path, str) and _normalized_path(path):
                    paths[_normalized_path(path)] = None
        return tuple(paths)

    def _applies(self, exclusion: StandingExclusion) -> bool | None:
        """Whether the instruction covers this report, or None when the report cannot tell."""
        if not exclusion.repository:
            return True
        if self.repository is None:
            return None
        if self.repository != exclusion.repository:
            return False
        if not exclusion.path_prefix:
            return True
        if not self.paths:
            return None
        return any(path == exclusion.path_prefix or path.startswith(f"{exclusion.path_prefix}/") for path in self.paths)

    def review(self, candidates: tuple[SuggestedReviewerEntry, ...]) -> ExclusionReview:
        kept: list[SuggestedReviewerEntry] = []
        suppressed: list[Suppression] = []
        unresolved = False
        for candidate in candidates:
            suppressing: StandingExclusion | None = None
            for exclusion in self.exclusions:
                match = _subject_match(exclusion.subject, candidate)
                if match == "none":
                    continue
                applies = self._applies(exclusion)
                if applies is False:
                    continue
                if applies is None or match == "ambiguous":
                    unresolved = True
                elif suppressing is None:
                    suppressing = exclusion
            if suppressing is None:
                kept.append(candidate)
            else:
                suppressed.append(Suppression(exclusion_id=suppressing.id, reviewer=candidate))
        return ExclusionReview(kept=tuple(kept), suppressed=tuple(suppressed), unresolved=unresolved)


def _record_revision(
    exclusion: SignalReviewerExclusion, action: SignalReviewerExclusionRevision.Action, actor_id: int | None
) -> None:
    SignalReviewerExclusionRevision.objects.for_team(exclusion.team_id).create(
        team_id=exclusion.team_id,
        exclusion=exclusion,
        revision=exclusion.revision,
        action=action,
        subject_user_uuid=exclusion.subject_user_uuid,
        subject_github_login=exclusion.subject_github_login,
        repository=exclusion.repository,
        path_prefix=exclusion.path_prefix,
        instruction=exclusion.instruction,
        status=exclusion.status,
        actor_id=actor_id,
    )


def create_exclusion(
    *,
    team_id: int,
    actor_id: int,
    instruction: str,
    subject_user_uuid: UUID | None = None,
    subject_github_login: str | None = None,
    repository: str = "",
    path_prefix: str = "",
) -> SignalReviewerExclusion:
    with transaction.atomic():
        exclusion = SignalReviewerExclusion.objects.for_team(team_id).create(
            team_id=team_id,
            subject_user_uuid=subject_user_uuid,
            subject_github_login=subject_github_login.strip().lower() if subject_github_login else None,
            repository=repository.strip().lower(),
            path_prefix=_normalized_path(path_prefix),
            instruction=instruction,
            created_by_id=actor_id,
        )
        _record_revision(exclusion, SignalReviewerExclusionRevision.Action.CREATED, actor_id)
    return exclusion


def revise_exclusion(
    *,
    team_id: int,
    exclusion_id: UUID | str,
    actor_id: int,
    instruction: str | None = None,
    repository: str | None = None,
    path_prefix: str | None = None,
) -> SignalReviewerExclusion:
    with transaction.atomic():
        exclusion = (
            SignalReviewerExclusion.objects.for_team(team_id)
            .select_for_update()
            .get(id=exclusion_id, status=SignalReviewerExclusion.Status.ACTIVE)
        )
        if instruction is not None:
            exclusion.instruction = instruction
        if repository is not None:
            exclusion.repository = repository.strip().lower()
        if path_prefix is not None:
            exclusion.path_prefix = _normalized_path(path_prefix)
        exclusion.revision += 1
        exclusion.save()
        _record_revision(exclusion, SignalReviewerExclusionRevision.Action.REVISED, actor_id)
    return exclusion


def revoke_exclusion(*, team_id: int, exclusion_id: UUID | str, actor_id: int) -> SignalReviewerExclusion:
    with transaction.atomic():
        exclusion = SignalReviewerExclusion.objects.for_team(team_id).select_for_update().get(id=exclusion_id)
        if exclusion.status == SignalReviewerExclusion.Status.REVOKED:
            return exclusion
        exclusion.status = SignalReviewerExclusion.Status.REVOKED
        exclusion.revision += 1
        exclusion.save()
        _record_revision(exclusion, SignalReviewerExclusionRevision.Action.REVOKED, actor_id)
    return exclusion
