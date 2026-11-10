"""The contract between Self-driving and a product that hands its records to an agent.

Every type here is a plain value with no ORM row behind it, so it can cross the product boundary
in both directions: products name an entity and read what is attached to it, and Self-driving
calls their loader and handlers with these values.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen


@frozen
class AgentEntity:
    """The key of a record that another product owns. It is unique within a project."""

    product: str
    type: str
    id: str


@frozen
class AgentEntityContent:
    """What the owning product's loader returns for one entity at the start of a pass."""

    title: str
    text: str
    url: str
    # Changes when the content the agent would read changes. A request with no reason on an
    # entity whose hash equals the last finished pass's hash starts nothing.
    content_hash: str


class AgentRunOutcome(StrEnum):
    REPORTS = "reports"
    NOT_ACTIONABLE = "not_actionable"
    NEEDS_INPUT = "needs_input"
    BLOCKED = "blocked"
    FAILED = "failed"


class ImplementationState(StrEnum):
    NONE = "none"
    STARTED = "started"
    PR_DRAFT = "pr_draft"
    PR_OPEN = "pr_open"
    PR_MERGED = "pr_merged"
    PR_CLOSED = "pr_closed"


@frozen
class ReportImplementation:
    state: ImplementationState
    pr_url: str | None
    # A fix run can end with no pull request, and it can open one while it still works. `state`
    # shows neither, so this says whether a fix run for the report is running now.
    run_active: bool = False


@frozen
class AttachedReport:
    """A report linked to an entity. It carries states and no report content, because someone who
    may read the entity is not always allowed to read the report."""

    report_id: str
    relation: str
    status: str
    implementation: ReportImplementation


@frozen
class AttachedRun:
    run_id: str
    pass_number: int
    status: str
    outcome: str | None
    reason_code: str | None
    updated_at: datetime


@frozen
class Attached:
    """What Self-driving holds for one entity: its latest pass, and the reports linked to it."""

    run: AttachedRun | None
    reports: tuple[AttachedReport, ...]


@frozen
class AgentRunResult:
    """The one final answer of a pass, as the owning product's `on_result` handler receives it."""

    run_id: str
    team_id: int
    agent: str
    entity: AgentEntity
    pass_number: int
    outcome: AgentRunOutcome
    reason_code: str | None
    next_pass_queued: bool
    reports: tuple[AttachedReport, ...]
    # The record the agent's skill wrote for the owning product. Its keys are the skill's own schema.
    output: dict[str, Any] | None
