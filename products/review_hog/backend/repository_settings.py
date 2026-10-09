"""Writes and reads behind the repository settings API: claims, repository rows, personal choices.

The viewsets stay thin and call these classes. Every write keeps the ownership rules of
`ownership.py`: a repository has at most one row across projects, at most one project takes all
repositories of an installation, and a project only stores what differs from what it inherits.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from django.db import IntegrityError, models, transaction

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.activity_logging import log_repository_taken
from products.review_hog.backend.automatic_review_rules import (
    AuthorPreferences,
    AutomaticReviewDecision,
    AutomaticReviewReason,
    ProjectRuleContext,
    load_author_preferences,
)
from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
)
from products.review_hog.backend.ownership import RepositoryOwnership, RepositoryRef, find_matching_row, resolve_owner


class Unset:
    """Marks a field the request did not mention, because None is a valid value."""


UNSET = Unset()


class RepositorySettingsError(Exception):
    """A write the rules do not allow. The API answers 400 with the message."""


@frozen
class ProjectRef:
    """Another project, named only inside its own organization."""

    team_id: int
    name: str | None

    @classmethod
    def load(cls, team_id: int, *, viewer_organization_id: Any) -> "ProjectRef":
        team = Team.objects.filter(id=team_id).values("name", "organization_id").first() or {}
        same_organization = team.get("organization_id") == viewer_organization_id
        return cls(team_id=team_id, name=team.get("name") if same_organization else None)

    @property
    def label(self) -> str:
        return f"the {self.name} project" if self.name else "a project in another organization"


class OwnershipConflict(Exception):
    """Another project already holds what this write asks for. The API answers 409."""

    def __init__(self, message: str, project: ProjectRef | None) -> None:
        super().__init__(message)
        self.project = project


@frozen
class RepositoryWriteResult:
    # None when the write left nothing to store, so the row was deleted.
    repository: ReviewRepository | None
    # The project that took all repositories of the installation, when this write took one from it.
    taken_from: ProjectRef | None


@frozen
class InstallationSummary:
    installation_id: str
    account_name: str
    connected_by: User | None
    claim: ReviewInstallationClaim | None
    all_taken_by: ProjectRef | None


class ProjectRepositories:
    """The repository settings of one project, as one acting user changes them."""

    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.team_id = team.id
        self.user = user

    def _project(self, team_id: int) -> ProjectRef:
        return ProjectRef.load(team_id, viewer_organization_id=self.team.organization_id)

    def integrations(self) -> list[Integration]:
        return list(
            Integration.objects.filter(team_id=self.team_id, kind="github").select_related("created_by").order_by("id")
        )

    def integration_for(self, installation_id: str) -> Integration:
        integration = next((row for row in self.integrations() if row.integration_id == installation_id), None)
        if integration is None:
            raise RepositorySettingsError("This project has no GitHub connection for that installation.")
        return integration

    def claim_for(self, installation_id: str) -> ReviewInstallationClaim | None:
        return ReviewInstallationClaim.objects.for_team(self.team_id).filter(installation_id=installation_id).first()

    def installations(self) -> list[InstallationSummary]:
        claims = {claim.installation_id: claim for claim in ReviewInstallationClaim.objects.for_team(self.team_id)}
        summaries: list[InstallationSummary] = []
        for integration in self.integrations():
            installation_id = integration.integration_id or ""
            all_claim = RepositoryOwnership.all_claim(installation_id)
            account = (integration.config or {}).get("account") or {}
            summaries.append(
                InstallationSummary(
                    installation_id=installation_id,
                    account_name=account.get("name") or installation_id,
                    connected_by=integration.created_by,
                    claim=claims.get(installation_id),
                    all_taken_by=(
                        self._project(all_claim.team_id)
                        if all_claim is not None and all_claim.team_id != self.team_id
                        else None
                    ),
                )
            )
        return summaries

    def _check_all_is_free(self, installation_id: str) -> None:
        all_claim = RepositoryOwnership.all_claim(installation_id)
        if all_claim is not None and all_claim.team_id != self.team_id:
            project = self._project(all_claim.team_id)
            raise OwnershipConflict(
                f"All repositories of this installation are already reviewed in {project.label}.", project
            )

    def _delete_rows(self, installation_id: str, *, only_unselected: bool) -> None:
        rows = ReviewRepository.objects.for_team(self.team_id).filter(installation_id=installation_id)
        if only_unselected:
            rows = rows.filter(selected=False)
        # One delete per row, so the activity log records each one.
        for row in rows:
            row.delete()

    def create_claim(self, installation_id: str, scope: str) -> ReviewInstallationClaim:
        self.integration_for(installation_id)
        if self.claim_for(installation_id) is not None:
            raise RepositorySettingsError("This project already has a choice for that installation. Change it instead.")
        if scope == ReviewInstallationClaim.Scope.ALL:
            self._check_all_is_free(installation_id)
        try:
            with transaction.atomic():
                return ReviewInstallationClaim.objects.for_team(self.team_id).create(
                    team_id=self.team_id, installation_id=installation_id, scope=scope, created_by=self.user
                )
        except IntegrityError:
            # A concurrent write took all repositories, or added the same claim.
            self._check_all_is_free(installation_id)
            raise RepositorySettingsError("This project already has a choice for that installation. Change it instead.")

    def update_claim(self, claim: ReviewInstallationClaim, scope: str) -> ReviewInstallationClaim:
        if scope == claim.scope:
            return claim
        if scope == ReviewInstallationClaim.Scope.ALL:
            self._check_all_is_free(claim.installation_id)
        with transaction.atomic():
            if scope == ReviewInstallationClaim.Scope.SELECTED:
                # The repositories this project did not select leave it, and their exceptions go too.
                self._delete_rows(claim.installation_id, only_unselected=True)
            claim.scope = scope
            try:
                with transaction.atomic():
                    claim.save()
            except IntegrityError:
                self._check_all_is_free(claim.installation_id)
                raise
        return claim

    def delete_claim(self, claim: ReviewInstallationClaim) -> None:
        with transaction.atomic():
            self._delete_rows(claim.installation_id, only_unselected=False)
            claim.delete()

    def save_repository(
        self,
        ref: RepositoryRef,
        *,
        selected: bool | None = None,
        flash_for: str | None | Unset = UNSET,
    ) -> RepositoryWriteResult:
        """Include or remove a repository, or set or clear its exception. Omitted fields keep their value."""
        self.integration_for(ref.installation_id)
        with transaction.atomic():
            row = find_matching_row(ref, RepositoryOwnership.rows_for(ref))
            if row is not None and row.team_id != self.team_id:
                project = self._project(row.team_id)
                raise OwnershipConflict(f"{ref.full_name} is already reviewed in {project.label}.", project)
            claim = self.claim_for(ref.installation_id)
            takes_all = claim is not None and claim.scope == ReviewInstallationClaim.Scope.ALL
            was_selected = row is not None and row.selected
            new_selected = selected if selected is not None else was_selected
            if isinstance(flash_for, Unset):
                new_flash_for = row.flash_for if row is not None else None
            else:
                new_flash_for = flash_for

            if not new_selected and not takes_all:
                if isinstance(flash_for, str):
                    raise RepositorySettingsError("Include the repository in this project before you add an exception.")
                # The repository leaves the project, so its exception goes too.
                new_flash_for = None
            if not new_selected and new_flash_for is None:
                if row is not None:
                    row.delete()
                return RepositoryWriteResult(repository=None, taken_from=None)

            all_claim = RepositoryOwnership.all_claim(ref.installation_id)
            taken_from_claim = (
                all_claim
                if new_selected and not was_selected and all_claim is not None and all_claim.team_id != self.team_id
                else None
            )
            if claim is None:
                ReviewInstallationClaim.objects.for_team(self.team_id).create(
                    team_id=self.team_id,
                    installation_id=ref.installation_id,
                    scope=ReviewInstallationClaim.Scope.SELECTED,
                    created_by=self.user,
                )
            if row is None:
                row = ReviewRepository(
                    team_id=self.team_id,
                    installation_id=ref.installation_id,
                    full_name=ref.full_name,
                    created_by=self.user,
                )
            if row.github_repo_id is None and ref.github_repo_id is not None:
                row.github_repo_id = ref.github_repo_id
            row.selected = new_selected
            row.flash_for = new_flash_for
            try:
                with transaction.atomic():
                    row.save()
            except IntegrityError:
                raise OwnershipConflict(f"{ref.full_name} is already reviewed in another project.", None)
            if taken_from_claim is not None:
                log_repository_taken(
                    claim=taken_from_claim, full_name=ref.full_name, taken_by_team_id=self.team_id, user=self.user
                )
        return RepositoryWriteResult(
            repository=row,
            taken_from=self._project(taken_from_claim.team_id) if taken_from_claim is not None else None,
        )

    def add_person(self, repository: ReviewRepository | None, *, user_id: int, kind: str) -> bool:
        """Add a person to a list of the project rule (no repository) or of an exception. True when added."""
        _person, created = ReviewRepositoryPerson.objects.for_team(self.team_id).get_or_create(
            team_id=self.team_id, repository=repository, user_id=user_id, kind=kind
        )
        return created


class RepositoryOwnerKind(models.TextChoices):
    THIS_PROJECT = "this_project", "This project"
    OTHER_PROJECT = "other_project", "Another project"
    NONE = "none", "No project"


class RepositoryOverviewView(models.TextChoices):
    ALL = "all", "All repositories"
    IN_PROJECT = "in_project", "In this project"
    EXCEPTIONS = "exceptions", "With exceptions"
    MINE = "mine", "My choices"


@frozen
class OverviewEntry:
    full_name: str
    github_repo_id: int | None
    owner: RepositoryOwnerKind
    owner_project: ProjectRef | None
    in_project: bool
    selected: bool
    repository: ReviewRepository | None
    exception_people: Sequence[ReviewRepositoryPerson]
    my_choice: ReviewUserRepositoryChoice | None
    my_result: AutomaticReviewDecision


class RepositoryOverview:
    """Every repository an installation can see, joined with this project's settings and the viewer's.

    The decision comes from the same resolver as the automatic dispatch, so the UI never re-implements it.
    """

    def __init__(self, team: Team, user: User, installation_id: str) -> None:
        self.team = team
        self.user = user
        self.installation_id = installation_id
        self.rows = list(ReviewRepository.objects.unscoped().filter(installation_id=installation_id))
        self.all_claim = RepositoryOwnership.all_claim(installation_id)
        own_rows = [row for row in self.rows if row.team_id == team.id]
        self.rules = ProjectRuleContext.load(team.id, own_rows)
        self.viewer: AuthorPreferences = load_author_preferences(team.id, user_id=user.id, is_bot=False)
        self._projects: dict[int, ProjectRef] = {}

    def _project(self, team_id: int) -> ProjectRef:
        if team_id not in self._projects:
            self._projects[team_id] = ProjectRef.load(team_id, viewer_organization_id=self.team.organization_id)
        return self._projects[team_id]

    def entry(self, repository: Mapping[str, Any]) -> OverviewEntry:
        github_repo_id = repository.get("id") if isinstance(repository.get("id"), int) else None
        ref = RepositoryRef(
            installation_id=self.installation_id, github_repo_id=github_repo_id, full_name=str(repository["full_name"])
        )
        owner = resolve_owner(ref, self.rows, self.all_claim)
        own_row = find_matching_row(ref, [row for row in self.rows if row.team_id == self.team.id])
        in_project = owner is not None and owner.team_id == self.team.id
        choice = self.viewer.choice_for(ref)
        if in_project:
            result = self.rules.rule_for(own_row).resolve(self.viewer.for_repository(ref))
        else:
            result = AutomaticReviewDecision(flash=False, reason=AutomaticReviewReason.NOT_IN_PROJECT)
        if owner is None:
            owner_kind, owner_project = RepositoryOwnerKind.NONE, None
        elif in_project:
            owner_kind, owner_project = RepositoryOwnerKind.THIS_PROJECT, None
        else:
            owner_kind, owner_project = RepositoryOwnerKind.OTHER_PROJECT, self._project(owner.team_id)
        has_exception = own_row is not None and own_row.flash_for is not None
        return OverviewEntry(
            full_name=ref.full_name,
            github_repo_id=github_repo_id,
            owner=owner_kind,
            owner_project=owner_project,
            in_project=in_project,
            selected=own_row is not None and own_row.selected,
            repository=own_row,
            exception_people=self.rules.people.get(own_row.id, []) if has_exception and own_row is not None else [],
            my_choice=choice,
            my_result=result,
        )

    def _in_view(self, entry: OverviewEntry, view: str) -> bool:
        if view == RepositoryOverviewView.IN_PROJECT:
            return entry.in_project
        if view == RepositoryOverviewView.EXCEPTIONS:
            return entry.repository is not None and entry.repository.flash_for is not None
        if view == RepositoryOverviewView.MINE:
            return entry.my_choice is not None
        return True

    def page(
        self, repositories: Sequence[Mapping[str, Any]], *, view: str, offset: int, limit: int
    ) -> tuple[list[OverviewEntry], int]:
        """One page of entries and the total that match the view."""
        if view == RepositoryOverviewView.ALL:
            return [self.entry(repository) for repository in repositories[offset : offset + limit]], len(repositories)
        matching = [
            entry for entry in (self.entry(repository) for repository in repositories) if self._in_view(entry, view)
        ]
        return matching[offset : offset + limit], len(matching)


class RepositoryChoices:
    """A person's own choices for repositories of one project. A choice stores only what differs."""

    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user

    def save(self, ref: RepositoryRef, mode: str) -> tuple[ReviewUserRepositoryChoice | None, AutomaticReviewDecision]:
        owner = RepositoryOwnership.find(ref)
        if owner is None or owner.team_id != self.team.id:
            raise RepositorySettingsError(f"This project does not review {ref.full_name}.")
        viewer = load_author_preferences(self.team.id, user_id=self.user.id, is_bot=False)
        rule = ProjectRuleContext.load(self.team.id, [owner.row] if owner.row is not None else []).rule_for(owner.row)
        existing = viewer.choice_for(ref)
        author = viewer.for_repository(ref)
        inherited = rule.resolve(replace(author, repository_choice=None))
        wants_flash = mode == ReviewUserRepositoryChoice.Mode.FLASH
        with transaction.atomic():
            if inherited.flash == wants_flash:
                # Equal to what the user inherits, so storing it would pin a value that only looks set.
                if existing is not None:
                    existing.delete()
                return None, inherited
            choices = ReviewUserRepositoryChoice.objects.for_team(self.team.id)
            if existing is None:
                existing = choices.create(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    installation_id=ref.installation_id,
                    github_repo_id=ref.github_repo_id,
                    full_name=ref.full_name,
                    mode=mode,
                )
            else:
                existing.mode = mode
                existing.full_name = ref.full_name
                existing.github_repo_id = existing.github_repo_id or ref.github_repo_id
                existing.save()
        decision = rule.resolve(replace(author, repository_choice=ReviewUserRepositoryChoice.Mode(mode)))
        return existing, decision
