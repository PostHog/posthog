from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import patch

from products.signals.evals.agentic.cases.research import SESSION_IDS
from products.signals.evals.agentic.datasets import RepoSelectionCase, ScoutCase
from products.signals.evals.agentic.seeders import seed_repository_catalog, seed_research_sessions, seed_scout_project
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def test_seed_research_sessions_creates_every_referenced_session() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))

    with patch("posthog.session_recordings.queries.test.session_replay_sql.produce_replay_summary") as produce:
        seed = seed_research_sessions(context)

    assert seed == {"session_ids": list(SESSION_IDS)}
    assert [call.kwargs["session_id"] for call in produce.call_args_list] == list(SESSION_IDS)
    assert all(call.kwargs["team_id"] == 7 for call in produce.call_args_list)


def test_seed_repository_catalog_provides_a_non_expiring_placeholder_token() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    integration = SimpleNamespace(id=42)

    with (
        patch("products.signals.evals.agentic.seeders.Integration.objects.create", return_value=integration) as create,
        patch("products.signals.evals.agentic.seeders.IntegrationRepositoryCacheEntry"),
    ):
        seed_repository_catalog(context)

    assert create.call_args.kwargs["sensitive_config"] == {"access_token": "signals-eval-public-repositories"}


def test_seed_repository_catalog_limits_candidates_and_uses_real_paths() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    case = RepoSelectionCase(
        case_id="canvas",
        step="repo_selection",
        candidate_repos=("excalidraw/excalidraw", "tldraw/tldraw"),
    )
    integration = SimpleNamespace(id=42)

    with (
        patch("products.signals.evals.agentic.seeders.Integration.objects.create", return_value=integration) as create,
        patch("products.signals.evals.agentic.seeders.IntegrationRepositoryCacheEntry") as cache_entry,
    ):
        seed_repository_catalog(context, case)

    cached_names = {repo["full_name"] for repo in create.call_args.kwargs["repository_cache"]}
    assert cached_names == {"excalidraw/excalidraw", "tldraw/tldraw"}
    cached_paths = "\n".join(call.kwargs["tree_paths"] for call in cache_entry.call_args_list)
    assert "staticSvgScene.ts" in cached_paths
    assert "SvgExportContext.tsx" in cached_paths
    assert all(call.kwargs["default_branch_sha"] != "0" * 40 for call in cache_entry.call_args_list)


@pytest.mark.parametrize(
    ("seed_name", "broad_reach"),
    [("error_burst", True), ("error_low_volume", False)],
)
def test_seed_scout_project_dispatches_error_seed(seed_name, broad_reach) -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    case = ScoutCase(
        case_id="scout",
        step="scout",
        skill_name="signals-scout-error-tracking",
        seed=seed_name,
    )

    with patch("products.signals.evals.agentic.seeders._seed_error_tracking") as seed:
        seed.return_value = {"issue": "checkout"}
        result = seed_scout_project(context, case)

    seed.assert_called_once_with(context, broad_reach=broad_reach)
    assert result == {"issue": "checkout"}


@pytest.mark.parametrize(
    ("seed_name", "denominator_holds"),
    [("funnel_regression", True), ("funnel_denominator_drop", False)],
)
def test_seed_scout_project_dispatches_funnel_seed(seed_name, denominator_holds) -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    case = ScoutCase(
        case_id="scout",
        step="scout",
        skill_name="signals-scout-product-analytics",
        seed=seed_name,
    )

    with patch("products.signals.evals.agentic.seeders._seed_product_funnel") as seed:
        seed.return_value = {"insight": "activation"}
        result = seed_scout_project(context, case)

    seed.assert_called_once_with(context, denominator_holds=denominator_holds)
    assert result == {"insight": "activation"}
