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

from .enums import ChannelResolutionSource, DigestRunStatus, ReviewRunStatus, ReviewVerdict


@dataclass(frozen=True)
class RepoConfigDTO:
    """A repository stamphog is configured to review for a team."""

    id: UUID
    team_id: int
    provider: str
    repository: str
    enabled: bool
    installation_id: str
    digest_enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class MergedPullRequestDTO:
    """A merged pull request captured for the digest."""

    id: UUID
    team_id: int
    repo_config_id: UUID
    repository: str
    pr_number: int
    pr_url: str
    title: str
    author_login: str
    merged_at: datetime
    merge_commit_sha: str
    head_branch: str
    additions: int
    deletions: int
    changed_files: int
    body_excerpt: str
    audience_key: str
    digest_run_id: UUID | None = None
    delivery_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class DigestChannelDTO:
    """A Slack destination for one digest audience."""

    id: UUID
    team_id: int
    audience_key: str
    slack_integration_id: int
    slack_channel_id: str
    slack_channel_name: str
    enabled: bool
    resolution_source: ChannelResolutionSource = ChannelResolutionSource.MANUAL
    last_digest_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class DigestRunDTO:
    """One posted (or attempted) daily digest for a channel."""

    id: UUID
    team_id: int
    digest_channel_id: UUID
    status: DigestRunStatus
    pr_count: int
    summary: dict = Field(default_factory=dict)
    slack_message_ts: str = ""
    error: str = ""
    created_at: datetime | None = None
    posted_at: datetime | None = None


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
