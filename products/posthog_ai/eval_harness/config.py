from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from products.tasks.backend.facade.agents import CustomPromptSandboxContext


class BaseEvalCase(BaseModel):
    """A single eval case, independent of how its task executes.

    Named ``BaseEvalCase`` (not ``EvalCase``) to avoid shadowing Braintrust's
    ``EvalCase``, which the runners import alongside it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    """Human-readable name for this eval case."""

    prompt: str
    """Natural language task description for the agent or model."""

    expected: dict[str, Any] = Field(default_factory=dict)
    """Expected values for scoring, keyed by scorer ``_name()``.

    Each scorer reads its own sub-entry — e.g. ``{"tests_pass": {"should_pass": True}}``.
    Missing keys mean the scorer falls back to its default behavior.
    """

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Arbitrary metadata for tracking and filtering."""


class SandboxedEvalCase(BaseEvalCase):
    """A single eval case for the sandboxed coding agent."""

    repo_fixture: str = ""
    """Name of the repo fixture (informational, for tracking)."""

    interaction_origin: str | None = None
    """Surface to run the case as (e.g. ``"slack"``), for suites grading behavior that only
    exists on one surface. The agent server branches its system prompt on this, so setting it
    is what makes a case exercise the real prompt instead of a copy. ``None`` runs the case
    like a plain task, which is what every non-surface-specific suite wants."""

    setup: Callable[[CustomPromptSandboxContext], dict[str, Any]] | None = Field(
        default=None,
        exclude=True,
    )
    """Optional pre-run hook invoked once the per-case team/user has been
    provisioned, before the agent prompt is dispatched. Returns a dict that
    is merged into the task output under ``seed`` so scorers can read seeded
    entity IDs. Excluded from serialization — the callable never round-trips
    through Braintrust telemetry.
    """


class AgentArtifacts(BaseModel):
    """Collected outputs from a sandboxed agent run.

    Passed to scorers as the `output` value. Fields are populated by parsing
    the agent's JSONL session logs from S3.
    """

    exit_code: int
    """0 if the agent finished cleanly, 1 otherwise."""

    stdout: str = ""
    """Concatenated tool call output from the agent session."""

    stderr: str = ""
    """Error output, if any."""

    git_diff: str = ""
    """Git diff extracted from agent tool calls."""

    files_changed: list[str] = Field(default_factory=list)
    """File paths extracted from agent tool calls."""

    test_exit_code: int | None = None
    """Inferred exit code from test tool calls (None if not run)."""

    test_output: str = ""
    """Test output extracted from agent tool calls."""

    lint_exit_code: int | None = None
    """Inferred exit code from lint tool calls (None if not run)."""

    lint_output: str = ""
    """Lint output extracted from agent tool calls."""

    tool_call_count: int = 0
    """Tool calls the agent made. Zero alongside a non-zero ``exit_code`` means the run failed before
    it did any work, which the harness treats as an infrastructure error rather than a score."""

    duration_seconds: float = 0.0
    """Wall-clock time for the agent run in seconds."""

    pr_url: str | None = None
    """URL of the created PR, if any."""
