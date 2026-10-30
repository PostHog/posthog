from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from requests import Timeout

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models import Team
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration

from products.signals.backend.github_optional import (
    GITHUB_OPTIONAL_FLAG,
    RepositoryAccessTemporarilyUnavailable,
    ResearchAccessPolicy,
)
from products.signals.backend.models import SignalTeamConfig
from products.signals.backend.scout_harness.team_limits import _parse_enrollment, _resolve_enrolled
from products.signals.backend.temporal.agentic.scout_coordinator import _participating_teams


class TestResearchAccessPolicy(BaseTest):
    def test_flag_uses_canonical_project_and_fails_closed(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        with patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=True) as flag:
            assert ResearchAccessPolicy.enabled(child.id)
        assert flag.call_args.args == (GITHUB_OPTIONAL_FLAG, str(self.team.uuid))
        assert flag.call_args.kwargs["groups"] == {"project": str(self.team.uuid)}
        with patch("products.signals.backend.github_optional.feature_enabled_or_false", side_effect=RuntimeError):
            assert not ResearchAccessPolicy.enabled(self.team.id)

    @parameterized.expand(
        ["example/app/contents/file", "example/app?ref=main", "example/app#section", "example/app%2Fpath"]
    )
    def test_repository_access_rejects_non_repository_paths(self, repository: str) -> None:
        Integration.objects.create(team=self.team, kind="github", integration_id="first")
        with patch.object(GitHubIntegration, "installation_can_access_repository") as probe:
            assert ResearchAccessPolicy.repository_integration_id(self.team.id, repository) is None
        probe.assert_not_called()

    @parameterized.expand(
        [
            (False, False, False, True),
            (True, False, True, True),
            (True, True, False, True),
            (True, False, False, False),
            (True, False, False, True, True),
        ]
    )
    def test_activation_enrolls_in_both_scheduled_and_manual_dispatch(
        self, enabled: bool, excluded: bool, expected: bool, completed: bool, drained: bool = False
    ) -> None:
        SignalTeamConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "onboarding": {
                    "draft": {"activation_mode": "github_optional"},
                    "completed_at": "2026-10-26T00:00:00Z" if completed else None,
                }
            },
        )
        enrollment = _parse_enrollment({"skip_team_ids": [self.team.id] if excluded else []})
        if drained:
            enrollment = _parse_enrollment({"guaranteed_team_ids": []})
        with (
            patch("products.signals.backend.github_optional.feature_enabled_or_false", return_value=enabled),
            patch("posthoganalytics.default_client", SimpleNamespace(feature_flags=[])),
        ):
            assert _resolve_enrolled(self.team.id, enrollment) is expected
            assert (self.team.id in {team.id for team, _ in _participating_teams(enrollment)}) is expected
        with patch("posthoganalytics.default_client", None):
            assert ResearchAccessPolicy.enrolled_team_ids() == set()

    @parameterized.expand(
        [
            (Timeout(), False, True),
            (GitHubRateLimitError("Rate limited", retry_after=30), False, True),
            (GitHubIntegrationError("Unavailable", status_code=503), False, True),
            (GitHubIntegrationError("Forbidden", status_code=403), False, False),
            (Timeout(), True, False),
        ]
    )
    def test_repository_access_preserves_transient_failures_after_trying_other_installations(
        self, error: Exception, other_available: bool, retryable: bool
    ) -> None:
        Integration.objects.create(team=self.team, kind="github", integration_id="first")
        second = Integration.objects.create(team=self.team, kind="github", integration_id="second")
        with patch.object(
            GitHubIntegration, "installation_can_access_repository", side_effect=[error, other_available]
        ):
            if retryable:
                with self.assertRaises(RepositoryAccessTemporarilyUnavailable) as raised:
                    ResearchAccessPolicy.repository_integration_id(self.team.id, "example/product")
                assert raised.exception.status_code == 503
                if isinstance(error, GitHubRateLimitError):
                    assert raised.exception.wait == 30
            else:
                assert ResearchAccessPolicy.repository_integration_id(self.team.id, "example/product") == (
                    second.id if other_available else None
                )
