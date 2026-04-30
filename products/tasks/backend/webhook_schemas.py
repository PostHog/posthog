from pydantic import BaseModel, ConfigDict, Field


# Lenient on missing/unknown fields, fail-fast on type mismatch.
# We model only the subset of GitHub webhook payloads that PostHog reads —
# every field defaults so that minimal test fixtures and partial deliveries
# parse cleanly. Type mismatches still raise ValidationError at the dispatcher.
class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Repository(_Base):
    full_name: str | None = None


class PullRequestHead(_Base):
    ref: str | None = None


class PullRequestRef(_Base):
    html_url: str | None = None
    merged: bool = False
    head: PullRequestHead = Field(default_factory=PullRequestHead)


class IssueRef(_Base):
    pull_request: PullRequestRef | None = None


class CheckRunPullRequest(_Base):
    url: str | None = None


class CheckRun(_Base):
    name: str | None = None
    conclusion: str | None = None
    pull_requests: list[CheckRunPullRequest] = Field(default_factory=list)


class PullRequestEvent(_Base):
    action: str | None = None
    pull_request: PullRequestRef = Field(default_factory=PullRequestRef)
    repository: Repository = Field(default_factory=Repository)


# Covers issue_comment, pull_request_review_comment, and pull_request_review.
# All three share the relevant shape — either a top-level pull_request, or
# an issue with a nested pull_request reference.
class CommentEvent(_Base):
    action: str | None = None
    pull_request: PullRequestRef | None = None
    issue: IssueRef | None = None


class CheckRunEvent(_Base):
    action: str | None = None
    check_run: CheckRun = Field(default_factory=CheckRun)
    repository: Repository = Field(default_factory=Repository)
