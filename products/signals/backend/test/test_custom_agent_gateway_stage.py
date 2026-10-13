"""Pins the custom-agent run's ai_stage stamp: it must equal STEP_CUSTOM_AGENT so
`signals-pipeline-models` payload authors target the vocabulary they see in LLM
analytics. Deleting the kwarg keeps every other suite green."""

from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync

import products.signals.backend.temporal.custom_agent  # noqa: F401  (warms the base<->temporal import cycle so standalone collection works)
from products.signals.backend.agent_runtime import STEP_CUSTOM_AGENT, AgentRuntime
from products.signals.backend.custom_agent.base import CustomSignalAgent


def test_send_raw_stamps_custom_agent_stage():
    agent = CustomSignalAgent.__new__(CustomSignalAgent)
    agent._session = None
    agent.team_id = 123
    agent.user_id = 456
    agent._resolved_repository = None
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
