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
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F, JSONField, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast

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


class DuplicateExclusion(ValueError):
    pass


@frozen
class StandingExclusion:
    id: str
    # The stored subject, with a missing identity filled from the organization's GitHub links.
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


def _normalized_login(login: str | None) -> str | None:
    return (login.strip().lower() or None) if login else None


def _same_subject(subject: SuggestedReviewerEntry, candidate: SuggestedReviewerEntry) -> bool:
    """A user UUID decides whenever both sides know one. A login decides only when one side has no UUID."""
    if subject.user_uuid and candidate.user_uuid:
        return subject.user_uuid == candidate.user_uuid
    login = _normalized_login(subject.github_login)
    return login is not None and login == _normalized_login(candidate.github_login)


class StandingExclusions:
    """The team's active instructions, read against one report's area evidence."""

    def __init__(
        self,
        *,
        team_id: int,
        exclusions: tuple[StandingExclusion, ...],
        repository: str | None,
        paths: tuple[str, ...],
    ) -> None:
        self.team_id = team_id
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
            return cls(team_id=team_id, exclusions=(), repository=None, paths=())
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
        # Finding paths decide only a path instruction for this report's repository, and the read runs
        # under the report lock, so skip it for every other report.
        if repository is not None and any(e.path_prefix and e.repository == repository for e in exclusions):
            paths = cls._read_paths(artefacts.filter(type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING))
        return cls(team_id=team_id, exclusions=exclusions, repository=repository, paths=paths)

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
                    subject=SuggestedReviewerEntry(
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
    def _read_paths(findings: QuerySet[SignalReportArtefact]) -> tuple[str, ...]:
        """The paths of each signal's current finding. Re-research supersedes a signal's older findings."""
        content = Cast("content", JSONField())
        current_paths = (
            findings.filter(content__startswith="{")
            .annotate(
                _signal_id=KeyTextTransform("signal_id", content),
                _paths=KeyTransform("relevant_code_paths", content),
            )
            .order_by("_signal_id", "-created_at", "-id")
            .distinct("_signal_id")
            .values_list("_signal_id", "_paths")
        )
        paths: dict[str, None] = {}
        for _signal_id, found in current_paths:
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
            if not _same_subject(exclusion.subject, candidate):
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
        if not self.exclusions:
            return list(logins)
        # Resolve each login to its member, so an instruction keyed on the user still applies after a login change.
        users = resolve_org_github_login_to_users(self.team_id, logins)
        allowed: list[str] = []
        for login in logins:
            user = users.get(login.strip().lower())
            candidate = SuggestedReviewerEntry(
                user_uuid=str(user.uuid) if user else None, github_login=_normalized_login(login)
            )
            suppressing, unresolved = self._verdict(candidate)
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
    team_id: int, *, subject_user_uuid: UUID | None, subject_github_login: str | None, repository: str, path_prefix: str
) -> QuerySet[SignalReviewerExclusion]:
    """Active instructions in the same area for the same subject, the rows keyed on the user UUID first.

    A user row and a login-only row with the subject's login name the same person.
    """
    if subject_user_uuid is None:
        subject = Q(subject_github_login=subject_github_login)
    else:
        subject = Q(subject_user_uuid=subject_user_uuid)
        if subject_github_login is not None:
            subject |= Q(subject_user_uuid__isnull=True, subject_github_login=subject_github_login)
    return (
        SignalReviewerExclusion.objects.for_team(team_id)
        .filter(subject, status=SignalReviewerExclusion.Status.ACTIVE, repository=repository, path_prefix=path_prefix)
        .order_by(F("subject_user_uuid").asc(nulls_last=True), "created_at", "id")
    )


def _existing_twin(
    twins: QuerySet[SignalReviewerExclusion], subject_user_uuid: UUID | None, actor_id: int
) -> SignalReviewerExclusion | None:
    """The active twin, with the subject's user attached when the twin knew only the login."""
    with transaction.atomic():
        existing = twins.select_for_update().first()
        if existing is None or subject_user_uuid is None or existing.subject_user_uuid is not None:
            return existing
        existing.subject_user_uuid = subject_user_uuid
        existing.revision += 1
        existing.save()
        _record_revision(existing, SignalReviewerExclusionRevision.Action.REVISED, actor_id)
    return existing


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
    repository = repository.strip().lower()
    path_prefix = _normalized_path(path_prefix)
    active = _active_twins(
        team_id,
        subject_user_uuid=subject_user_uuid,
        subject_github_login=login,
        repository=repository,
        path_prefix=path_prefix,
    )
    if existing := _existing_twin(active, subject_user_uuid, actor_id):
        return existing, False
    try:
        with transaction.atomic():
            exclusion = SignalReviewerExclusion.objects.for_team(team_id).create(
                team_id=team_id,
                instruction=instruction,
                created_by_id=actor_id,
                subject_user_uuid=subject_user_uuid,
                subject_github_login=login,
                repository=repository,
                path_prefix=path_prefix,
            )
            _record_revision(exclusion, SignalReviewerExclusionRevision.Action.CREATED, actor_id)
    except IntegrityError:
        # A concurrent create of the same instruction won the unique constraint.
        if existing := _existing_twin(active, subject_user_uuid, actor_id):
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
            subject_github_login=exclusion.subject_github_login,
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
