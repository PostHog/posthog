"""
Facade re-exports for the multi-turn agent machinery.

The custom-prompt agent surface (sandbox context, the multi-turn session driver, the
create/poll primitives, local-dev helpers) is shared behavioral infrastructure that other
products (signals, conversations, evals) build agentic flows on. It crosses the boundary as
objects, not data, per the wiring pattern. Heavy by import, so it lives here rather than in
``facade/api.py``.
"""

from products.tasks.backend.constants import EVAL_INTERACTION_ORIGIN, MCP_EXEC_SKILLS_FEATURE_FLAG
from products.tasks.backend.logic.services.custom_prompt_internals import (
    CustomPromptSandboxContext,
    EmptyAgentTurnError,
    OutputFn,
    TruncatedAgentOutputError,
    TurnPollResult,
    TurnPollTimeout,
    create_task_and_trigger,
    extract_json_from_text,
    poll_for_turn,
)
from products.tasks.backend.logic.services.custom_prompt_multi_turn_runner import MultiTurnSession
from products.tasks.backend.logic.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev
from products.tasks.backend.logic.services.local_skills import (
    ENV_DISABLE_BUNDLED_SKILLS,
    ENV_LOCAL_SKILLS_HOST_PATH,
    LocalSkillsCache,
)
from products.tasks.backend.models import SandboxEnvironment


def create_skill_isolation_environment(*, team_id: int, user_id: int, name: str) -> str:
    """Create an internal environment that disables native bundled skills for an agent run."""
    environment = SandboxEnvironment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=name,
        environment_variables={ENV_DISABLE_BUNDLED_SKILLS: "1"},
        internal=True,
    )
    return str(environment.id)


__all__ = [
    "ENV_DISABLE_BUNDLED_SKILLS",
    "EVAL_INTERACTION_ORIGIN",
    "MCP_EXEC_SKILLS_FEATURE_FLAG",
    "ENV_LOCAL_SKILLS_HOST_PATH",
    "CustomPromptSandboxContext",
    "EmptyAgentTurnError",
    "LocalSkillsCache",
    "MultiTurnSession",
    "OutputFn",
    "TruncatedAgentOutputError",
    "TurnPollResult",
    "TurnPollTimeout",
    "create_task_and_trigger",
    "create_skill_isolation_environment",
    "extract_json_from_text",
    "poll_for_turn",
    "resolve_sandbox_context_for_local_dev",
]
