from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.integration import Integration

from products.signals.backend.constants import FIRST_REPORT_SCOUT
from products.signals.backend.models import SignalReportPullRequest, SignalScoutConfig
from products.signals.backend.scout_harness.runner import _resolve_github_posture
from products.signals.backend.scout_harness.skill_loader import LoadedSkill
from products.signals.backend.scout_repositories import default_scout_repositories

LIST_REPOSITORIES = "products.signals.backend.scout_repositories.GitHubIntegration.list_all_cached_repositories"
INTEGRATION_ID = "products.signals.backend.scout_repositories.tasks_facade.readonly_github_integration_id"


class TestDefaultScoutRepositories(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.integration = Integration.objects.create(
            team=self.team, kind="github", config={"account": {"type": "org"}}
        )

    def test_ranks_merged_fixes_before_recent_pushes_and_skips_archived(self) -> None:
        for number, repository in enumerate(["acme/api", "acme/api", "Acme/Web"], start=1):
            SignalReportPullRequest.objects.create(
                team=self.team,
                repository=repository,
                number=number,
                url=f"https://github.com/{repository}/pull/{number}",
                merged_at=timezone.now(),
            )
        SignalReportPullRequest.objects.create(
            team=self.team, repository="acme/docs", number=9, url="https://github.com/acme/docs/pull/9"
        )
        repositories = [
            {"full_name": "acme/docs", "pushed_at": "2026-11-02T00:00:00Z"},
            {"full_name": "acme/archive", "pushed_at": "2026-11-03T00:00:00Z", "archived": True},
            {"full_name": "acme/web", "pushed_at": "2026-01-01T00:00:00Z"},
            {"full_name": "acme/api", "pushed_at": "2025-01-01T00:00:00Z"},
            {"full_name": "acme/sdk", "pushed_at": "2026-10-01T00:00:00Z"},
            {"full_name": "acme/old", "pushed_at": "2024-01-01T00:00:00Z"},
            {"full_name": "acme/never-pushed"},
        ]

        with (
            patch(INTEGRATION_ID, return_value=self.integration.id),
            patch(LIST_REPOSITORIES, return_value=repositories),
        ):
            ranked = default_scout_repositories(self.team.id)

        assert ranked == ["acme/api", "acme/web", "acme/docs", "acme/sdk", "acme/old"]

    @parameterized.expand(
        [
            ("success_is_cached", None, 1),
            ("failure_is_not_cached", RuntimeError("GitHub unavailable"), 2),
        ]
    )
    def test_caches_the_selection_but_not_a_failed_read(
        self, _name: str, error: Exception | None, expected_reads: int
    ) -> None:
        with (
            patch(INTEGRATION_ID, return_value=self.integration.id),
            patch(LIST_REPOSITORIES, return_value=[{"full_name": "acme/api"}], side_effect=error) as list_repos,
        ):
            first = default_scout_repositories(self.team.id)
            second = default_scout_repositories(self.team.id)

        assert list_repos.call_count == expected_reads
        assert first == second == ([] if error else ["acme/api"])


class TestFirstReportScoutGithubPosture(BaseTest):
    def _skill(self, name: str) -> LoadedSkill:
        return LoadedSkill(
            name=name,
            version=1,
            body="",
            description="",
            allowed_tools=[],
            files=[],
            skill_id="skill",
            origin="canonical",
            authors=[],
        )

    @parameterized.expand(
        [
            ("first_report_without_pin_uses_defaults", FIRST_REPORT_SCOUT, [], True, ["acme/api", "acme/web"]),
            ("first_report_pin_wins", FIRST_REPORT_SCOUT, ["acme/pinned"], True, ["acme/pinned"]),
            ("first_report_without_token_stays_repo_less", FIRST_REPORT_SCOUT, [], False, []),
            ("other_scout_stays_repo_less", "signals-scout-errors", [], True, []),
        ]
    )
    def test_resolves_repositories(
        self, _name: str, skill_name: str, pinned: list[str], can_mint: bool, expected: list[str]
    ) -> None:
        config = SignalScoutConfig.objects.create(team=self.team, skill_name=skill_name, repositories=pinned)

        with (
            patch(
                "products.signals.backend.scout_harness.runner.tasks_facade.can_mint_readonly_github_token",
                return_value=can_mint,
            ),
            patch(
                "products.signals.backend.scout_harness.runner.default_scout_repositories",
                return_value=["acme/api", "acme/web"],
            ),
        ):
            posture = async_to_sync(_resolve_github_posture)(
                team=self.team, config=config, skill=self._skill(skill_name), repository_override=None
            )

        assert posture.repositories == expected
