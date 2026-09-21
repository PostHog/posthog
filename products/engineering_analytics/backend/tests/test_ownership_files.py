from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import Integration
from posthog.ownership.github_files import AuthenticatedRepoFiles
from posthog.ownership.repo_files import GitHubRepoFiles

from products.engineering_analytics.backend.logic.ownership_files import repo_files
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

_REPOSITORY = "PostHog/posthog"


class TestOwnershipFiles(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The team's covering integration is cached per repository, so one test's fallback would
        # otherwise answer the next one's lookup.
        cache.clear()

    def _source(self, job_inputs: dict[str, Any]) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh",
            connection_id="gh",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            job_inputs=job_inputs,
        )

    def _integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="42",
            config={"account": {"name": "PostHog"}},
            sensitive_config={"access_token": "t0ken"},
        )

    @parameterized.expand(
        [
            ("pat", {"auth_method": {"selection": "pat", "personal_access_token": "t0ken"}}),
            ("pat_without_a_token", {"auth_method": {"selection": "pat"}}),
            ("oauth_without_an_integration", {"auth_method": {"selection": "oauth"}}),
        ]
    )
    def test_a_source_credential_is_used_where_the_source_has_one(self, _name: str, auth: dict[str, Any]) -> None:
        # A connected source is the only credential engineering analytics has for a private
        # repository, and a half-configured one must fall back rather than fail the board.
        self._source({**auth, "repository": _REPOSITORY})
        usable = bool(auth["auth_method"].get("personal_access_token"))
        with patch("posthog.ownership.github_files.GitHubIntegration.first_for_team_repository", return_value=None):
            files = repo_files(self.team, _REPOSITORY, priority=Priority.BATCH)
        assert isinstance(files, AuthenticatedRepoFiles if usable else GitHubRepoFiles)

    def test_an_oauth_source_reads_as_its_github_integration(self) -> None:
        integration = self._integration()
        self._source(
            {
                "auth_method": {"selection": "oauth", "github_integration_id": integration.pk},
                "repositories": [_REPOSITORY],
            }
        )
        files = repo_files(self.team, _REPOSITORY, priority=Priority.BATCH)
        assert isinstance(files, AuthenticatedRepoFiles)

    def test_a_repository_no_source_lists_falls_back_to_the_team_integration(self) -> None:
        self._source({"auth_method": {"selection": "pat", "personal_access_token": "t0ken"}, "repository": "a/b"})
        with patch(
            "posthog.ownership.github_files.GitHubIntegration.first_for_team_repository", return_value=None
        ) as lookup:
            files = repo_files(self.team, _REPOSITORY, priority=Priority.BATCH)
        lookup.assert_called_once()
        assert isinstance(files, GitHubRepoFiles)
