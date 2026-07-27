"""
Facade re-exports for the multi-turn agent machinery.

The custom-prompt agent surface (sandbox context, the multi-turn session driver, the
create/poll primitives, local-dev helpers) is shared behavioral infrastructure that other
products (signals, conversations, evals) build agentic flows on. It crosses the boundary as
objects, not data, per the wiring pattern. Heavy by import, so it lives here rather than in
``facade/api.py``.
"""

from products.tasks.backend.logic.services.custom_prompt_internals import (
    CustomPromptSandboxContext,
    EmptyAgentTurnError,
    OutputFn,
    create_task_and_trigger,
    extract_json_from_text,
    poll_for_turn,
)
from products.tasks.backend.logic.services.custom_prompt_multi_turn_runner import MultiTurnSession
from products.tasks.backend.logic.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev
from products.tasks.backend.logic.services.local_skills import ENV_LOCAL_SKILLS_HOST_PATH, LocalSkillsCache

__all__ = [
    "ENV_LOCAL_SKILLS_HOST_PATH",
    "CustomPromptSandboxContext",
    "EmptyAgentTurnError",
    "LocalSkillsCache",
    "MultiTurnSession",
    "OutputFn",
    "create_task_and_trigger",
    "extract_json_from_text",
    "poll_for_turn",
    "resolve_sandbox_context_for_local_dev",
]
