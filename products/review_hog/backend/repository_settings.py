"""Writes and reads behind the repository settings API: claims, repository rows, personal choices.

The viewsets stay thin and call these classes. Every write keeps the ownership rules of
`ownership.py`: a repository has at most one row across projects, at most one project takes all
repositories of an installation, and a project only stores what differs from what it inherits.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from functools import cached_property
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models.integration import GitHubIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.activity_logging import log_repository_taken
from products.review_hog.backend.automatic_review_rules import (
    AuthorPreferences,
    ProjectRuleContext,
    load_author_preferences,
)
from products.review_hog.backend.facade.contracts import (
    UNSET,
    AutomaticReviewDecision,
    GitHubRepositoryListError,
    OwnershipConflict,
    PersonNotActiveMemberError,
    ProjectRef,
    RepositorySettingsError,
    Unset,
)
from products.review_hog.backend.facade.enums import AutomaticReviewReason, RepositoryOverviewView, RepositoryOwnerKind
from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserRepositoryChoice,
)
from products.review_hog.backend.ownership import RepositoryOwnership, RepositoryRef, find_matching_row, resolve_owner
from products.review_hog.backend.preferences import DefaultReviewMode

logger = logging.getLogger(__name__)


def load_project_ref(team_id: int, *, viewer_organization_id: Any) -> ProjectRef:
    """Another project, with its name only when it is in the viewer's organization."""
    return load_project_refs([team_id], viewer_organization_id=viewer_organization_id)[team_id]


def load_project_refs(team_ids: Iterable[int], *, viewer_organization_id: Any) -> dict[int, ProjectRef]:
    """Other projects in one query, each with its name only when it is in the viewer's organization."""
    ids = set(team_ids)
    teams = {team["id"]: team for team in Team.objects.filter(id__in=ids).values("id", "name", "organization_id")}
    refs: dict[int, ProjectRef] = {}
    for team_id in ids:
        team = teams.get(team_id, {})
        same_organization = team.get("organization_id") == viewer_organization_id
        refs[team_id] = ProjectRef(team_id=team_id, name=team.get("name") if same_organization else None)
    return refs


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
        return load_project_ref(team_id, viewer_organization_id=self.team.organization_id)

    def integrations(self) -> list[IntegrationRecord]:
        return IntegrationManager.github.oauth.list(self.team_id)

    def integration_for(self, installation_id: str) -> IntegrationRecord:
        integration = next((row for row in self.integrations() if row.integration_id == installation_id), None)
        if integration is None:
            raise RepositorySettingsError("This project has no GitHub connection for that installation.")
        return integration

    def installation_repositories(self, installation_id: str, search: str) -> Sequence[Mapping[str, Any]]:
        """The repositories the installation can see, from the cache, whose name contains `search`."""
        integration = self.integration_for(installation_id)
        try:
            repositories = GitHubIntegration(
                integration, source="review_hog", priority=Priority.NORMAL
            ).list_all_cached_repositories()
        except Exception:
            # The list refreshes from GitHub when the cache is cold, and GitHub can fail or rate limit.
            logger.warning("review_hog_repository_overview_list_failed", exc_info=True)
            raise GitHubRepositoryListError("GitHub did not return the repository list. Try again shortly.")
        search = search.strip().casefold()
        if search:
            repositories = [
                repository for repository in repositories if search in str(repository["full_name"]).casefold()
            ]
        return repositories

    def check_active_member(self, user_id: int) -> None:
        is_member = OrganizationMembership.objects.filter(
            organization_id=self.team.organization_id, user_id=user_id, user__is_active=True
        ).exists()
        if not is_member:
            raise PersonNotActiveMemberError("This user is not an active member of the organization.")

    def repositories(self) -> list[ReviewRepository]:
        return list(
            ReviewRepository.objects.for_team(self.team_id, canonical=True)
            .select_related("created_by")
            .order_by("created_at")
        )

    def repository(self, repository_id: UUID) -> ReviewRepository | None:
        return (
            ReviewRepository.objects.for_team(self.team_id, canonical=True)
            .select_related("created_by")
            .filter(id=repository_id)
            .first()
        )

    def delete_repository(self, repository_id: UUID) -> bool:
        """Delete one repository row and its lists. False when the project has no such row."""
        row = self.repository(repository_id)
        if row is None:
            return False
        row.delete()
        return True

    def claims(self) -> list[ReviewInstallationClaim]:
        return list(
            ReviewInstallationClaim.objects.for_team(self.team_id, canonical=True)
            .select_related("created_by")
            .order_by("created_at")
        )

    def claim(self, claim_id: UUID) -> ReviewInstallationClaim | None:
        return (
            ReviewInstallationClaim.objects.for_team(self.team_id, canonical=True)
            .select_related("created_by")
            .filter(id=claim_id)
            .first()
        )

    def verified_ref(self, ref: RepositoryRef) -> RepositoryRef:
        """The repository as the installation reports it. A client cannot store a pair GitHub does not know."""
        integration = self.integration_for(ref.installation_id)
        try:
            repositories = GitHubIntegration(
                integration, source="review_hog", priority=Priority.NORMAL
            ).list_all_cached_repositories()
        except Exception:
            # The list refreshes from GitHub when the cache is cold, and GitHub can fail or rate limit.
            logger.warning("review_hog_repository_write_list_failed", exc_info=True)
            raise RepositorySettingsError("GitHub did not return the repository list. Try again shortly.")
        for repository in repositories:
            github_repo_id = repository.get("id") if isinstance(repository.get("id"), int) else None
            full_name = str(repository.get("full_name") or "")
            if full_name.lower() != ref.full_name.lower():
                continue
            if ref.github_repo_id is not None and ref.github_repo_id != github_repo_id:
                continue
            return RepositoryRef(
                installation_id=ref.installation_id, github_repo_id=github_repo_id, full_name=full_name
            )
        raise RepositorySettingsError(f"The GitHub installation has no repository {ref.full_name} with that id.")

    def claim_for(self, installation_id: str) -> ReviewInstallationClaim | None:
        return ReviewInstallationClaim.objects.for_team(self.team_id).filter(installation_id=installation_id).first()

    def installations(self) -> list[InstallationSummary]:
        claims = {claim.installation_id: claim for claim in ReviewInstallationClaim.objects.for_team(self.team_id)}
        summaries: list[InstallationSummary] = []
        integrations = self.integrations()
        creators = User.objects.in_bulk({row.created_by_id for row in integrations if row.created_by_id})
        for integration in integrations:
            installation_id = integration.integration_id or ""
            all_claim = RepositoryOwnership.all_claim(installation_id)
            account = (integration.config or {}).get("account") or {}
            summaries.append(
                InstallationSummary(
                    installation_id=installation_id,
                    account_name=account.get("name") or installation_id,
                    connected_by=creators.get(integration.created_by_id) if integration.created_by_id else None,
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
        ref = self.verified_ref(ref)
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
            row.installation_id = ref.installation_id
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

    def remove_person(self, repository_id: UUID | None, person_id: UUID) -> bool:
        """Remove one entry from a list of the project rule (no repository) or of an exception.

        False when the list has no such entry.
        """
        people = ReviewRepositoryPerson.objects.for_team(self.team_id, canonical=True)
        if repository_id is None:
            people = people.filter(repository__isnull=True)
        else:
            people = people.filter(repository_id=repository_id)
        person = people.filter(id=person_id).first()
        if person is None:
            return False
        person.delete()
        return True


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
    inherited_result: AutomaticReviewDecision
    repository_result: AutomaticReviewDecision


class RepositoryOverview:
    """Every repository an installation can see, joined with this project's settings and the viewer's.

    The decision comes from the same resolver as the automatic dispatch, so the UI never re-implements it.
    """

    def __init__(self, team: Team, user: User, installation_id: str, repositories: Sequence[Mapping[str, Any]]) -> None:
        self.team = team
        self.user = user
        self.installation_id = installation_id
        self.repositories = repositories
        self.rows = RepositoryOwnership.rows_for_listing(
            (str(repository["full_name"]) for repository in repositories),
            (repository["id"] for repository in repositories if isinstance(repository.get("id"), int)),
        )
        self.all_claim = RepositoryOwnership.all_claim(installation_id)
        own_rows = [row for row in self.rows if row.team_id == team.id]
        self.rules = ProjectRuleContext.load(team.id, own_rows)
        self.viewer: AuthorPreferences = load_author_preferences(team.id, user_id=user.id, is_bot=False)
        # Some views compute every entry, so each lookup below must not scan all rows or query per owner.
        self._rows_by_id: dict[int, list[ReviewRepository]] = defaultdict(list)
        self._rows_by_name: dict[str, list[ReviewRepository]] = defaultdict(list)
        for row in self.rows:
            if row.github_repo_id is not None:
                self._rows_by_id[row.github_repo_id].append(row)
            self._rows_by_name[row.full_name.lower()].append(row)
        owner_team_ids = {row.team_id for row in self.rows}
        if self.all_claim is not None:
            owner_team_ids.add(self.all_claim.team_id)
        owner_team_ids.discard(team.id)
        self._projects = load_project_refs(owner_team_ids, viewer_organization_id=team.organization_id)

    def _candidate_rows(self, ref: RepositoryRef) -> list[ReviewRepository]:
        """The rows that can match `ref`. Id matches come first, which keeps the result of `find_matching_row`."""
        by_id = self._rows_by_id.get(ref.github_repo_id, []) if ref.github_repo_id is not None else []
        return by_id + self._rows_by_name.get(ref.full_name.lower(), [])

    def entry(self, repository: Mapping[str, Any]) -> OverviewEntry:
        github_repo_id = repository.get("id") if isinstance(repository.get("id"), int) else None
        ref = RepositoryRef(
            installation_id=self.installation_id, github_repo_id=github_repo_id, full_name=str(repository["full_name"])
        )
        rows = self._candidate_rows(ref)
        owner = resolve_owner(ref, rows, self.all_claim)
        own_row = find_matching_row(ref, [row for row in rows if row.team_id == self.team.id])
        in_project = owner is not None and owner.team_id == self.team.id
        choice = self.viewer.choice_for(ref)
        if in_project:
            rule = self.rules.rule_for(own_row)
            author = self.viewer.for_repository(ref)
            result = rule.resolve(author)
            inherited = rule.resolve(replace(author, repository_choice=None))
            repository_result = rule.resolve(
                replace(author, repository_choice=None, default_mode=DefaultReviewMode.FOLLOW)
            )
        else:
            result = AutomaticReviewDecision(flash=False, reason=AutomaticReviewReason.NOT_IN_PROJECT)
            inherited = result
            repository_result = result
        if owner is None:
            owner_kind, owner_project = RepositoryOwnerKind.NONE, None
        elif in_project:
            owner_kind, owner_project = RepositoryOwnerKind.THIS_PROJECT, None
        else:
            owner_kind, owner_project = RepositoryOwnerKind.OTHER_PROJECT, self._projects[owner.team_id]
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
            inherited_result=inherited,
            repository_result=repository_result,
        )

    def choices_unlike_default(self) -> int:
        """The viewer's repository choices, in any installation, that give something other than their default."""
        if self.viewer.default_mode == DefaultReviewMode.FOLLOW:
            return len(self.viewer.choices)
        return sum(1 for choice in self.viewer.choices if choice.mode != self.viewer.default_mode)

    @cached_property
    def all_entries(self) -> list[OverviewEntry]:
        # Every view except 'all' filters on computed entries, and the 'differs' view also counts the rest.
        return [self.entry(repository) for repository in self.repositories]

    @staticmethod
    def follows_project(entry: OverviewEntry) -> bool:
        """No exception and no own choice, so the entry gets exactly what every other such entry gets."""
        has_exception = entry.repository is not None and entry.repository.flash_for is not None
        return (
            entry.owner == RepositoryOwnerKind.THIS_PROJECT
            and entry.in_project
            and not has_exception
            and entry.my_choice is None
        )

    def folded(self) -> list[OverviewEntry]:
        """The entries the 'differs' view leaves out."""
        return [entry for entry in self.all_entries if self.follows_project(entry)]

    def _in_view(self, entry: OverviewEntry, view: str) -> bool:
        if view == RepositoryOverviewView.DIFFERS:
            return not self.follows_project(entry)
        if view == RepositoryOverviewView.IN_PROJECT:
            return entry.in_project
        if view == RepositoryOverviewView.EXCEPTIONS:
            return entry.repository is not None and entry.repository.flash_for is not None
        if view == RepositoryOverviewView.MINE:
            return entry.my_choice is not None
        return True

    def page(self, *, view: str, offset: int, limit: int) -> tuple[list[OverviewEntry], int]:
        """One page of entries and the total that match the view."""
        if view == RepositoryOverviewView.ALL:
            page = self.repositories[offset : offset + limit]
            return [self.entry(repository) for repository in page], len(self.repositories)
        matching = [entry for entry in self.all_entries if self._in_view(entry, view)]
        return matching[offset : offset + limit], len(matching)


class RepositoryChoices:
    """A person's own choices for repositories of one project. A choice stores only what differs."""

    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user

    def choices(self) -> list[ReviewUserRepositoryChoice]:
        return list(
            ReviewUserRepositoryChoice.objects.for_team(self.team.id, canonical=True)
            .filter(user_id=self.user.id)
            .order_by("full_name")
        )

    def delete(self, choice_id: UUID) -> bool:
        """Clear one of the person's choices. False when the person has no such choice."""
        choice = (
            ReviewUserRepositoryChoice.objects.for_team(self.team.id, canonical=True)
            .filter(user_id=self.user.id, id=choice_id)
            .first()
        )
        if choice is None:
            return False
        choice.delete()
        return True

    def save(self, ref: RepositoryRef, mode: str) -> tuple[ReviewUserRepositoryChoice | None, AutomaticReviewDecision]:
        ProjectRepositories(self.team, self.user).integration_for(ref.installation_id)
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
                existing.installation_id = ref.installation_id
                existing.full_name = ref.full_name
                existing.github_repo_id = existing.github_repo_id or ref.github_repo_id
                existing.save()
        decision = rule.resolve(replace(author, repository_choice=ReviewUserRepositoryChoice.Mode(mode)))
        return existing, decision
