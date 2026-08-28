from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, uuid7

from products.stamphog.backend.facade import contracts
from products.stamphog.backend.facade.enums import ChannelResolutionSource, DigestRunStatus, ReviewMode, ReviewRunStatus
from products.stamphog.backend.models import DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.presentation.serializers import StamphogRepoConfigWriteSerializer
from products.stamphog.backend.presentation.views import _INSTALL_STATE_SALT
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, StamphogTeamScopedTestMixin

_VIEWS = "products.stamphog.backend.presentation.views"
# The repo enumeration moved behind the facade with the sync logic; the rest is still looked up in views.
_GITHUB_FACADE = "products.stamphog.backend.facade.github"
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

    def test_update_cannot_change_identity_fields(self) -> None:
        # provider + repository anchor webhook resolution and every PR/ReviewRun FK. A PATCH that
        # changed them would reroute the config's history and orphan the original repo's webhooks, so
        # they're create-only: the values are ignored on update while enabled still toggles.
        created = self.client.post(self.url, {"repository": "PostHog/posthog", "enabled": True}, format="json").json()
        response = self.client.patch(
            f"{self.url}{created['id']}/",
            {"repository": "PostHog/evil", "provider": "gitlab", "enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["repository"] == "PostHog/posthog"
        assert body["provider"] == "github"
        assert body["enabled"] is False

    def test_blank_installation_does_not_reserve_repo_across_teams(self) -> None:
        # A manual placeholder carries a blank installation and proves no ownership, so it must not
        # globally reserve a repo. Two teams can each hold their own unsynced placeholder for the same
        # repository; only a real synced installation is exclusive (partial unique constraint).
        self.client.post(self.url, {"repository": "PostHog/posthog"}, format="json")
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        StamphogRepoConfig.objects.unscoped().create(
            team_id=other_team.id, repository="PostHog/posthog", installation_id=""
        )
        both = StamphogRepoConfig.objects.unscoped().filter(repository="PostHog/posthog", installation_id="")
        assert both.count() == 2

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

    def test_environment_url_reads_canonical_parent_rows(self) -> None:
        # With a child environment id in the URL, reads must resolve to the canonical (parent) team.
        # ProductTeamModel.save() writes rows at the parent id, so scoping the list by the raw child id
        # would miss them. The viewset canonicalizes self.team_id, so the parent's config still lists.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="7"
        )

        response = self.client.get(f"/api/projects/{env.id}/stamphog/repo_configs/")

        assert response.status_code == status.HTTP_200_OK, response.content
        repos = [row["repository"] for row in response.json()["results"]]
        assert repos == ["PostHog/posthog"]

    def test_child_scoped_api_key_cannot_reach_parent_rows(self) -> None:
        # stamphog rows canonicalize to the parent team, so a request through the child environment
        # reads the PARENT's data. A token scoped only to the child passes the default scope check
        # (URL team == child) but must not reach the parent's rows through it.
        env = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="8"
        )
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child-scoped",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["stamphog:read"],
            scoped_teams=[env.id],
        )
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{env.id}/stamphog/repo_configs/", HTTP_AUTHORIZATION=f"Bearer {key_value}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

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

    def test_delete_soft_disables_as_tombstone(self) -> None:
        # A hard delete would cascade away the PRs and review runs (including posted_review_id), so a
        # push to a previously approved PR could no longer resolve the config or dismiss the stale
        # approval — deleting a repo must not launder a standing approval. In-flight runs are
        # superseded too: their workflows never re-check enabled and could still post an approval.
        mine = StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/mine", installation_id="3", enabled=True, digest_enabled=True
        )
        pull_request = PullRequest.objects.unscoped().create(
            team_id=self.team.id, repo_config=mine, pr_number=9, author_login="dev"
        )
        in_flight = ReviewRun.objects.unscoped().create(
            team_id=self.team.id, pull_request=pull_request, head_sha="sha-live", status=ReviewRunStatus.REVIEWING
        )
        response = self.client.delete(f"{self.url}{mine.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
        mine.refresh_from_db()
        in_flight.refresh_from_db()
        assert mine.enabled is False
        assert mine.digest_enabled is False
        assert in_flight.status == ReviewRunStatus.SUPERSEDED

    def test_cannot_enable_digest_without_reviews(self) -> None:
        # Wiring guard for the serializer matrix below: the viewset must actually reject the
        # combination. A digest-on/review-off repo captures no merges at all, so it would look
        # configured and silently never post.
        response = self.client.post(self.url, {"repository": "PostHog/quiet", "enabled": False, "digest_enabled": True})
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert not StamphogRepoConfig.objects.unscoped().filter(repository="PostHog/quiet").exists()


def _repo_config_dto(*, enabled: bool, digest_enabled: bool) -> contracts.RepoConfigDTO:
    return contracts.RepoConfigDTO(
        id=uuid7(),
        team_id=1,
        provider="github",
        repository="PostHog/posthog",
        enabled=enabled,
        installation_id="1",
        digest_enabled=digest_enabled,
    )


class TestStamphogRepoConfigSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("create", None, {"repository": "PostHog/posthog", "enabled": False, "digest_enabled": True}),
            (
                "enable_digest_on_review_off_repo",
                _repo_config_dto(enabled=False, digest_enabled=False),
                {"digest_enabled": True},
            ),
        ]
    )
    def test_asking_for_digest_without_reviews_is_rejected(
        self, _name: str, current: contracts.RepoConfigDTO | None, data: dict
    ) -> None:
        serializer = StamphogRepoConfigWriteSerializer(
            data=data, partial=current is not None, partial_update=current is not None, current=current
        )
        assert not serializer.is_valid()
        assert "digest_enabled" in serializer.errors

    def test_disabling_reviews_clears_the_digest(self) -> None:
        # The Enabled toggle PATCHes only `enabled`, so rejecting the write would leave an admin
        # unable to turn reviews off on any digest-enabled repo, with a generic failure toast.
        serializer = StamphogRepoConfigWriteSerializer(
            data={"enabled": False},
            partial=True,
            partial_update=True,
            current=_repo_config_dto(enabled=True, digest_enabled=True),
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["digest_enabled"] is False


class TestReviewRunAPI(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/stamphog/review_runs/"
        self.repo_config = StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="1"
        )

    def _make_run(
        self,
        *,
        team=None,
        repo_config=None,
        pr_number: int = 1,
        status_value: str = "queued",
        output: dict | None = None,
    ) -> ReviewRun:
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
            output=output or {},
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

    @parameterized.expand(
        [
            # Inbox provenance outranks the repo mode: a self-driving run is dispatched from the inbox
            # whether or not the repo also reviews every PR event.
            ("self_driving_beats_all_mode", ReviewMode.ALL, {"inbox_review": {"trigger": "inbox"}}, "self_driving"),
            ("self_driving_beats_label_mode", ReviewMode.LABEL, {"inbox_review": {"trigger": "inbox"}}, "self_driving"),
            ("label_mode", ReviewMode.LABEL, {}, "label"),
            ("all_mode", ReviewMode.ALL, {}, "all"),
        ]
    )
    def test_trigger_is_derived_and_filterable(
        self, _name: str, review_mode: ReviewMode, output: dict, expected: str
    ) -> None:
        # The facade derives `trigger` in Python and filters on it in SQL through two separate code
        # paths. They must agree: a run that reads as self-driving in the list has to be reachable by
        # the self-driving filter, or the filter quietly hides rows the table just showed.
        self.repo_config.review_mode = review_mode
        self.repo_config.save(update_fields=["review_mode"])
        run = self._make_run(output=output)

        listed = self.client.get(self.url)
        assert listed.status_code == status.HTTP_200_OK, listed.content
        assert [row["trigger"] for row in listed.json()["results"]] == [expected]

        filtered = self.client.get(self.url, {"trigger": expected})
        assert filtered.status_code == status.HTTP_200_OK, filtered.content
        assert [row["id"] for row in filtered.json()["results"]] == [str(run.id)]

    def test_unknown_trigger_returns_empty_not_everything(self) -> None:
        # The filter is exposed via API/MCP. An unrecognized value must narrow to nothing rather than
        # fall through and hand back the unfiltered list as if the filter had applied.
        self._make_run()
        response = self.client.get(self.url, {"trigger": "not-a-trigger"})
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["results"] == []

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

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories", return_value=["PostHog/posthog", "PostHog/other"])
    @patch(f"{_VIEWS}.user_can_access_installation", return_value=True)
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_verified_installation_binds_repos(self, mock_exchange, mock_verify, mock_list) -> None:
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        mock_exchange.assert_called_once_with("oauth-code")
        mock_verify.assert_called_once_with("42", "user-token")
        # The explicit-id path never discovers, so app_not_installed is always false there.
        assert response.json()["app_not_installed"] is False
        synced = sorted(row["repository"] for row in response.json()["synced"])
        assert synced == ["PostHog/other", "PostHog/posthog"]
        bound = StamphogRepoConfig.objects.unscoped().filter(team_id=self.team.id, installation_id="42")
        assert bound.count() == 2
        # Bind disabled: an install can surface hundreds of repos, so none starts reviewing until toggled.
        assert all(not config.enabled for config in bound)
        # The caller becomes the connecting user — the identity review-sandbox credentials are minted under.
        assert all(config.connected_by_user_id == self.user.id for config in bound)

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories", return_value=["PostHog/posthog"])
    @patch(f"{_VIEWS}.user_can_access_installation", return_value=True)
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_sync_adopts_preexisting_manual_config(self, mock_exchange, mock_verify, mock_list) -> None:
        # A repo onboarded through the plain create path carries a blank installation_id. When the same
        # team later syncs the verified installation, that row must be adopted (its installation stamped)
        # rather than reported skipped and left unbound forever — but adopted DISABLED: the placeholder's
        # flags were set by someone who never proved GitHub access, so a member could otherwise pre-arm
        # enabled=True for a private repo and have reviews start the moment a teammate installs.
        manual = StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="", enabled=True, digest_enabled=True
        )
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [row["repository"] for row in response.json()["synced"]] == ["PostHog/posthog"]
        assert response.json()["skipped"] == []
        manual.refresh_from_db()
        assert manual.installation_id == "42"
        assert manual.connected_by_user_id == self.user.id
        assert manual.enabled is False
        assert manual.digest_enabled is False

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories", return_value=["PostHog/posthog"])
    @patch(f"{_VIEWS}.user_can_access_installation", return_value=True)
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_sync_rebinds_repo_after_reinstall(self, mock_exchange, mock_verify, mock_list) -> None:
        # An uninstall/reinstall cycle mints a new installation id; the old binding is dead (the app
        # can only be installed once per repo). Re-syncing the verified new installation must rebind
        # the team's existing row instead of skipping it and leaving the repo dead forever.
        stale = StamphogRepoConfig.objects.unscoped().create(
            team_id=self.team.id, repository="PostHog/posthog", installation_id="41", enabled=True
        )
        response = self.client.post(
            self.url, {"installation_id": "42", "code": "oauth-code", "state": self.state}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [row["repository"] for row in response.json()["synced"]] == ["PostHog/posthog"]
        stale.refresh_from_db()
        assert stale.installation_id == "42"
        assert stale.enabled is True  # settings survive the rebind

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories")
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

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories")
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

    @parameterized.expand(["team", "user"])
    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories")
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token")
    def test_state_for_another_team_or_user_is_rejected(self, mismatch, mock_exchange, mock_list) -> None:
        # CSRF guard: the callback binds an installation to the team AND the member named in the signed
        # state, not whoever's session posts it. A state minted for another team lets an attacker replay
        # their own installation into a victim's project; a state minted for another member lets one
        # project member complete another member's install under the second member's session. Both must
        # be refused before any OAuth exchange.
        if mismatch == "team":
            other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
            foreign_state = _install_state(other_team.id, self.user.id)
        else:
            foreign_state = _install_state(self.team.id, self.user.pk + 1)
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

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories", return_value=["PostHog/posthog"])
    @patch(f"{_VIEWS}.list_user_installations", return_value=[{"id": "42", "account_login": "PostHog"}])
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_discovery_without_installation_id_syncs_discovered_installation(
        self, mock_exchange, mock_discover, mock_list
    ) -> None:
        # Authorize-first: the callback carries no installation_id. The backend discovers the caller's
        # installations from the OAuth code (GitHub returns only installations of this App the user can
        # reach) and syncs them, so the client never has to supply a forgeable id.
        response = self.client.post(self.url, {"code": "oauth-code", "state": self.state}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        mock_discover.assert_called_once_with("user-token")
        body = response.json()
        assert [row["repository"] for row in body["synced"]] == ["PostHog/posthog"]
        assert body["app_not_installed"] is False
        assert body["installations"] == []
        bound = StamphogRepoConfig.objects.unscoped().filter(team_id=self.team.id, installation_id="42")
        assert bound.count() == 1

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories")
    @patch(
        f"{_VIEWS}.list_user_installations",
        return_value=[{"id": "100", "account_login": "AlphaOrg"}, {"id": "200", "account_login": "SharedOrg"}],
    )
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_discovery_with_several_installations_binds_nothing_and_returns_choices(
        self, mock_exchange, mock_discover, mock_list
    ) -> None:
        # Reachability is not intent: a user in several orgs that all carry the App must pick which
        # installation this team binds. Binding them all would attach foreign orgs' repos here and, via
        # the oldest-wins webhook resolution, could blackhole another team's future connect.
        response = self.client.post(self.url, {"code": "oauth-code", "state": self.state}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["synced"] == []
        assert body["skipped"] == []
        assert body["app_not_installed"] is False
        assert body["installations"] == [
            {"id": "100", "account_login": "AlphaOrg"},
            {"id": "200", "account_login": "SharedOrg"},
        ]
        mock_list.assert_not_called()
        assert not StamphogRepoConfig.objects.unscoped().filter(team_id=self.team.id).exists()

    @patch(f"{_GITHUB_FACADE}.list_user_accessible_repositories")
    @patch(f"{_VIEWS}.list_user_installations", return_value=[])
    @patch(f"{_VIEWS}.exchange_oauth_code_for_user_token", return_value="user-token")
    def test_discovery_with_no_installations_reports_app_not_installed(
        self, mock_exchange, mock_discover, mock_list
    ) -> None:
        # Discovery reached no installation the user can see: the App isn't installed anywhere for them.
        # Not an error — return app_not_installed so the frontend routes them to the install page, binding
        # nothing and never touching the repo-enumeration path.
        response = self.client.post(self.url, {"code": "oauth-code", "state": self.state}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["app_not_installed"] is True
        assert body["synced"] == []
        assert body["skipped"] == []
        mock_list.assert_not_called()
        assert not StamphogRepoConfig.objects.unscoped().filter(team_id=self.team.id).exists()


class TestDigestRunAPI(StamphogTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def test_a_run_reports_where_its_digest_went(self) -> None:
        # The run is the only record of a digest's destination now that routing is derived per run
        # rather than stored on a channel row. Losing these fields leaves "why did my digest go
        # there" unanswerable from anywhere but a worker log.
        for channel_id, audience in (("C1", "team-x"), ("C2", "team-y")):
            DigestRun.objects.unscoped().create(
                team_id=self.team.id,
                audience_key=audience,
                slack_channel_id=channel_id,
                # Stored bare, the way _match records it. The "#" belongs to display only.
                slack_channel_name=audience,
                resolution_source=ChannelResolutionSource.OWNERS_CONTACT,
                status=DigestRunStatus.COMPLETED,
            )

        url = f"/api/projects/{self.team.id}/stamphog/digest_runs/"
        body = self.client.get(url).json()
        assert {r["slack_channel_id"] for r in body["results"]} == {"C1", "C2"}
        assert {r["audience_key"] for r in body["results"]} == {"team-x", "team-y"}
        assert {r["resolution_source"] for r in body["results"]} == {"owners_contact"}

        filtered = self.client.get(f"{url}?slack_channel_id=C1").json()
        assert [r["audience_key"] for r in filtered["results"]] == ["team-x"]
