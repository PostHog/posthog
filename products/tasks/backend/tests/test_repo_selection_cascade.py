import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration

from products.tasks.backend.logic.repo_selection.cascade import cascade_select_repository, select_repository_for_message
from products.tasks.backend.models import Task

_CASCADE = "products.tasks.backend.logic.repo_selection.cascade"


def _patch_candidates(github: object | None, candidates: list[str]):
    return (
        patch(f"{_CASCADE}.resolve_team_github_integration", return_value=github),
        patch(f"{_CASCADE}._list_candidate_repos", return_value=candidates),
    )


async def _run(message: str) -> str | None:
    return await select_repository_for_message(1, 2, message, origin_product=Task.OriginProduct.POSTHOG_AI)


class TestSelectRepositoryForMessage:
    async def test_no_github_integration_returns_none(self):
        resolve, list_repos = _patch_candidates(None, [])
        with resolve, list_repos:
            assert await _run("anything") is None

    async def test_no_candidates_returns_none(self):
        resolve, list_repos = _patch_candidates(MagicMock(), [])
        with resolve, list_repos:
            assert await _run("anything") is None

    async def test_explicit_mention_short_circuits(self):
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog", "posthog/posthog-js"])
        with resolve, list_repos:
            assert await _run("please fix posthog/posthog-js") == "posthog/posthog-js"

    async def test_multi_candidate_without_explicit_mention_returns_none(self):
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog", "posthog/posthog-js"])
        with resolve, list_repos:
            assert await _run("the dashboards are slow") is None


class TestCascadeSelectRepository:
    @pytest.mark.parametrize("single_repo_wins,expected", [(True, "posthog/posthog"), (False, None)])
    def test_lone_repo_only_taken_when_opted_in(self, single_repo_wins, expected):
        # Inbox report actions opt in (a single-repo team has no ambiguity to resolve); an unprompted
        # sandbox message doesn't, so it never pins itself to a repo the user never named.
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog"])
        with resolve, list_repos:
            assert cascade_select_repository(1, 2, "", single_repo_wins=single_repo_wins) == expected

    @pytest.mark.django_db
    def test_unsynced_cache_is_read_without_a_live_sync(self, team):
        # Request-path callers pass allow_refresh=False, so a never-synced cache
        # (repository_cache_updated_at is null) is still read rather than triggering a GitHub sync.
        Integration.objects.create(
            team=team,
            kind="github",
            integration_id="gh-1",
            config={"installation_id": "gh-1"},
            sensitive_config={},
            repository_cache=[{"full_name": "PostHog/PostHog", "name": "PostHog", "id": 1}],
        )

        assert cascade_select_repository(team.id, None, "", single_repo_wins=True, allow_refresh=False) == (
            "posthog/posthog"
        )
