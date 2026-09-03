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

from .enums import ChannelResolutionSource, DigestRunStatus, ReviewRunStatus, ReviewTrigger, ReviewVerdict


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
    review_mode: str = ""
    trigger_label: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PullRequestDTO:
    """A pull request stamphog knows about, including merge state once it merges."""

    id: UUID
    team_id: int
    repo_config_id: UUID
    repository: str
    pr_number: int
    pr_url: str
    title: str
    author_login: str
    head_branch: str
    body_excerpt: str
    additions: int
    deletions: int
    changed_files: int
    merge_commit_sha: str = ""
    merged_at: datetime | None = None
    posted_comment_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class DigestRunDTO:
    """One posted (or attempted) daily digest: one audience, one destination, one day."""

    id: UUID
    team_id: int
    audience_key: str
    slack_channel_id: str
    slack_channel_name: str
    resolution_source: ChannelResolutionSource
    status: DigestRunStatus
    pr_count: int
    summary: dict = Field(default_factory=dict)
    slack_message_ts: str = ""
    error: str = ""
    created_at: datetime | None = None
    posted_at: datetime | None = None


@dataclass(frozen=True)
class ReviewRunDTO:
    """A single stamphog review attempt against a pull request."""

    id: UUID
    team_id: int
    pull_request_id: UUID
    # Convenience PR context sourced via the pull_request FK.
    repository: str
    pr_number: int
    pr_url: str
    head_branch: str
    head_sha: str
    status: ReviewRunStatus
    verdict: ReviewVerdict
    # Why stamphog looked at this PR at all. Derived rather than stored — see the facade's
    # trigger helpers, which own both the derivation and the matching filter.
    trigger: ReviewTrigger
    title: str = ""
    author_login: str = ""
    delivery_id: str | None = None
    gate_result: dict | None = None
    output: dict = Field(default_factory=dict)
    error: str = ""
    posted_review_id: int | None = None
    verdict_posted_at: datetime | None = None
    approval_dismissed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class RepoAlreadyClaimedError(Exception):
    """Another team already owns this repository under this GitHub installation."""


class StamphogGitHubError(Exception):
    """A Stamphog GitHub API call failed for a non-rate-limit reason (auth failure, unexpected status,
    malformed response). Rate limits raise ``GitHubRateLimitError`` from the egress layer instead."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
