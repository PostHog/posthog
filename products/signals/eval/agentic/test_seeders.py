from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from products.signals.eval.agentic.cases.research import SESSION_IDS
from products.signals.eval.agentic.seeders import seed_research_sessions
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def test_seed_research_sessions_creates_every_referenced_session() -> None:
    context = cast(CustomPromptSandboxContext, SimpleNamespace(team_id=7))

    with patch("posthog.session_recordings.queries.test.session_replay_sql.produce_replay_summary") as produce:
        seed = seed_research_sessions(context)

    assert seed == {"session_ids": list(SESSION_IDS)}
    assert [call.kwargs["session_id"] for call in produce.call_args_list] == list(SESSION_IDS)
    assert all(call.kwargs["team_id"] == 7 for call in produce.call_args_list)
