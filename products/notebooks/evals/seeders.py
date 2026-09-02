"""Seeder hooks for the notebook eval cases.

The seeder contract takes no per-case parameters, so each seeded state gets its own
function. Every one of them returns ``team_id``: it is the only channel a scorer has
for reaching the case's own team, and the notebook scorers grade the documents and run
rows the agent left there rather than what the transcript claims.
"""

from __future__ import annotations

from typing import Any

from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def seed_case_team(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed nothing; hand the scorers the case's team so they can read the end state.

    For cases where the agent creates the notebook itself, Hedgebox is already the
    whole fixture.
    """
    return {"team_id": context.team_id}
