from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import patch

from products.signals.evals.agentic.cases.research import SESSION_IDS
from products.signals.evals.agentic.datasets import RepoSelectionCase, ResearchCase, ScoutCase
from products.signals.evals.agentic.seeders import (
    _seed_research_events,
    _seed_web_vitals,
    _write_events,
    seed_repository_catalog,
    seed_research_project,
    seed_scout_project,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def test_write_events_reuses_shared_event_definition_helper() -> None:
    rows = [
        {
            "event": "signed_up",
            "distinct_id": "person-1",
            "timestamp": datetime.now(UTC),
        }
    ]

    with (
        patch("products.signals.evals.agentic.seeders.create_placeholder_event_definitions") as create_definitions,
        patch("posthog.models.event.util.bulk_create_events"),
    ):
        _write_events(7, rows)

    assert create_definitions.call_args.kwargs["team_id"] == 7
    assert [definition.name for definition in create_definitions.call_args.kwargs["definitions"]] == ["signed_up"]


def test_seed_research_project_creates_every_referenced_session() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))

    with patch("posthog.session_recordings.queries.test.session_replay_sql.produce_replay_summary") as produce:
        seed = seed_research_project(context)

    assert seed == {"session_ids": list(SESSION_IDS)}
    assert [call.kwargs["session_id"] for call in produce.call_args_list] == list(SESSION_IDS)
    assert all(call.kwargs["team_id"] == 7 for call in produce.call_args_list)


@pytest.mark.parametrize(
    "seed_name",
    ["checkout_browser_regression", "signup_volume_drop", "upload_retry_cluster"],
)
def test_seed_research_project_dispatches_case_data(seed_name) -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    case = ResearchCase(case_id="research", step="research", seed=seed_name)

    with (
        patch("posthog.session_recordings.queries.test.session_replay_sql.produce_replay_summary"),
        patch("products.signals.evals.agentic.seeders._seed_research_events") as seed_events,
    ):
        seed_events.return_value = {"scenario": seed_name}
        result = seed_research_project(context, case)

    seed_events.assert_called_once_with(context, seed_name)
    assert result["scenario"] == seed_name
    assert result["session_ids"] == list(SESSION_IDS)


def test_checkout_research_seed_has_segmented_conversion_regression() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))

    with patch("products.signals.evals.agentic.seeders._write_events") as write_events:
        result = _seed_research_events(context, "checkout_browser_regression")

    rows = write_events.call_args.args[1]
    latest = [row for row in rows if "latest" in row["distinct_id"]]
    latest_errors = [row for row in latest if row["event"] == "$exception"]
    latest_completions = [row for row in latest if row["event"] == "checkout_completed"]

    assert result["latest_conversion"] == 0.275
    assert len(latest_errors) == 52
    assert len(latest_completions) == 22
    assert {row["properties"]["$browser"] for row in latest_errors} == {"Safari"}


def test_signup_research_seed_keeps_conversion_constant() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))

    with patch("products.signals.evals.agentic.seeders._write_events") as write_events:
        result = _seed_research_events(context, "signup_volume_drop")

    rows = write_events.call_args.args[1]
    latest = [row for row in rows if row["distinct_id"].split("-")[3] in {"1", "2"}]

    assert result["baseline_conversion"] == result["latest_conversion"] == 0.6
    assert sum(row["event"] == "signup_started" for row in latest) == 60
    assert sum(row["event"] == "signed_up" for row in latest) == 36


def test_upload_research_seed_has_narrow_retry_cluster() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))

    with patch("products.signals.evals.agentic.seeders._write_events") as write_events:
        result = _seed_research_events(context, "upload_retry_cluster")

    rows = write_events.call_args.args[1]
    errors = [row for row in rows if row["event"] == "$exception"]

    assert result == {
        "scenario": "upload_retry_cluster",
        "retry_errors": 90,
        "affected_users": 18,
        "eventual_successes": 16,
    }
    assert len(errors) == 90
    assert len({row["distinct_id"] for row in errors}) == 18
    assert {row["properties"]["$browser"] for row in errors} == {"Safari"}


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


@pytest.mark.parametrize("seed_name", ["error_burst", "error_low_volume", "error_stuck_loop", "error_upstream_noise"])
def test_seed_scout_project_dispatches_error_seed(seed_name) -> None:
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

    seed.assert_called_once_with(context, scenario=seed_name)
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


@pytest.mark.parametrize(
    ("seed_name", "high_volume"),
    [("web_vitals_poor_lcp", True), ("web_vitals_low_sample", False)],
)
def test_seed_scout_project_dispatches_web_vitals_seed(seed_name, high_volume) -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    case = ScoutCase(
        case_id="scout",
        step="scout",
        skill_name="signals-scout-web-vitals",
        seed=seed_name,
    )

    with patch("products.signals.evals.agentic.seeders._seed_web_vitals") as seed:
        seed.return_value = {"path": "/files"}
        result = seed_scout_project(context, case)

    seed.assert_called_once_with(context, high_volume=high_volume)
    assert result == {"path": "/files"}


@pytest.mark.parametrize(("high_volume", "samples"), [(True, 1_200), (False, 30)])
def test_web_vitals_seed_preserves_volume_gate(high_volume, samples) -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))
    team = SimpleNamespace(id=7, project_id=8)

    with (
        patch("posthog.models.Team.objects.get", return_value=team),
        patch("posthog.models.EventDefinition.objects.get_or_create"),
        patch("products.signals.evals.agentic.seeders._write_events") as write_events,
    ):
        result = _seed_web_vitals(context, high_volume=high_volume)

    rows = write_events.call_args.args[1]
    assert result["samples"] == samples
    assert len(rows) == samples
    assert all(row["properties"]["$web_vitals_LCP_value"] > 4_000 for row in rows)
