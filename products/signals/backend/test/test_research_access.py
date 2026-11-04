from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.integration.github_readiness import GitHubReadinessStatus

from products.signals.backend.github_optional import research_access


class TestResearchAccess(SimpleTestCase):
    @parameterized.expand(
        [
            (False, "ready", "code", None),
            (True, "ready", "code", None),
            (False, "not_connected", "blocked", "not_connected"),
            (True, "not_connected", "data_only", None),
            (False, "reconnect_required", "blocked", "reconnect_required"),
            (True, "reconnect_required", "data_only", None),
            (False, "no_repositories", "blocked", "no_repositories"),
            (True, "no_repositories", "data_only", None),
            (False, "temporarily_unavailable", "blocked", "temporarily_unavailable"),
            (True, "temporarily_unavailable", "data_only", None),
        ]
    )
    def test_access_decision(self, allowed: bool, status: str, mode: str, blocker: str | None) -> None:
        access = research_access(github_optional_allowed=allowed, github_status=GitHubReadinessStatus(status))
        assert access.mode == mode
        assert access.blocker == blocker
