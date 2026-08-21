from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from products.signals.evals.agentic.cases.research import SESSION_IDS
from products.signals.evals.agentic.seeders import seed_repository_catalog, seed_research_sessions
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
