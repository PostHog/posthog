from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration.github_readiness import GitHubReadinessStatus

from products.signals.backend.github_optional import research_access


class TestResearchAccess(SimpleTestCase):
    @parameterized.expand(
        [
            (False, "ready", "example/app", "code", None),
            (True, "ready", "example/app", "code", None),
            (False, "ready", None, "repository_discovery", None),
            (True, "ready", None, "repository_discovery", None),
            (False, "not_connected", None, "blocked", "not_connected"),
            (True, "not_connected", None, "data_only", None),
            (False, "reconnect_required", None, "blocked", "reconnect_required"),
            (True, "reconnect_required", None, "data_only", None),
            (False, "no_repositories", None, "blocked", "no_repositories"),
            (True, "no_repositories", None, "data_only", None),
            (False, "temporarily_unavailable", None, "blocked", "temporarily_unavailable"),
            (True, "temporarily_unavailable", None, "data_only", None),
            (True, "reconnect_required", "example/app", "data_only", None),
        ]
    )
    def test_access_decision(
        self, allowed: bool, status: str, repository: str | None, mode: str, blocker: str | None
    ) -> None:
        access = research_access(
            github_optional_allowed=allowed, github_status=GitHubReadinessStatus(status), repository=repository
        )
        assert access.mode == mode
        assert access.blocker == blocker
