from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import Integration
from posthog.ownership.github_files import AuthenticatedRepoFiles, GitHubFilesFetcher
from posthog.ownership.repo_files import GitHubRepoFiles

from products.engineering_analytics.backend.logic.ownership_files import repo_files
from products.warehouse_sources.backend.facade.contracts import GitHubSourceCredential

_REPOSITORY = "PostHog/posthog"
_CREDENTIAL = "products.warehouse_sources.backend.facade.api.github_source_credential"


class TestOwnershipFiles(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The team's covering integration is cached per repository, so one test's fallback would
        # otherwise answer the next one's lookup.
        cache.clear()

    def _integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="42",
            config={"account": {"name": "PostHog"}},
            sensitive_config={"access_token": "t0ken"},
        )

    def test_the_selected_sources_token_is_what_reads_the_repository(self) -> None:
        # A connected source is the only credential engineering analytics has for a private
        # repository, and the read must use the token of the source it was scoped to.
        with (
            patch(_CREDENTIAL, return_value=GitHubSourceCredential(personal_access_token="selected")) as credential,
            patch.object(GitHubFilesFetcher, "from_token", side_effect=GitHubFilesFetcher.from_token) as built,
        ):
            files = repo_files(self.team, _REPOSITORY, source_id="src", priority=Priority.BATCH)
        credential.assert_called_once_with(team_id=self.team.pk, source_id="src")
        built.assert_called_once_with("selected", priority=Priority.BATCH)
        assert isinstance(files, AuthenticatedRepoFiles)

    @parameterized.expand([("a_connected_integration", True), ("an_integration_row_that_is_gone", False)])
    def test_an_oauth_source_reads_as_its_github_integration(self, _name: str, connected: bool) -> None:
        # The source names an integration row rather than holding a token, so a row that was
        # disconnected since the sync was configured has to fall back rather than fail the board.
        integration_id = self._integration().pk if connected else 0
        with (
            patch(_CREDENTIAL, return_value=GitHubSourceCredential(integration_id=integration_id)),
            patch("posthog.ownership.github_files.GitHubIntegration.first_for_team_repository", return_value=None),
        ):
            files = repo_files(self.team, _REPOSITORY, source_id="src", priority=Priority.BATCH)
        assert isinstance(files, AuthenticatedRepoFiles if connected else GitHubRepoFiles)

    @parameterized.expand([("no_selected_source", "", 0), ("a_source_with_no_credential", "src", 1)])
    def test_a_read_with_no_credential_falls_back_to_the_team_integration(
        self, _name: str, source_id: str, lookups: int
    ) -> None:
        with (
            patch(_CREDENTIAL, return_value=None) as credential,
            patch(
                "posthog.ownership.github_files.GitHubIntegration.first_for_team_repository", return_value=None
            ) as team_lookup,
        ):
            files = repo_files(self.team, _REPOSITORY, source_id=source_id, priority=Priority.BATCH)
        # An empty source_id names no source, so it must not cost a source lookup either.
        assert credential.call_count == lookups
        team_lookup.assert_called_once()
        assert isinstance(files, GitHubRepoFiles)
