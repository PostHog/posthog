"""Pins the custom-agent sandbox run's ai_stage stamp.

The stamp is what gives custom-agent LLM spend a stage (and, via the agent
server, the `signals_custom_agent` product) instead of landing unlabelled under
broad `signals`. It must also stay equal to STEP_CUSTOM_AGENT so
`signals-pipeline-models` payload authors can target the vocabulary they see in
LLM analytics. Deleting the kwarg keeps every other suite green, so this test
is the only thing that fails on a silent revert.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync

from products.signals.backend.agent_runtime import STEP_CUSTOM_AGENT, AgentRuntime
from products.signals.backend.artefact_schemas import (
    CodeReference,  # noqa: F401  (fully initializes the package before base)
)
from products.signals.backend.custom_agent.base import CustomSignalAgent


def test_send_raw_stamps_custom_agent_stage():
    agent = CustomSignalAgent.__new__(CustomSignalAgent)
    agent._session = None
    agent.team_id = 123
    agent.user_id = 456
    agent.repository = None
    agent.model = "claude-sonnet-4-6"

    start_raw = AsyncMock(return_value=(MagicMock(), "ok"))
    with (
        patch(
            "products.signals.backend.custom_agent.base.get_or_create_signals_sandbox_env",
            return_value="env-id",
        ),
        patch(
            "products.signals.backend.custom_agent.base.resolve_agent_runtime",
            return_value=AgentRuntime(),
        ),
        patch(
            "products.signals.backend.custom_agent.base.MultiTurnSession.start_raw",
            start_raw,
        ),
    ):
        result = async_to_sync(agent._send_raw)("prompt", label="step-1")

    assert result == "ok"
    assert start_raw.call_args.kwargs["ai_stage"] == STEP_CUSTOM_AGENT
