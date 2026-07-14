from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core import signing

from rest_framework import status

from posthog.models.team import Team

from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.presentation.views import _INSTALL_STATE_SALT
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogTeamScopedTestMixin

_VIEWS = "products.stamphog.backend.presentation.views"
_CLIENT = "products.stamphog.backend.logic.github_client.StamphogGitHubClient"


def _install_state(team_id: int, user_id: int) -> str:
    """A signed install-flow state token, as install_info mints it, for use in sync_installation posts."""
    return signing.dumps({"team_id": team_id, "user_id": user_id}, salt=_INSTALL_STATE_SALT)


class TestStamphogRepoConfigAPI(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/stamphog/repo_configs/"

    def test_create_ignores_client_supplied_installation_id(self) -> None:
        # installation_id is read-only: a manual create must not let a caller claim an installation
        # they haven't proven ownership of. Only the verified sync_installation flow may set it.
        response = self.client.post(
            self.url,
            {"repository": "PostHog/posthog", "installation_id": "42"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["repository"] == "PostHog/posthog"
        assert body["enabled"] is True
        assert body["provider"] == "github"
        assert body["installation_id"] == ""
        config = StamphogRepoConfig.objects.unscoped().get(id=body["id"])
        assert config.team_id == self.team.id
        assert config.installation_id == ""

    def test_list_excludes_other_teams_configs(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        self.client.post(self.url, {"repository": "PostHog/posthog", "installation_id": "1"}, format="json")
        StamphogRepoConfig.objects.unscoped().create(
            team_id=other_team.id, repository="PostHog/other", installation_id="2"
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        repos = [row["repository"] for row in response.json()["results"]]
        assert repos == ["PostHog/posthog"]

    def test_cannot_retrieve_other_teams_config(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        theirs = StamphogRepoConfig.objects.unscoped().create(
            team_id=other_team.id, repository="PostHog/other", installation_id="2"
        )
        response = self.client.get(f"{self.url}{theirs.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_delete_other_teams_config(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        theirs = StamphogRepoConfig.objects.unscoped().create(
            team_id=other_team.id, repository="PostHog/other", installation_id="2"
        )
        response = self.client.delete(f"{self.url}{theirs.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert StamphogRepoConfig.objects.unscoped().filter(id=theirs.id).exists()


class TestReviewRunAPI(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/stamphog/review_runs/"
        self.repo_config = StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="1"
        )

    def _make_run(self, *, team=None, repo_config=None, pr_number: int = 1, status_value: str = "queued") -> ReviewRun:
        team = team or self.team
        repo_config = repo_config or self.repo_config
        pull_request, _ = PullRequest.objects.unscoped().update_or_create(
            team_id=team.id,
            repo_config=repo_config,
            pr_number=pr_number,
            defaults={"pr_url": f"https://github.com/{repo_config.repository}/pull/{pr_number}"},
        )
        return ReviewRun.objects.unscoped().create(
            team_id=team.id,
            pull_request=pull_request,
            head_sha="abc123",
            status=status_value,
        )

    def test_list_only_returns_own_team_runs(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        other_repo_config = StamphogRepoConfig.objects.unscoped().create(
            team_id=other_team.id, repository="PostHog/other", installation_id="2"
        )
        mine = self._make_run()
        self._make_run(team=other_team, repo_config=other_repo_config)

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(mine.id)]

    def test_filter_by_pr_number(self) -> None:
        self._make_run(pr_number=1)
        run_two = self._make_run(pr_number=2)

        response = self.client.get(self.url, {"pr_number": 2})
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(run_two.id)]

    def test_non_integer_pr_number_returns_empty_not_500(self) -> None:
        # pr_number flows into an integer ORM filter; a non-integer value used to raise and 500.
        # It's exposed via the API/MCP, so a bad value must degrade to an empty 200, not crash.
        self._make_run(pr_number=1)
        response = self.client.get(self.url, {"pr_number": "abc"})
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["results"] == []

    def test_filter_by_status(self) -> None:
        self._make_run(pr_number=1, status_value="completed")
        queued_run = self._make_run(pr_number=2, status_value="queued")

        response = self.client.get(self.url, {"status": "queued"})
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(queued_run.id)]

    def test_readonly_viewset_rejects_writes(self) -> None:
        # ReviewRun is created by the webhook/task pipeline, never directly
        # by API clients; the viewset must stay read-only.
        response = self.client.post(
            self.url,
            {"repository": "PostHog/posthog", "pr_number": 1, "pr_url": "x", "head_sha": "abc"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_output_excludes_raw_repo_content(self) -> None:
        # run.output holds the full PR payload, changed-file patches, default-branch policy files, and
        # raw reviewer stdout. A project member without repo access can read this endpoint, so the API
        # must expose only the allowlisted, content-free summary — never the raw repo content.
        run = self._make_run()
        run.output = {
            "reviewer_raw": "SECRET reviewer stdout with patches",
            "pr": {"title": "secret PR", "body": "internal"},
            "files": [{"filename": "app.py", "patch": "@@ secret diff @@"}],
            "policy_files": {".stamphog/policy.yml": "secret policy"},
            "stamphog_version": "test-1.0.0",
            "reviewer_exit_code": 0,
        }
        run.save(update_fields=["output"])

        response = self.client.get(f"{self.url}{run.id}/")
        assert response.status_code == status.HTTP_200_OK
        output = response.json()["output"]
        assert output == {"stamphog_version": "test-1.0.0", "reviewer_exit_code": 0}
        for leaked in ("reviewer_raw", "pr", "files", "policy_files"):
            assert leaked not in output


class TestSyncInstallationAPI(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/stamphog/repo_configs/sync_installation/"
        self.state = _install_state(self.team.id, self.user.id)

    @patch(f"{_CLIENT}.list_installation_repositories", return_value=["PostHog/posthog", "PostHog/other"])
    @patch(f"{_VIEWS}.user_can_access_installation", return_value=True)
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_verified_installation_binds_repos(self, mock_exchange, mock_verify, mock_list) -> None:
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        mock_exchange.assert_called_once_with("oauth-code")
        mock_verify.assert_called_once_with("42", "user-token")
        synced = sorted(row["repository"] for row in response.json()["synced"])
        assert synced == ["PostHog/other", "PostHog/posthog"]
        bound = StamphogRepoConfig.objects.unscoped().filter(team_id=self.team.id, installation_id="42")
        assert bound.count() == 2
        # Bind disabled: an install can surface hundreds of repos, so none starts reviewing until toggled.
        assert all(not config.enabled for config in bound)

    @patch(f"{_CLIENT}.list_installation_repositories", return_value=["PostHog/posthog"])
    @patch(f"{_VIEWS}.user_can_access_installation", return_value=True)
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_sync_adopts_preexisting_manual_config(self, mock_exchange, mock_verify, mock_list) -> None:
        # A repo onboarded through the plain create path carries a blank installation_id. When the same
        # team later syncs the verified installation, that row must be adopted (its installation stamped)
        # rather than reported skipped and left unbound forever.
        manual = StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="", enabled=True
        )
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [row["repository"] for row in response.json()["synced"]] == ["PostHog/posthog"]
        assert response.json()["skipped"] == []
        manual.refresh_from_db()
        assert manual.installation_id == "42"

    @patch(f"{_CLIENT}.list_installation_repositories")
    @patch(f"{_VIEWS}.user_can_access_installation", return_value=False)
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_installation_not_owned_by_caller_is_rejected(self, mock_exchange, mock_verify, mock_list) -> None:
        # Regression: without ownership verification, a caller who learns another org's installation_id
        # could bind its repos under their own team and hijack its webhooks. A verified-but-unowned
        # installation must be refused and bind nothing.
        response = self.client.post(
            self.url, {"installation_id": "999", "code": "oauth-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        mock_list.assert_not_called()
        assert not StamphogRepoConfig.objects.unscoped().filter(installation_id="999").exists()

    @patch(f"{_CLIENT}.list_installation_repositories")
    @patch(f"{_VIEWS}.user_can_access_installation")
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value=None)
    def test_unexchangeable_code_fails_closed(self, mock_exchange, mock_verify, mock_list) -> None:
        # A bad/expired code or unset OAuth creds yields no user token — fail closed with a 400 and bind
        # nothing, never fall through to the ownership check or the repo listing.
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "bad-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        mock_verify.assert_not_called()
        mock_list.assert_not_called()
        assert not StamphogRepoConfig.objects.unscoped().filter(installation_id="42").exists()

    @patch(f"{_CLIENT}.list_installation_repositories")
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token")
    def test_state_for_another_team_is_rejected(self, mock_exchange, mock_list) -> None:
        # CSRF guard: the callback binds an installation to the team named in the signed state, not the
        # team whose session posts it. A state minted for another team must be refused before any OAuth
        # exchange, so an attacker can't replay their own installation into a victim's project.
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        foreign_state = _install_state(other_team.id, self.user.id)
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": foreign_state}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        mock_exchange.assert_not_called()
        mock_list.assert_not_called()

    def test_invalid_state_is_rejected(self) -> None:
        # A tampered/garbage state token fails signature verification with a 400.
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": "not-a-real-token"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_missing_code_is_rejected(self) -> None:
        # code is the ownership proof — the endpoint must require it.
        response = self.client.post(self.url, {"installation_id": "42", "state": self.state}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
