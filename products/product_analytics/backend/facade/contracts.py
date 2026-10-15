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

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataCheckMethod,
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
class SavedInsightDefinition:
    id: int
    short_id: str
    name: str | None
    query: dict[str, Any]


@dataclass(frozen=True)
class InsightDataCheck:
    key: InsightDataCheckKey
    level: InsightDataCheckLevel
    name: str
    # A statement that reads without the name next to it. A check with no result repeats the name.
    result: str
    fix: str | None = None
    action: InsightDataCheckAction | None = None
    method: InsightDataCheckMethod | None = None
    # The affected events in the insight's whole range, which is an estimate when `scaled` is true.
    events: int | None = None
    share: float | None = None
    scaled: bool = False


@dataclass(frozen=True)
class InsightDataCheckedPeriod:
    date_from: date
    date_to: date


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
    days_checked: int
    checked_periods: list[InsightDataCheckedPeriod]
    filters_test_accounts: bool
    # Scaled up from the sample and the checked days, so it is exact only when both cover every event.
    events_in_range: int | None
    sample: InsightDataChecksSample | None


@dataclass(frozen=True)
class InsightDataChecks:
    status: InsightDataChecksStatus
    checks: list[InsightDataCheck]
    coverage: InsightDataChecksCoverage | None
