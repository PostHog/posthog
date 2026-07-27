from unittest.mock import MagicMock, patch

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
