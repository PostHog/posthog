"""Minimal `CustomSignalAgent` example: writes a poem about cookies.

Run it::

    from products.signals.backend.custom_agent.examples.cookie_poem_agent import run_cookie_poem_agent

    handle = run_cookie_poem_agent(team_id=1, prompt="Cookies on a rainy day")
"""

from __future__ import annotations

from pydantic import BaseModel

from posthog.models import Team

from products.signals.backend.custom_agent import NO_REPO, CustomAgentRunHandle, CustomSignalAgent
from products.signals.backend.report_generation.research import ActionabilityChoice, Priority

DEFAULT_PROMPT = "Write a short poem about freshly baked chocolate chip cookies on a quiet afternoon."


class CookiePoem(BaseModel):
    title: str
    body: str


class CookiePoemAgent(CustomSignalAgent):
    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return "signals", "cookie_poem"

    async def run(self) -> None:
        poem = await self.send("Write a short poem about cookies.", CookiePoem)
        self.register_title(poem.title)
        self.register_description(poem.body)
        self.register_actionability(ActionabilityChoice.IMMEDIATELY_ACTIONABLE)
        self.register_priority(Priority.P0)
        self.register_assignees([])


def run_cookie_poem_agent(*, team_id: int, prompt: str = DEFAULT_PROMPT) -> CustomAgentRunHandle:
    team = Team.objects.select_related("organization").get(id=team_id)
    return CookiePoemAgent.run_agent(team=team, initial_prompt=prompt, repository=NO_REPO)
