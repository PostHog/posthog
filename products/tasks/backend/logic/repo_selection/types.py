from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Why `repository` came back null. Distinguishes operational failures (no integration, no
# eligible repos, LLM hallucination) from the agent genuinely deciding none of the candidates
# match — callers (e.g. Signals analytics) need this to tell a matching regression apart from
# a customer batch-researching companies that have no public repo. `None` when `repository` is
# set, or for results produced before this field existed.
NoRepoReason = Literal["no_github_integration", "no_eligible_repos", "agent_rejected", "agent_no_match"]


class RepoSelectionResult(BaseModel):
    """Outcome of repository selection: the chosen repo (or none) and why.

    Lives in this leaf module (pydantic only) so it can be shared by dependency-light consumers
    — notably the Signals artefact schema registry — without pulling in the sandbox/LLM runtime
    that `agent.py` imports.
    """

    repository: str | None = Field(
        description="Selected repository in 'owner/repo' format, or null if none of the candidates are relevant."
    )
    reason: str = Field(
        description=(
            "Why this repository was selected (or why none matched). When cache queries were made, "
            "cite the specific path matches, README excerpts, or description content that drove the "
            "decision. When no query was made, justify why the choice was unambiguous from the "
            "context and repo names alone."
        )
    )
    no_repo_reason: NoRepoReason | None = Field(
        default=None,
        description="Machine-readable category for why `repository` is null. Null when a repository was selected.",
    )
    # Set by `select_repository` after the sandbox session, never by the LLM (it is stripped from
    # the prompt's JSON schema). Optional with a default so persisted results and in-flight
    # Temporal payloads from before the field existed still validate.
    task_id: str | None = Field(
        default=None,
        description="UUID of the sandbox task that performed the selection, when an agent ran.",
    )
