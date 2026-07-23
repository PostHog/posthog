from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

REPORTS_PATH = "/api/reports/by-user-client-date"
CREDITS_PATH = "/api/credits"


@dataclass
class CodyEndpointConfig:
    name: str
    path: str
    # Value for the reports endpoint's `granularity` query param; None for non-report endpoints.
    granularity: Optional[str] = None
    # Whether syncs chunk the fetch into calendar-month startDate/endDate windows. Only valid for
    # day-grain granularities — windowing an aggregate report (e.g. by_user) would turn its
    # all-time totals into per-window totals and change the table's meaning.
    windowed: bool = False
    # The Analytics API filters server-side on startDate/endDate, but the CSV column names
    # (including the date column an incremental cursor would track) aren't documented, so every
    # endpoint ships full refresh until the response schema can be verified against a live token.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    description: Optional[str] = None
    should_sync_default: bool = True


CODY_ENDPOINTS: dict[str, CodyEndpointConfig] = {
    "usage_by_user": CodyEndpointConfig(
        name="usage_by_user",
        path=REPORTS_PATH,
        granularity="by_user",
        description="All-time usage totals per user (searches, chats, completions, acceptance rates). Full refresh only",
        should_sync_default=False,
    ),
    "usage_by_user_month": CodyEndpointConfig(
        name="usage_by_user_month",
        path=REPORTS_PATH,
        granularity="by_user_month",
        description="Monthly usage totals per user. Full refresh only",
        should_sync_default=False,
    ),
    "usage_by_user_day": CodyEndpointConfig(
        name="usage_by_user_day",
        path=REPORTS_PATH,
        granularity="by_user_day",
        windowed=True,
        description="Daily usage totals per user. Full refresh only",
        should_sync_default=False,
    ),
    "usage_by_user_day_client_language": CodyEndpointConfig(
        name="usage_by_user_day_client_language",
        path=REPORTS_PATH,
        granularity="by_user_day_client_language",
        windowed=True,
        description="Daily usage per user, split by client/editor and programming language (the most detailed report). Full refresh only",
    ),
    "credits": CodyEndpointConfig(
        name="credits",
        path=CREDITS_PATH,
        description="Credit bucket allocations and consumption for the instance. Full refresh only",
    ),
}

ENDPOINTS = tuple(CODY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CODY_ENDPOINTS.items()
}
