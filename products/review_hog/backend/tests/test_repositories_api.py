from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewRepository,
    ReviewUserRepositoryChoice,
    ReviewUserSettings,
)
from products.review_hog.backend.temporal.client import WorkflowProbe

INSTALLATION = "1001"
WEB = {"installation_id": INSTALLATION, "full_name": "example-org/web", "github_repo_id": 501}
CACHED_REPOSITORIES = [
    {"id": 501, "name": "web", "full_name": "example-org/web"},
    {"id": 502, "name": "api", "full_name": "example-org/api"},
    {"id": 503, "name": "docs", "full_name": "example-org/docs"},
]

ADMIN_WRITES = [
    ("project_settings/", "patch", {"flash_for": "everyone"}),
    ("installation_claims/", "post", {"installation_id": INSTALLATION, "scope": "all"}),
    ("repositories/", "post", {**WEB, "selected": True}),
]


class TestReviewRepositorySettingsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.enterContext(
            patch(
                "posthog.models.integration.GitHubIntegration.list_all_cached_repositories",
                return_value=CACHED_REPOSITORIES,
            )
        )
        self._set_level(OrganizationMembership.Level.ADMIN)
        self.other_team = Team.objects.create(organization=self.organization, name="Other project")
        for team in (self.team, self.other_team):
            Integration.objects.create(
                team=team,
                kind="github",
                integration_id=INSTALLATION,
                config={"account": {"name": "example-org"}},
                created_by=self.user,
            )

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(level=level)

    def _url(self, path: str, team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/review_hog/{path}"

    def _claim(self, team: Team, scope: str) -> ReviewInstallationClaim:
        return ReviewInstallationClaim.objects.for_team(team.id).create(
            team=team, installation_id=INSTALLATION, scope=scope
        )

    @parameterized.expand(ADMIN_WRITES)
    def test_members_read_but_only_admins_change_project_settings(self, path: str, method: str, body: dict) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)

        assert self.client.get(self._url(path)).status_code == 200
        assert getattr(self.client, method)(self._url(path), body, format="json").status_code == 403

        self._set_level(OrganizationMembership.Level.ADMIN)

        assert getattr(self.client, method)(self._url(path), body, format="json").status_code in (200, 201)

    @parameterized.expand(ADMIN_WRITES)
    def test_admin_of_an_environment_cannot_change_the_parent_project(self, path: str, method: str, body: dict) -> None:
        self._set_level(OrganizationMembership.Level.MEMBER)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        AccessControl.objects.create(
            team=environment,
            resource="project",
            resource_id=str(environment.id),
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=self.user),
            access_level="admin",
        )

        res = getattr(self.client, method)(self._url(path, environment), body, format="json")

        assert res.status_code == 403, res.json()
        assert self.client.get(self._url(path, environment)).status_code == 200

    @parameterized.expand(
        [
            ("environment_only", False, (403, 403, 403, 403)),
            ("environment_and_parent", True, (200, 200, 200, 200)),
        ]
    )
    @patch("products.review_hog.backend.pr_status.probe_workflow", return_value=WorkflowProbe.NOT_RUNNING)
    def test_a_project_scoped_key_needs_the_parent_project(
        self, _name: str, include_parent: bool, expected: tuple[int, int, int, int], _probe: MagicMock
    ) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Scoped",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=["*"],
            scoped_teams=[environment.id, self.team.id] if include_parent else [environment.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {value}")

        read = self.client.get(self._url("repositories/", environment))
        write = self.client.post(self._url("repositories/", environment), {**WEB, "selected": True})
        reviews = self.client.get(self._url("reviews/", environment))
        pr_status = self.client.get(
            self._url("reviews/pr_status/", environment), {"pr_url": "https://github.com/PostHog/posthog/pull/5"}
        )

        assert (read.status_code, write.status_code, reviews.status_code, pr_status.status_code) == expected

    def test_project_rule_stores_only_what_differs_and_is_logged(self) -> None:
        res = self.client.patch(
            self._url("project_settings/"),
            {"flash_for": "listed", "bot_prs": "run", "urgency_threshold": "must_fix", "celebrate_clean_reviews": True},
            format="json",
        )

        assert res.status_code == 200, res.json()
        assert res.json()["urgency_threshold"] == "must_fix"
        assert res.json()["can_edit"] is True
        assert [installation["account_name"] for installation in res.json()["installations"]] == ["example-org"]
        row = ReviewProjectSettings.objects.for_team(self.team.id).get()
        assert (row.flash_for, row.bot_prs, row.preferences) == ("listed", "run", {"urgency_threshold": "must_fix"})

        added = self.client.post(
            self._url("project_settings/people/"), {"user_id": self.user.id, "kind": "listed"}, format="json"
        )
        assert added.status_code == 201, added.json()
        person_id = added.json()["people"][0]["id"]
        assert self.client.delete(self._url(f"project_settings/people/{person_id}/")).status_code == 200

        logged = ActivityLog.objects.filter(team_id=self.team.id, scope="ReviewProjectSettings", item_id=str(row.id))
        fields = [change["field"] for entry in logged for change in (entry.detail or {}).get("changes") or []]
        assert {"flash_for", "bot_prs", "listed_people"} <= set(fields)

    def test_selecting_a_repository_takes_it_from_the_project_that_claims_all(self) -> None:
        self._claim(self.other_team, ReviewInstallationClaim.Scope.ALL)

        res = self.client.post(self._url("repositories/"), {**WEB, "selected": True}, format="json")

        assert res.status_code == 200, res.json()
        assert res.json()["taken_from_project"] == {"id": self.other_team.id, "name": "Other project"}
        assert res.json()["repository"]["selected"] is True
        # The first selection also claims the installation for "only selected repositories".
        assert ReviewInstallationClaim.objects.for_team(self.team.id).get().scope == "selected"
        taken = ActivityLog.objects.filter(
            team_id=self.other_team.id, scope="ReviewInstallationClaim", activity="updated"
        ).first()
        assert taken is not None and taken.detail is not None
        assert taken.detail["changes"][0]["before"] == "example-org/web"

        # The repository now has a row in this project, so the other project cannot take it back.
        conflict = self.client.post(
            self._url("repositories/", self.other_team), {**WEB, "flash_for": "everyone"}, format="json"
        )

        assert conflict.status_code == 409
        assert conflict.json()["conflicting_project"]["id"] == self.team.id

    def test_a_repository_row_from_an_earlier_installation_still_owns_the_repository(self) -> None:
        # A reinstall of the GitHub App gives the same repositories a new installation id. The row of
        # the earlier installation must still block another project, or the repository gets two owners.
        ReviewRepository.objects.for_team(self.other_team.id).create(
            team=self.other_team, installation_id="1000", github_repo_id=501, full_name="example-org/web", selected=True
        )

        res = self.client.post(self._url("repositories/"), {**WEB, "selected": True}, format="json")

        assert res.status_code == 409, res.json()
        assert res.json()["conflicting_project"]["id"] == self.other_team.id

    def test_only_one_project_can_claim_all_repositories(self) -> None:
        self._claim(self.other_team, ReviewInstallationClaim.Scope.ALL)

        res = self.client.post(
            self._url("installation_claims/"), {"installation_id": INSTALLATION, "scope": "all"}, format="json"
        )

        assert res.status_code == 409
        assert res.json()["conflicting_project"] == {"id": self.other_team.id, "name": "Other project"}

    def test_projects_of_other_organizations_stay_unnamed(self) -> None:
        stranger_team = Team.objects.create(organization=Organization.objects.create(name="other"), name="Secret")
        self._claim(stranger_team, ReviewInstallationClaim.Scope.ALL)

        res = self.client.post(
            self._url("installation_claims/"), {"installation_id": INSTALLATION, "scope": "all"}, format="json"
        )

        assert res.status_code == 409
        assert res.json()["conflicting_project"] == {"id": None, "name": None}
        assert "Secret" not in res.json()["error"]

        taken = self.client.post(self._url("repositories/"), {**WEB, "selected": True}, format="json")

        assert taken.status_code == 200, taken.json()
        logged = ActivityLog.objects.get(team_id=stranger_team.id, scope="ReviewInstallationClaim", activity="updated")
        assert logged.user is None
        assert logged.detail is not None
        assert logged.detail["changes"][0]["after"] == "A project in another organization"

    def test_switching_to_selected_removes_the_exceptions_of_repositories_that_leave(self) -> None:
        claim = self._claim(self.team, ReviewInstallationClaim.Scope.ALL)
        for body in (
            {**WEB, "flash_for": "off"},
            {**WEB, "full_name": "example-org/api", "github_repo_id": 502, "selected": True},
        ):
            assert self.client.post(self._url("repositories/"), body, format="json").status_code == 200

        res = self.client.patch(self._url(f"installation_claims/{claim.id}/"), {"scope": "selected"}, format="json")

        assert res.status_code == 200, res.json()
        remaining = ReviewRepository.objects.for_team(self.team.id).values_list("full_name", flat=True)
        assert list(remaining) == ["example-org/api"]

    @parameterized.expand(
        [
            ("exception_without_ownership", {**WEB, "flash_for": "everyone"}, 400),
            ("nothing_to_store", {**WEB, "selected": False}, 200),
            ("unknown_to_the_installation", {**WEB, "full_name": "example-org/secret", "selected": True}, 400),
            ("id_of_another_repository", {**WEB, "github_repo_id": 502, "selected": True}, 400),
            (
                "reserve_another_repositorys_id",
                {**WEB, "full_name": "example-org/not-yet-created", "github_repo_id": 503, "flash_for": "off"},
                400,
            ),
        ]
    )
    def test_repository_writes_keep_rows_meaningful(self, _name: str, body: dict, expected_status: int) -> None:
        self._claim(self.team, ReviewInstallationClaim.Scope.SELECTED)

        res = self.client.post(self._url("repositories/"), body, format="json")

        assert res.status_code == expected_status, res.json()
        assert not ReviewRepository.objects.for_team(self.team.id).exists()

    def test_a_choice_equal_to_the_inherited_value_is_not_stored(self) -> None:
        self._claim(self.team, ReviewInstallationClaim.Scope.ALL)
        url = self._url("repository_choices/")

        flash = self.client.post(url, {**WEB, "mode": "flash"}, format="json")

        assert flash.status_code == 200, flash.json()
        assert flash.json()["my_result"] == {"flash": True, "reason": "own_repository_choice"}
        assert flash.json()["choice"]["mode"] == "flash"

        # The project rule is opt-in only, so "off" is what the user inherits: the choice clears.
        off = self.client.post(url, {**WEB, "mode": "off"}, format="json")

        assert off.json() == {"choice": None, "my_result": {"flash": False, "reason": "project_opt_in"}}
        assert not ReviewUserRepositoryChoice.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            ("no_project_reviews_it", None, {}),
            ("rename_through_a_known_id", 501, {"full_name": "example-org/zzz"}),
            ("store_an_unknown_id", None, {"github_repo_id": 777}),
        ]
    )
    def test_choices_need_a_repository_this_project_reviews(
        self, _name: str, other_row_repo_id: int | None, overrides: dict
    ) -> None:
        other_row = None
        if overrides:
            self._claim(self.other_team, ReviewInstallationClaim.Scope.SELECTED)
            other_row = ReviewRepository.objects.for_team(self.other_team.id).create(
                team=self.other_team,
                installation_id=INSTALLATION,
                github_repo_id=other_row_repo_id,
                full_name="example-org/web",
                selected=True,
            )

        res = self.client.post(self._url("repository_choices/"), {**WEB, **overrides, "mode": "flash"}, format="json")

        assert res.status_code == 400
        if other_row is not None:
            stored = ReviewRepository.objects.for_team(self.other_team.id).get(id=other_row.id)
            assert (stored.full_name, stored.github_repo_id) == ("example-org/web", other_row_repo_id)

    @patch(
        "posthog.models.integration.GitHubIntegration.list_all_cached_repositories", return_value=CACHED_REPOSITORIES
    )
    def test_overview_joins_the_cached_list_with_ownership_and_my_result(self, _cached: object) -> None:
        self._claim(self.team, ReviewInstallationClaim.Scope.ALL)
        self._claim(self.other_team, ReviewInstallationClaim.Scope.SELECTED)
        # Stored before a reinstall of the GitHub App, so under an earlier installation id.
        ReviewRepository.objects.for_team(self.other_team.id).create(
            team=self.other_team, installation_id="1000", full_name="example-org/api", selected=True
        )
        ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, installation_id=INSTALLATION, full_name="example-org/docs", flash_for="everyone"
        )
        ReviewUserRepositoryChoice.objects.for_team(self.team.id).create(
            team=self.team, user=self.user, installation_id=INSTALLATION, full_name="example-org/docs", mode="off"
        )
        ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, preferences={"default_review_mode": "flash"}
        )
        url = self._url(f"repository_overview/?installation_id={INSTALLATION}")

        everything = self.client.get(url)

        assert everything.status_code == 200, everything.json()
        assert everything.json()["claim_scope"] == "all"
        # The one choice, "off" on docs, differs from the "flash" default.
        assert everything.json()["my_choices_unlike_default"] == 1
        entries = {entry["full_name"]: entry for entry in everything.json()["results"]}
        assert entries["example-org/web"]["owner"] == "this_project"
        assert entries["example-org/web"]["my_result"] == {"flash": True, "reason": "own_default"}
        assert entries["example-org/web"]["repository_result"] == {"flash": False, "reason": "project_opt_in"}
        assert entries["example-org/api"]["owner"] == "other_project"
        assert entries["example-org/api"]["owner_project"] == {"id": self.other_team.id, "name": "Other project"}
        assert entries["example-org/api"]["my_result"] == {"flash": False, "reason": "not_in_project"}
        assert entries["example-org/docs"]["exception"]["flash_for"] == "everyone"
        assert entries["example-org/docs"]["my_result"] == {"flash": False, "reason": "own_repository_choice"}
        assert entries["example-org/docs"]["inherited_result"] == {"flash": True, "reason": "own_default"}
        assert entries["example-org/docs"]["repository_result"] == {"flash": True, "reason": "repository_everyone"}

        exceptions = self.client.get(f"{url}&view=exceptions").json()
        assert [entry["full_name"] for entry in exceptions["results"]] == ["example-org/docs"]
        page = self.client.get(f"{url}&view=in_project&limit=1").json()
        assert (page["total"], page["has_more"], page["next_offset"]) == (2, True, 1)
        searched = self.client.get(f"{url}&search=API").json()
        assert [entry["full_name"] for entry in searched["results"]] == ["example-org/api"]

    def test_overview_needs_a_connected_installation(self) -> None:
        res = self.client.get(self._url("repository_overview/?installation_id=9999"))

        assert res.status_code == 400

    def test_settings_of_another_project_are_invisible(self) -> None:
        other = ReviewRepository.objects.for_team(self.other_team.id).create(
            team=self.other_team, installation_id=INSTALLATION, full_name="example-org/web", selected=True
        )

        listed = self.client.get(self._url("repositories/"))
        removed = self.client.delete(self._url(f"repositories/{other.id}/"))

        assert listed.json() == []
        assert removed.status_code == 404
        assert ReviewRepository.objects.for_team(self.other_team.id).filter(id=other.id).exists()

    def test_people_must_be_active_members(self) -> None:
        outsider = User.objects.create_and_join(Organization.objects.create(name="other"), "out@example.com", None)

        res = self.client.post(
            self._url("project_settings/people/"), {"user_id": outsider.id, "kind": "listed"}, format="json"
        )

        assert res.status_code == 400
