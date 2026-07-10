"""
Contract types for stamphog.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib
variant — same syntax, same ``is_dataclass()`` compatibility (so
``DataclassSerializer`` keeps working), but with runtime type
validation on construction.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field
from pydantic.dataclasses import dataclass

from .enums import ReviewRunStatus, ReviewVerdict


@dataclass(frozen=True)
class RepoConfigDTO:
    """A repository stamphog is configured to review for a team."""

    id: UUID
    team_id: int
    provider: str
    repository: str
    enabled: bool
    installation_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ReviewRunDTO:
    """A single stamphog review of a pull request."""

    id: UUID
    team_id: int
    repo_config_id: UUID
    repository: str
    pr_number: int
    pr_url: str
    head_sha: str
    head_branch: str
    status: ReviewRunStatus
    verdict: ReviewVerdict
    delivery_id: str | None = None
    gate_result: dict | None = None
    output: dict = Field(default_factory=dict)
    error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
