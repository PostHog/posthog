import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.tasks.backend.logic.repo_selection.agent import (
    RepoSelectionResult,
    _salvage_non_json_end_turn,
    select_repository,
)


class TestSalvageNonJsonEndTurn:
    def test_collapses_to_no_repo(self):
        result = _salvage_non_json_end_turn("not json at all")
        assert isinstance(result, RepoSelectionResult)
        assert result.repository is None

    @parameterized.expand(
        [
            ("rate_limit_429", "API Error: Request rejected (429) · Rate limit exceeded"),
            ("overloaded_529", "API Error: Overloaded (529)"),
            ("too_many_requests", "Error: Too Many Requests"),
        ]
    )
    def test_tags_upstream_api_errors(self, _name: str, text: str):
        result = _salvage_non_json_end_turn(text)
        assert result.repository is None
        assert "upstream API error" in result.reason

    def test_generic_prose_reason(self):
        result = _salvage_non_json_end_turn("I think it's probably posthog/posthog but I'm not sure.")
        assert result.repository is None
        assert "not valid JSON" in result.reason

    def test_truncates_long_text_in_reason(self):
        result = _salvage_non_json_end_turn("x" * 5000)
        # The reason embeds at most a 200-char snippet of the raw text.
        assert len(result.reason) < 400


class TestSelectRepositoryWiresFallback:
    @pytest.mark.asyncio
    async def test_non_json_end_turn_degrades_to_no_repo(self):
        # The agent ends its turn with a 429 error string instead of JSON. start() invokes the
        # caller's fallback to salvage it; select_repository must return repository=None rather
        # than letting the parse failure propagate and crash the run.
        rate_limit_text = "API Error: Request rejected (429) · Rate limit exceeded"
        candidates = ["posthog/posthog", "posthog/posthog-js"]

        fake_github = MagicMock()
        fake_session = MagicMock()
        fake_session.task.id = "task-1"
        fake_session.task_run.id = "run-1"
        fake_session.end = AsyncMock()

        async def fake_start(*args, **kwargs):
            # Mirror MultiTurnSession.start's salvage path: a non-JSON end-turn is handed to the
            # caller-provided fallback rather than raising.
            salvaged = kwargs["fallback_from_text"](rate_limit_text)
            return fake_session, salvaged

        with (
            patch(
                "products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration",
                return_value=fake_github,
            ),
            patch(
                "products.tasks.backend.logic.repo_selection.agent._list_candidate_repos",
                return_value=candidates,
            ),
            patch(
                "products.tasks.backend.logic.repo_selection.agent._list_eligible_full_names",
                return_value=set(candidates),
            ),
            patch("products.tasks.backend.logic.repo_selection.agent.GitHubRepositoryFullCache") as mock_cache_cls,
            patch(
                "products.tasks.backend.logic.repo_selection.agent.MultiTurnSession.start",
                new=AsyncMock(side_effect=fake_start),
            ),
        ):
            mock_cache_cls.return_value.sync_full_cache = AsyncMock()
            result = await select_repository(
                team_id=1,
                user_id=2,
                context="something is broken",
                origin_product=MagicMock(),
            )

        assert result.repository is None
        assert "upstream API error" in result.reason
        fake_session.end.assert_awaited_once()
