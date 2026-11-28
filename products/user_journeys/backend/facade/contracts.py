"""
Contract types for user_journeys.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field
from pydantic.dataclasses import dataclass

from .enums import (
    JourneyDeploySkipReason,
    JourneyDeployStatus,
    JourneyRunStatus,
    JourneyRunStepStatus,
    JourneyRunTrigger,
    JourneySource,
    JourneyStepFailureReason,
    JourneyVisualChange,
    UrlMatching,
)

MIN_STEPS = 2
MAX_STEPS = 20
MAX_URL_LENGTH = 2048
MAX_SELECTOR_LENGTH = 1024
MAX_TEXT_LENGTH = 400
MIN_CONVERSION_WINDOW_MINUTES = 1
# Steps are matched within one session, and a session ends after 24 hours at most.
MAX_CONVERSION_WINDOW_MINUTES = 24 * 60
DEFAULT_CONVERSION_WINDOW_MINUTES = 30


class JourneyNotFoundError(Exception):
    pass


@dataclass(frozen=True, kw_only=True)
class PageviewStep:
    type: Literal["pageview"] = "pageview"
    url: str
    url_matching: UrlMatching = UrlMatching.EXACT


@dataclass(frozen=True, kw_only=True)
class ElementClickStep:
    type: Literal["element_click"] = "element_click"
    selector: str
    text: str | None = None
    href: str | None = None
    url: str | None = None
    url_matching: UrlMatching = UrlMatching.EXACT


JourneyStep = Annotated[PageviewStep | ElementClickStep, Field(discriminator="type")]


@dataclass(frozen=True)
class Journey:
    id: UUID
    team_id: int
    name: str
    description: str
    steps: list[JourneyStep]
    conversion_window_minutes: int
    source: JourneySource
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime
    start_url: str | None = None


@dataclass(frozen=True)
class CreateJourneyInput:
    name: str
    steps: list[JourneyStep]
    description: str = ""
    conversion_window_minutes: int = DEFAULT_CONVERSION_WINDOW_MINUTES
    source: JourneySource = JourneySource.MANUAL
    start_url: str | None = None


@dataclass(frozen=True)
class UpdateJourneyInput:
    """Fields left as None keep their stored value."""

    name: str | None = None
    description: str | None = None
    steps: list[JourneyStep] | None = None
    conversion_window_minutes: int | None = None
    source: JourneySource | None = None
    # An empty string clears the stored start URL, because None already means "keep it".
    start_url: str | None = None


DEFAULT_ELEMENT_PATH_STEPS = 2
MAX_ELEMENT_PATH_STEPS = 4
DEFAULT_ELEMENT_PATHS = 10
MAX_ELEMENT_PATHS = 25
MAX_ELEMENT_PATHS_RANGE_DAYS = 31


class ElementPathsQueryError(Exception):
    """The element paths request can't run, for example because its date range is too long."""


@dataclass(frozen=True, kw_only=True)
class ElementPathsQuery:
    """Find the most common paths that sessions take through clicks on one element."""

    anchor: ElementClickStep
    date_from: str = "-7d"
    date_to: str | None = None
    steps_before: int = DEFAULT_ELEMENT_PATH_STEPS
    steps_after: int = DEFAULT_ELEMENT_PATH_STEPS
    limit: int = DEFAULT_ELEMENT_PATHS
    filter_test_accounts: bool = False


@dataclass(frozen=True, kw_only=True)
class ElementPathNode:
    label: str
    is_anchor: bool
    step: JourneyStep
    # False when `step` can match events that this node did not aggregate, or miss some that it did.
    step_is_exact: bool


@dataclass(frozen=True, kw_only=True)
class ElementPath:
    session_count: int
    share_of_anchor_sessions: float
    anchor_index: int
    nodes: list[ElementPathNode]


@dataclass(frozen=True, kw_only=True)
class ElementPathsResult:
    date_from: datetime
    date_to: datetime
    anchor_click_count: int
    anchor_session_count: int
    analyzed_session_count: int
    paths: list[ElementPath]


DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 800
MIN_VIEWPORT_SIDE = 320
MAX_VIEWPORT_WIDTH = 1920
MAX_VIEWPORT_HEIGHT = 1200
MAX_COMMIT_SHA_LENGTH = 64
MAX_BRANCH_LENGTH = 255


class JourneyRunNotFoundError(Exception):
    pass


class JourneyNotRunnableError(Exception):
    """The journey can't be run as it is, for example because it has no URL to start from."""


class JourneyRunTargetNotAllowedError(Exception):
    """A URL the run would load is outside what the project allows a run to visit."""


class JourneyRunInProgressError(Exception):
    """Another run of the same journey hasn't finished yet."""


@dataclass(frozen=True, kw_only=True)
class CreateJourneyRunInput:
    journey_id: UUID
    trigger: JourneyRunTrigger = JourneyRunTrigger.MANUAL
    base_url: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT
    created_by_id: int | None = None
    deploy_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class JourneyRun:
    id: UUID
    team_id: int
    journey_id: UUID
    trigger: JourneyRunTrigger
    status: JourneyRunStatus
    start_url: str | None
    base_url: str | None
    commit_sha: str | None
    branch: str | None
    viewport_width: int
    viewport_height: int
    error: str | None
    baseline_run_id: UUID | None
    created_by_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    deploy_id: UUID | None
    # Position of the first failed step, from 0, and why it failed. None unless a step failed.
    failed_step_index: int | None
    failure_reason: JourneyStepFailureReason | None


@dataclass(frozen=True, kw_only=True)
class JourneyRunStep:
    index: int
    # The step as it was defined when the run started, so a later edit of the journey keeps this history.
    step: JourneyStep
    status: JourneyRunStepStatus
    failure_reason: JourneyStepFailureReason | None
    message: str
    screenshot_url: str | None
    baseline_screenshot_url: str | None
    diff_screenshot_url: str | None
    diff_percentage: float | None
    visual_change: JourneyVisualChange | None
    duration_ms: int | None


@dataclass(frozen=True, kw_only=True)
class JourneyRunDetail(JourneyRun):
    steps: list[JourneyRunStep]


@dataclass(frozen=True, kw_only=True)
class JourneyLatestRun:
    journey_id: UUID
    run_id: UUID
    status: JourneyRunStatus
    created_at: datetime
    finished_at: datetime | None
    # Position of the first failed step, from 0. None unless the run failed on a step.
    failed_step_index: int | None


@dataclass(frozen=True, kw_only=True)
class JourneyWithLatestRun(Journey):
    """A journey as the app shows it, with its newest run, or None when it never ran."""

    latest_run: JourneyLatestRun | None


# A deploy starts one run per journey, so this bounds the browser sessions one request can queue.
MAX_JOURNEYS_PER_DEPLOY = 50
# A second deploy of the same commit and base URL inside this window returns the first one, so a CI
# step that retries after a timeout doesn't start every journey twice.
DEPLOY_IDEMPOTENCY_WINDOW_MINUTES = 10
MAX_DEPLOY_LABEL_LENGTH = 255


class JourneyDeployNotFoundError(Exception):
    pass


@dataclass(frozen=True, kw_only=True)
class CreateJourneyDeployInput:
    commit_sha: str
    branch: str | None = None
    base_url: str | None = None
    # None means the time the deploy is recorded.
    deployed_at: datetime | None = None
    label: str | None = None
    url: str | None = None
    # None runs every journey of the project, up to `MAX_JOURNEYS_PER_DEPLOY`.
    journey_ids: list[UUID] | None = None
    created_by_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class JourneyDeploy:
    id: UUID
    team_id: int
    commit_sha: str
    branch: str | None
    base_url: str | None
    label: str | None
    url: str | None
    deployed_at: datetime
    created_at: datetime
    created_by_id: int | None
    status: JourneyDeployStatus
    run_count: int
    # Journeys that weren't considered because the project has more than `MAX_JOURNEYS_PER_DEPLOY`.
    journeys_over_limit: int


@dataclass(frozen=True, kw_only=True)
class JourneyDeployRun:
    journey_id: UUID
    journey_name: str
    run_id: UUID
    status: JourneyRunStatus
    finished_at: datetime | None
    failed_step_index: int | None
    failure_reason: JourneyStepFailureReason | None
    # The failed step's message, or why an errored run couldn't finish. Empty otherwise.
    message: str


@dataclass(frozen=True, kw_only=True)
class JourneyDeploySkip:
    journey_id: UUID
    # None when the journey doesn't exist in the project.
    journey_name: str | None
    reason: JourneyDeploySkipReason
    message: str


@dataclass(frozen=True, kw_only=True)
class JourneyDeployDetail(JourneyDeploy):
    runs: list[JourneyDeployRun]
    skipped: list[JourneyDeploySkip]


@dataclass(frozen=True, kw_only=True)
class RecordedJourneyDeploy:
    deploy: JourneyDeployDetail
    # False when a retry within the idempotency window returned an earlier deploy.
    created: bool
