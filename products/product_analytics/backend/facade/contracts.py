"""
Cross-product contracts for product_analytics.

Stable, framework-free frozen dataclasses that define what this product hands to the rest of the
codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same syntax, same
``is_dataclass()`` compatibility, but with runtime validation on construction, so a mapper that
loses a field surfaces at the facade boundary instead of further down the caller's stack.

``Insight``, ``InsightVariable`` and the QueryRunner wiring still cross as classes
(``facade.models``, ``facade.queries``); as they convert, their contracts land here too.
"""

from dataclasses import field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataCheckMethod,
    InsightDataCheckSkipReason,
    InsightDataChecksStatus,
)


@dataclass(frozen=True)
class InsightVariableDefinition:
    """A saved query variable, as callers outside product analytics read it.

    ``type`` carries an ``InsightVariableType`` value. Comparing it to
    ``InsightVariableType.LIST`` works because the enum is a ``StrEnum``.
    """

    id: UUID
    name: str
    code_name: str | None
    type: str
    default_value: Any = None
    is_multi: bool = False


@dataclass(frozen=True)
class TrendsQueryRunResult:
    """The response fields consumers need from a blocking cached Trends query."""

    results: list[dict[str, Any]]
    last_refresh: datetime | None = None


@dataclass(frozen=True)
class TrendsActorsDateWindow:
    """The time window of the events that the actors of one Trends data point have.

    ``date_to`` is exclusive, unless ``date_to_inclusive`` is true.
    """

    date_from: datetime
    date_to: datetime
    date_to_inclusive: bool


@dataclass(frozen=True)
class SavedInsightDefinition:
    id: int
    short_id: str
    name: str | None
    query: dict[str, Any]


@dataclass(frozen=True)
class InsightDataCheckFilter:
    """A rule in the shape the project's internal and test users filter stores it."""

    key: str
    type: str
    operator: str
    value: list[str]


@dataclass(frozen=True)
class InsightDataCheck:
    key: InsightDataCheckKey
    level: InsightDataCheckLevel
    skip_reason: InsightDataCheckSkipReason | None = None
    method: InsightDataCheckMethod | None = None
    # The affected events on the checked days, scaled up from the sample when `scaled` is true.
    events: int | None = None
    share: float | None = None
    scaled: bool = False
    action: InsightDataCheckAction | None = None
    # The most affected values first, so a finding says what is affected as well as how much.
    top_events: list[str] = field(default_factory=list)
    top_hosts: list[str] = field(default_factory=list)
    distinct_hosts: int | None = None
    top_bots: list[str] = field(default_factory=list)
    distinct_bots: int | None = None
    # The internal users check's `events`, split into what the project's filter removes and what it keeps.
    removed_by_filter: int | None = None
    missed_by_filter: int | None = None
    top_emails: list[str] = field(default_factory=list)
    distinct_emails: int | None = None
    filter_to_add: InsightDataCheckFilter | None = None


@dataclass(frozen=True)
class InsightDataChecksSample:
    # The share of the events on the checked days that the sample reads.
    rate: float
    events: int
    distinct_ids: int


@dataclass(frozen=True)
class InsightDataChecksCoverage:
    date_from: date
    date_to: date
    days_in_range: int
    # The newest days of the range, which are all of it when the range is short.
    checked_date_from: date
    checked_date_to: date
    days_checked: int
    filters_test_accounts: bool
    # The events on the checked days, scaled up from the sample when the sample did not read every event.
    events_checked: int | None
    sample: InsightDataChecksSample | None


@dataclass(frozen=True)
class InsightDataChecks:
    status: InsightDataChecksStatus
    checks: list[InsightDataCheck]
    coverage: InsightDataChecksCoverage | None


@dataclass(frozen=True)
class SavedTrendsInsight:
    team_id: int
    insight_id: int
    # The trends interval, "day" when the query sets none.
    interval: str


@dataclass(frozen=True)
class ViewableInsight:
    id: int
    short_id: str
    # The saved name, else the generated one. None when the insight has neither.
    name: str | None


@dataclass(frozen=True)
class TeamEmailAccess:
    # A match reveals that an email belongs to the team, so each source needs the caller to be allowed to read it.
    member_emails: bool
    verified_domains: bool
    # The emails a check finds are person data, so the check names them only for a caller who may read persons.
    person_emails: bool


@dataclass(frozen=True)
class InsightSeries:
    short_id: str
    name: str | None
    series: dict[str, list[tuple[date, float]]]
    period: str
    averaged_series: list[str]
    event_name: str
    value_format: str | None = None
    value_prefix: str | None = None
    value_postfix: str | None = None
    decimal_places: int | None = None


@dataclass(frozen=True)
class InsightDashboardContext:
    filters: dict[str, Any]
    tile_filters: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrganizationEventsRetention:
    """The window an organization set for its projects, and the windows its admins can set, in months."""

    organization_months: int | None
    plan_months: int
    min_months: int
    max_months: int
