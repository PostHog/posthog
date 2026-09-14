from __future__ import annotations

from pydantic import BaseModel, Field

# Why repo selection ended without a repository. Set by whichever exit produced the null result,
# so callers can keep the exits apart in telemetry. `no_match` is the only one that measures
# selection quality: the agent ran, saw the candidate list, and chose none of it.
NO_REPO_CAUSE_NO_INTEGRATION = "no_integration"  # No GitHub integration, or no repository connected
NO_REPO_CAUSE_NO_ELIGIBLE = "no_eligible"  # Repos connected, but all archived or missing cache data
NO_REPO_CAUSE_PICK_REJECTED = "pick_rejected"  # The agent picked a repository outside the candidate list
NO_REPO_CAUSE_NO_MATCH = "no_match"  # The agent ran and picked none of the candidates


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
    # Set by the exit that produced the null result, never by the LLM (stripped from the prompt's
    # JSON schema). Optional with a default, for the same reason as `task_id`: a result from before
    # the field existed carries None, which readers treat as "cause unknown".
    no_repo_cause: str | None = Field(
        default=None,
        description="Why no repository was selected, when `repository` is null.",
    )
    # Inferring a repo from content is weaker evidence than a caller naming one: it says "this is the
    # repo a person would target", not "open a PR here". Autostart needs the second, so an inferred
    # selection is a target for a human-triggered run only.
    autostart_eligible: bool = Field(
        default=True,
        description="Whether this selection may start an implementation task without a person asking for one.",
    )
