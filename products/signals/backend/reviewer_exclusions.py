"""Standing instructions that keep a person off automatic reviewer selection in one area.

A person who left an area records one instruction, and every automatic writer (research, scouts,
custom agents) honors it through `ReviewerRules.prepare`. An instruction applies to a report when the
report's selected repository matches and, for a path instruction, when one of its finding paths is
under the prefix. When the report or the instruction cannot answer that question, the selection
stays unresolved instead of guessing. Pull request assignment reads the same instructions, so an
excluded person is neither assigned nor asked to review.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import SuggestedReviewerEntry
from products.signals.backend.models import (
    SignalReportArtefact,
    SignalReviewerExclusion,
    SignalReviewerExclusionRevision,
)
from products.signals.backend.report_generation.resolve_reviewers import (
    get_org_member_github_logins_by_user_uuid,
    resolve_org_github_login_to_users,
)

SubjectMatch = Literal["none", "match", "ambiguous"]


class DuplicateExclusion(ValueError):
    pass


@frozen
class StandingExclusion:
    id: str
    subject: SuggestedReviewerEntry
    # The subject with its missing identity filled from the organization's GitHub links.
    resolved_subject: SuggestedReviewerEntry
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


def _normalized_login(login: str | None) -> str | None:
    return (login.strip().lower() or None) if login else None


def _comparable(subject: SuggestedReviewerEntry, candidate: SuggestedReviewerEntry) -> bool:
    return bool((subject.user_uuid and candidate.user_uuid) or (subject.github_login and candidate.github_login))


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
    def load(cls, *, team_id: int, report_id: str, repository: str | None = None) -> StandingExclusions:
        """Read the team's instructions against the report's area.

        `repository` overrides the report's repository selection, for a caller that already knows
        the repository the work landed in.
        """
        subjects = [
            (
                str(row.id),
                SuggestedReviewerEntry(
                    user_uuid=str(row.subject_user_uuid) if row.subject_user_uuid else None,
                    github_login=_normalized_login(row.subject_github_login),
                ),
                row.repository.strip().lower(),
                _normalized_path(row.path_prefix),
            )
            for row in SignalReviewerExclusion.objects.for_team(team_id)
            .filter(status=SignalReviewerExclusion.Status.ACTIVE)
            .order_by("created_at", "id")
        ]
        if not subjects:
            return cls(exclusions=(), repository=None, paths=())
        exclusions = cls._resolve_subjects(team_id, subjects)
        artefacts = SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id)
        if repository is None:
            selection = (
                artefacts.filter(type=SignalReportArtefact.ArtefactType.REPO_SELECTION)
                .order_by("-created_at", "-id")
                .values_list("content", flat=True)
                .first()
            )
            repository = cls._read_repository(selection)
        else:
            repository = repository.strip().lower() or None
        paths: tuple[str, ...] = ()
        if any(exclusion.path_prefix for exclusion in exclusions):
            paths = cls._read_paths(
                artefacts.filter(type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING)
                .order_by("-created_at", "-id")
                .values_list("content", flat=True)
            )
        return cls(exclusions=exclusions, repository=repository, paths=paths)

    @staticmethod
    def _resolve_subjects(
        team_id: int, subjects: list[tuple[str, SuggestedReviewerEntry, str, str]]
    ) -> tuple[StandingExclusion, ...]:
        """Fill each subject's missing identity, so a login-only candidate matches a user-only instruction."""
        logins_by_uuid = get_org_member_github_logins_by_user_uuid(
            team_id, sorted({s.user_uuid for _, s, _, _ in subjects if s.user_uuid and not s.github_login})
        )
        users_by_login = resolve_org_github_login_to_users(
            team_id, {s.github_login for _, s, _, _ in subjects if s.github_login and not s.user_uuid}
        )
        resolved: list[StandingExclusion] = []
        for exclusion_id, subject, repository, path_prefix in subjects:
            user = users_by_login.get(subject.github_login) if subject.github_login else None
            resolved.append(
                StandingExclusion(
                    id=exclusion_id,
                    subject=subject,
                    resolved_subject=SuggestedReviewerEntry(
                        user_uuid=subject.user_uuid or (str(user.uuid) if user else None),
                        github_login=subject.github_login
                        or (logins_by_uuid.get(subject.user_uuid) if subject.user_uuid else None),
                    ),
                    repository=repository,
                    path_prefix=path_prefix,
                )
            )
        return tuple(resolved)

    @staticmethod
    def _read_repository(content: str | None) -> str | None:
        try:
            data = json.loads(content or "")
        except ValueError:
            return None
        repository = data.get("repository") if isinstance(data, dict) else None
        return repository.strip().lower() if isinstance(repository, str) and repository.strip() else None

    @staticmethod
    def _read_paths(newest_first: Iterable[str]) -> tuple[str, ...]:
        """The paths of each signal's current finding. Re-research supersedes a signal's older findings."""
        paths: dict[str, None] = {}
        seen_signals: set[str] = set()
        for content in newest_first:
            try:
                data = json.loads(content)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            signal_id = data.get("signal_id")
            if isinstance(signal_id, str):
                if signal_id in seen_signals:
                    continue
                seen_signals.add(signal_id)
            found = data.get("relevant_code_paths")
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

    def _verdict(self, candidate: SuggestedReviewerEntry) -> tuple[StandingExclusion | None, bool]:
        """The first instruction that removes the candidate, and whether another one cannot tell."""
        suppressing: StandingExclusion | None = None
        unresolved = False
        for exclusion in self.exclusions:
            # The stored identities decide when they share one with the candidate. Filled identities
            # only stand in when they share none, so a stale login cannot contradict a matching user.
            subject = exclusion.subject if _comparable(exclusion.subject, candidate) else exclusion.resolved_subject
            match = _subject_match(subject, candidate)
            if match == "none":
                continue
            applies = self._applies(exclusion)
            if applies is False:
                continue
            if applies is None or match == "ambiguous":
                unresolved = True
            elif suppressing is None:
                suppressing = exclusion
        return suppressing, unresolved

    def review(self, candidates: tuple[SuggestedReviewerEntry, ...]) -> ExclusionReview:
        kept: list[SuggestedReviewerEntry] = []
        suppressed: list[Suppression] = []
        unresolved = False
        for candidate in candidates:
            suppressing, uncertain = self._verdict(candidate)
            unresolved = unresolved or uncertain
            if suppressing is None:
                kept.append(candidate)
            else:
                suppressed.append(Suppression(exclusion_id=suppressing.id, reviewer=candidate))
        return ExclusionReview(kept=tuple(kept), suppressed=tuple(suppressed), unresolved=unresolved)

    def allowed_logins(self, logins: list[str]) -> list[str]:
        """The GitHub logins no instruction keeps off this area. A login nobody can decide on is left out."""
        allowed: list[str] = []
        for login in logins:
            suppressing, unresolved = self._verdict(SuggestedReviewerEntry(github_login=login.lower()))
            if suppressing is None and not unresolved:
                allowed.append(login)
        return allowed


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
) -> tuple[SignalReviewerExclusion, bool]:
    """Create an instruction, or return the active one for the same subject and area.

    Returns the instruction and whether it was created, so a retried request does not leave a twin.
    """
    login = _normalized_login(subject_github_login)
    if subject_user_uuid is None and login is None:
        raise ValueError("An exclusion needs a user or a GitHub login.")
    area = {
        "subject_user_uuid": subject_user_uuid,
        "subject_github_login": login,
        "repository": repository.strip().lower(),
        "path_prefix": _normalized_path(path_prefix),
    }
    active = SignalReviewerExclusion.objects.for_team(team_id).filter(
        status=SignalReviewerExclusion.Status.ACTIVE, **area
    )
    if existing := active.first():
        return existing, False
    try:
        with transaction.atomic():
            exclusion = SignalReviewerExclusion.objects.for_team(team_id).create(
                team_id=team_id, instruction=instruction, created_by_id=actor_id, **area
            )
            _record_revision(exclusion, SignalReviewerExclusionRevision.Action.CREATED, actor_id)
    except IntegrityError:
        # A concurrent create of the same instruction won the unique constraint.
        if existing := active.first():
            return existing, False
        raise
    return exclusion, True


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
        twin = (
            SignalReviewerExclusion.objects.for_team(team_id)
            .filter(
                status=SignalReviewerExclusion.Status.ACTIVE,
                subject_user_uuid=exclusion.subject_user_uuid,
                subject_github_login=exclusion.subject_github_login,
                repository=exclusion.repository,
                path_prefix=exclusion.path_prefix,
            )
            .exclude(id=exclusion.id)
        )
        if twin.exists():
            raise DuplicateExclusion("An active exclusion already covers this person and area.")
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
