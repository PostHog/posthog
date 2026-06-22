from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.tasks.backend.logic.repo_selection.agent import (
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
)
from products.tasks.backend.logic.repo_selection.cascade import select_repository_for_message
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
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock()) as select:
            assert await _run("anything") is None
            select.assert_not_called()

    async def test_no_candidates_returns_none(self):
        resolve, list_repos = _patch_candidates(MagicMock(), [])
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock()) as select:
            assert await _run("anything") is None
            select.assert_not_called()

    async def test_explicit_mention_short_circuits(self):
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog", "posthog/posthog-js"])
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock()) as select:
            assert await _run("please fix posthog/posthog-js") == "posthog/posthog-js"
            select.assert_not_called()

    async def test_delegates_to_select_repository_without_explicit_mention(self):
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog", "posthog/posthog-js"])
        result = RepoSelectionResult(repository="posthog/posthog", reason="agent picked it")
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock(return_value=result)) as select:
            assert await _run("the dashboards are slow") == "posthog/posthog"
            select.assert_awaited_once()

    async def test_forwards_resolved_integration_and_candidates(self):
        github = MagicMock()
        candidates = ["posthog/posthog", "posthog/posthog-js"]
        resolve, list_repos = _patch_candidates(github, candidates)
        result = RepoSelectionResult(repository="posthog/posthog", reason="agent picked it")
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock(return_value=result)) as select:
            await _run("the dashboards are slow")
            assert select.await_args.kwargs["github"] is github
            assert select.await_args.kwargs["candidate_repos"] == candidates

    async def test_select_repository_null_returns_none(self):
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog", "posthog/posthog-js"])
        result = RepoSelectionResult(repository=None, reason="no plausible candidate")
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock(return_value=result)):
            assert await _run("a question about billing") is None

    @parameterized.expand(
        [
            ("rejected", RepoSelectionRejectedError("posthog/hallucinated", "made it up")),
            ("unavailable", RepoSelectionUnavailableError("all archived")),
            ("unexpected", RuntimeError("sandbox boot failed")),
        ]
    )
    async def test_selection_failure_degrades_to_none(self, _name: str, error: Exception):
        resolve, list_repos = _patch_candidates(MagicMock(), ["posthog/posthog", "posthog/posthog-js"])
        with resolve, list_repos, patch(f"{_CASCADE}.select_repository", new=AsyncMock(side_effect=error)):
            assert await _run("the dashboards are slow") is None
