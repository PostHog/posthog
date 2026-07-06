"""Minimal `CustomSignalAgent` example: writes a poem about cookies.

This module defines only the agent class and its default prompt. The wiring to
Temporal (constructing a team, calling ``run_agent``) lives in the management
command ``run_custom_agent_example`` to keep this module Temporal-free — the
activity dynamically imports agent modules via ``import_agent_class``, and
agent modules that pull in the Temporal layer at module load time can hit
partial-load ``ImportError``s.

Run via the management command::

    # Through Temporal (default)
    python manage.py run_custom_agent_example --agent cookie_poem --team-id 1

    # Direct, no Temporal harness (useful for testing the agent locally)
    python manage.py run_custom_agent_example --agent cookie_poem --team-id 1 --local
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from products.signals.backend.custom_agent import CustomSignalAgent
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)

DEFAULT_PROMPT = "Write a short poem about freshly baked chocolate chip cookies on a quiet afternoon."


class CookiePoem(BaseModel):
    title: str = Field(max_length=96)
    body: str


class CookiePoemAgent(CustomSignalAgent):
    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return "signals", "cookie_poem"

    async def run(self) -> bool:
        poem = await self.send("Write a short poem about cookies.", CookiePoem)
        self.register_title(poem.title)
        self.register_description(poem.body)
        self.register_actionability(
            ActionabilityAssessment(
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                explanation="Cookie poems are immediately bakeable.",
                already_addressed=False,
            )
        )
        self.register_priority(
            PriorityAssessment(
                priority=Priority.P0,
                explanation="Cookies are top priority.",
                dollar_value=1000000.0,
            )
        )
        self.register_assignees([])
        return True
