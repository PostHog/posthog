from __future__ import annotations

from pydantic import BaseModel, Field


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
    # Set by `select_repository` after the sandbox session, never by the LLM (it is stripped from
    # the prompt's JSON schema). Optional with a default so persisted results and in-flight
    # Temporal payloads from before the field existed still validate.
    task_id: str | None = Field(
        default=None,
        description="UUID of the sandbox task that performed the selection, when an agent ran.",
    )
