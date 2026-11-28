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

from .enums import JourneySource, UrlMatching

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


@dataclass(frozen=True)
class CreateJourneyInput:
    name: str
    steps: list[JourneyStep]
    description: str = ""
    conversion_window_minutes: int = DEFAULT_CONVERSION_WINDOW_MINUTES
    source: JourneySource = JourneySource.MANUAL


@dataclass(frozen=True)
class UpdateJourneyInput:
    """Fields left as None keep their stored value."""

    name: str | None = None
    description: str | None = None
    steps: list[JourneyStep] | None = None
    conversion_window_minutes: int | None = None
    source: JourneySource | None = None


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
