"""Standing instructions that keep a person off automatic reviewer selection in one area.

A person who left an area records one instruction, and every automatic writer (research, scouts,
custom agents) honors it through `ReviewerRules.prepare`. An instruction applies to a report when the
report's selected repository matches and, for a path instruction, when one of its finding paths is
under the prefix. When the report or the instruction cannot answer that question, the selection
stays unresolved instead of guessing. Pull request assignment reads the same instructions, so an
excluded person is neither assigned nor asked to review.

The subject of an instruction is always a PostHog user. A candidate known only by a GitHub login
resolves to the member who links that login now. A login that resolves to nobody cannot be excluded.
"""

from __future__ import annotations

import json
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import SuggestedReviewerEntry
from products.signals.backend.models import (
    SignalReportArtefact,
    SignalReviewerExclusion,
    SignalReviewerExclusionRevision,
)
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = structlog.get_logger(__name__)


class DuplicateExclusion(ValueError):
    pass


@frozen
class StandingExclusion:
    id: str
    user_uuid: str
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


class StandingExclusions:
    """The team's active instructions, read against one report's area evidence."""

    def __init__(
        self,
        *,
        team_id: int,
        report_id: str,
        repository_override: str | None,
        versions: tuple[tuple[UUID, int], ...],
        exclusions: tuple[StandingExclusion, ...],
        repository: str | None,
        paths: tuple[str, ...],
    ) -> None:
        self.team_id = team_id
        self.report_id = report_id
        self.repository_override = repository_override
        self.versions = versions
        self.exclusions = exclusions
        self.repository = repository
        self.paths = paths
        # Each login resolves once per instance, however many candidate lists the caller checks.
        self.user_uuid_by_login: dict[str, str | None] = {}

    @classmethod
    def load(cls, *, team_id: int, report_id: str, repository: str | None = None) -> StandingExclusions:
        """Read the team's instructions against the report's area.

        `repository` overrides the report's repository selection, for a caller that already knows
        the repository the work landed in.
        """
        rows = list(
            SignalReviewerExclusion.objects.for_team(team_id)
            .filter(status=SignalReviewerExclusion.Status.ACTIVE)
            .order_by("created_at", "id")
        )
        versions = tuple((row.id, row.revision) for row in rows)
        exclusions = tuple(
            StandingExclusion(
                id=str(row.id),
                user_uuid=str(row.subject_user_uuid),
                repository=row.repository.strip().lower(),
                path_prefix=_normalized_path(row.path_prefix),
            )
            for row in rows
        )
        if not exclusions:
            return cls(
                team_id=team_id,
                report_id=report_id,
                repository_override=repository,
                versions=versions,
                exclusions=(),
                repository=None,
                paths=(),
            )
        repository_override = repository
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
        # Finding paths decide only a path instruction for this report's repository, and the read runs
        # under the report lock, so skip it for every other report.
        if repository is not None and any(e.path_prefix and e.repository == repository for e in exclusions):
            paths = cls._read_paths(artefacts.filter(type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING))
        return cls(
            team_id=team_id,
            report_id=report_id,
            repository_override=repository_override,
            versions=versions,
            exclusions=exclusions,
            repository=repository,
            paths=paths,
        )

    def refreshed(self) -> StandingExclusions:
        """These instructions when none changed since the load, otherwise a fresh load. One query when none changed."""
        current = tuple(
            SignalReviewerExclusion.objects.for_team(self.team_id)
            .filter(status=SignalReviewerExclusion.Status.ACTIVE)
            .order_by("created_at", "id")
            .values_list("id", "revision")
        )
        if current == self.versions:
            return self
        fresh = StandingExclusions.load(
            team_id=self.team_id, report_id=self.report_id, repository=self.repository_override
        )
        fresh.user_uuid_by_login = self.user_uuid_by_login
        return fresh

    def _member_uuids(self, logins: list[str]) -> list[str | None]:
        """The member each login resolves to now, looked up once per login."""
        normalized = [_normalized_login(login) for login in logins]
        missing = {login for login in normalized if login is not None and login not in self.user_uuid_by_login}
        if missing:
            users = resolve_org_github_login_to_users(self.team_id, missing)
            self.user_uuid_by_login.update(
                {login: str(users[login].uuid) if login in users else None for login in missing}
            )
        return [self.user_uuid_by_login[login] if login is not None else None for login in normalized]

    @staticmethod
    def _read_repository(content: str | None) -> str | None:
        try:
            data = json.loads(content or "")
        except ValueError:
            return None
        repository = data.get("repository") if isinstance(data, dict) else None
        return repository.strip().lower() if isinstance(repository, str) and repository.strip() else None

    @staticmethod
    def _read_paths(findings: QuerySet[SignalReportArtefact]) -> tuple[str, ...]:
        """The paths of each signal's current finding. Re-research supersedes a signal's older findings.

        Content parses in Python because a JSONB cast fails the whole read on one malformed row.
        """
        current: dict[str | None, object] = {}
        for content in (
            findings.filter(content__startswith="{").order_by("-created_at", "-id").values_list("content", flat=True)
        ):
            try:
                data = json.loads(content)
            except ValueError:
                logger.warning("signals.reviewer_exclusions.unreadable_finding")
                continue
            if not isinstance(data, dict):
                continue
            signal_id = data.get("signal_id")
            current.setdefault(None if signal_id is None else str(signal_id), data.get("relevant_code_paths"))
        paths: dict[str, None] = {}
        for found in current.values():
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

    def _verdict(self, user_uuid: str | None) -> tuple[StandingExclusion | None, bool]:
        """The first instruction that removes the member, and whether another one cannot tell."""
        suppressing: StandingExclusion | None = None
        unresolved = False
        for exclusion in self.exclusions:
            if user_uuid is None or exclusion.user_uuid != user_uuid:
                continue
            applies = self._applies(exclusion)
            if applies is False:
                continue
            if applies is None:
                unresolved = True
            elif suppressing is None:
                suppressing = exclusion
        return suppressing, unresolved

    def review(self, candidates: tuple[SuggestedReviewerEntry, ...]) -> ExclusionReview:
        if not self.exclusions:
            return ExclusionReview(kept=candidates, suppressed=(), unresolved=False)
        member_uuids = [
            candidate.user_uuid or member_uuid
            for candidate, member_uuid in zip(
                candidates,
                self._member_uuids(
                    ["" if candidate.user_uuid else candidate.github_login or "" for candidate in candidates]
                ),
            )
        ]
        kept: list[SuggestedReviewerEntry] = []
        suppressed: list[Suppression] = []
        unresolved = False
        for candidate, member_uuid in zip(candidates, member_uuids):
            suppressing, uncertain = self._verdict(member_uuid)
            unresolved = unresolved or uncertain
            if suppressing is None:
                kept.append(candidate)
            else:
                suppressed.append(Suppression(exclusion_id=suppressing.id, reviewer=candidate))
        return ExclusionReview(kept=tuple(kept), suppressed=tuple(suppressed), unresolved=unresolved)

    def allowed_logins(self, logins: list[str]) -> list[str]:
        """The GitHub logins no instruction keeps off this area. A login nobody can decide on is left out."""
        if not self.exclusions:
            return list(logins)
        allowed: list[str] = []
        for login, member_uuid in zip(logins, self._member_uuids(logins)):
            suppressing, unresolved = self._verdict(member_uuid)
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


def _active_twins(
    team_id: int, *, subject_user_uuid: UUID, repository: str, path_prefix: str
) -> QuerySet[SignalReviewerExclusion]:
    """Active instructions with the key of the partial unique index on the model."""
    return SignalReviewerExclusion.objects.for_team(team_id).filter(
        status=SignalReviewerExclusion.Status.ACTIVE,
        subject_user_uuid=subject_user_uuid,
        repository=repository,
        path_prefix=path_prefix,
    )


def create_exclusion(
    *,
    team_id: int,
    actor_id: int,
    instruction: str,
    subject_user_uuid: UUID,
    subject_github_login: str | None = None,
    repository: str = "",
    path_prefix: str = "",
) -> tuple[SignalReviewerExclusion, bool]:
    """Create an instruction, or return the active one for the same member and area.

    Returns the instruction and whether it was created, so a retried request does not leave a twin.
    `subject_github_login` is a snapshot for display and plays no part in matching.
    """
    repository = repository.strip().lower()
    path_prefix = _normalized_path(path_prefix)
    active = _active_twins(team_id, subject_user_uuid=subject_user_uuid, repository=repository, path_prefix=path_prefix)
    if existing := active.first():
        return existing, False
    try:
        with transaction.atomic():
            exclusion = SignalReviewerExclusion.objects.for_team(team_id).create(
                team_id=team_id,
                instruction=instruction,
                created_by_id=actor_id,
                subject_user_uuid=subject_user_uuid,
                subject_github_login=_normalized_login(subject_github_login),
                repository=repository,
                path_prefix=path_prefix,
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
    """Apply the given changes as one new revision. A call that changes nothing records no revision."""
    with transaction.atomic():
        exclusion = (
            SignalReviewerExclusion.objects.for_team(team_id)
            .select_for_update()
            .get(id=exclusion_id, status=SignalReviewerExclusion.Status.ACTIVE)
        )
        changes = {
            field: value
            for field, value in (
                ("instruction", instruction),
                ("repository", repository.strip().lower() if repository is not None else None),
                ("path_prefix", _normalized_path(path_prefix) if path_prefix is not None else None),
            )
            if value is not None and value != getattr(exclusion, field)
        }
        if not changes:
            return exclusion
        for field, value in changes.items():
            setattr(exclusion, field, value)
        twin = _active_twins(
            team_id,
            subject_user_uuid=exclusion.subject_user_uuid,
            repository=exclusion.repository,
            path_prefix=exclusion.path_prefix,
        ).exclude(id=exclusion.id)
        if twin.exists():
            raise DuplicateExclusion("An active exclusion already covers this person and area.")
        exclusion.revision += 1
        try:
            with transaction.atomic():
                exclusion.save()
        except IntegrityError as e:
            # A concurrent amend moved another row onto this area after the twin check.
            raise DuplicateExclusion("An active exclusion already covers this person and area.") from e
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
