"""
Contract types for the tasks product.

Stable, framework-free frozen dataclasses describing the data the tasks product
exposes across product boundaries. No Django, no DRF — just stdlib/pydantic types.

These use ``pydantic.dataclasses.dataclass`` (same shape as the stdlib variant, but
with runtime validation on construction) so a malformed mapper surfaces a
``ValidationError`` at the boundary instead of a confusing failure deep in a caller.

Behavioral/wiring surfaces (sandbox classes, the multi-turn agent machinery, temporal
workflows, max tools, webhook handlers) are NOT data and are not modelled here — they
are re-exported as objects through the sibling facade submodules (``sandbox``,
``agents``, ``temporal``, ``max_tools``, ``webhooks``, …).
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TaskDTO:
    """A code task."""

    id: UUID
    team_id: int
    title: str
    description: str
    origin_product: str
    repository: str | None
    internal: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    created_by_id: int | None = None
    task_number: int | None = None
    slug: str = ""


@dataclass(frozen=True)
class TaskRunDTO:
    """A single execution of a task.

    Carries the derived fields external callers read off a ``TaskRun`` ORM instance
    (``is_terminal``, ``workflow_id``, ``mode``) plus a few denormalised parent-task
    values (``task_origin_product``, ``created_by_distinct_id``, ``pr_url``) so callers
    never need to traverse the ORM relation themselves.
    """

    id: UUID
    task_id: UUID
    team_id: int
    status: str
    environment: str
    stage: str | None
    branch: str | None
    error_message: str | None
    output: dict | None
    state: dict
    artifacts: list = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    is_terminal: bool = False
    workflow_id: str = ""
    mode: str = "background"
    task_origin_product: str | None = None
    created_by_id: int | None = None
    created_by_distinct_id: str | None = None
    pr_url: str | None = None


@dataclass(frozen=True)
class CreatedTaskDTO:
    """Result of creating-and-running a task.

    ``Task.create_and_run`` returns an ORM instance whose ``latest_run`` is read by
    callers; this contract hands back the ids (and the run, if one was created) without
    leaking the model.
    """

    task_id: UUID
    team_id: int
    latest_run: TaskRunDTO | None = None


@dataclass(frozen=True)
class SandboxEnvironmentDTO:
    """A sandbox execution environment."""

    id: UUID
    team_id: int
    name: str
    network_access_level: str
    private: bool
    internal: bool
    include_default_domains: bool
    allowed_domains: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SandboxSnapshotDTO:
    """A snapshot of a sandbox image."""

    id: UUID
    external_id: str
    status: str
    repos: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SignalReportPrUrlDTO:
    """The PR URL produced by the latest task run for a signal report."""

    report_id: str
    pr_url: str


@dataclass(frozen=True)
class TaskRunGaugeRow:
    """One metric value keyed by (status, environment, origin_product)."""

    environment: str
    origin_product: str
    value: float
    status: str | None = None


@dataclass(frozen=True)
class TaskRunStateMetricsDTO:
    """Aggregations describing the current state of the TaskRun table, for monitoring gauges."""

    runs_in_status: list[TaskRunGaugeRow] = Field(default_factory=list)
    oldest_open_age_seconds: list[TaskRunGaugeRow] = Field(default_factory=list)
    created_recently: list[TaskRunGaugeRow] = Field(default_factory=list)
    terminal_recently: list[TaskRunGaugeRow] = Field(default_factory=list)
