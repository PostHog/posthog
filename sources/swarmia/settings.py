from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Swarmia's Export API returns time-windowed aggregate reports (CSV), not paginated entity lists.
# Each endpoint is synced by iterating fixed, complete windows (ISO weeks, calendar months, or
# years) so a row's identity — its window bounds plus its grouping columns — is stable across runs.

WindowStyle = Literal["week", "month", "year"]
TimeframeParamStyle = Literal["date_range", "month", "year"]

_END_DATE_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "end_date",
        "type": IncrementalFieldType.Date,
        "field": "end_date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class SwarmiaEndpointConfig:
    name: str
    path: str
    window: WindowStyle
    # How the window is passed to the API: startDate/endDate (YYYY-MM-DD), month=YYYY-MM, or year=YYYY.
    timeframe_param: TimeframeParamStyle
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # How far back the first sync (or a full refresh) reaches, in days.
    default_lookback_days: int = 365
    # Partition key for incremental endpoints; a window's start date never changes.
    partition_key: Optional[str] = None
    # Re-read window applied to the incremental watermark at schema creation. Swarmia recomputes
    # recent report data (e.g. FTE-based reports are generated ~10th of the following month, and a
    # late-registered incident can restate a past window's change failure rate), so incremental runs
    # re-pull a trailing window; merge dedupes on the primary key.
    default_incremental_lookback_seconds: Optional[int] = None
    # capex/employees returns one column per month of the year; unpivot those into
    # {employee_id, name, email, month, fte} rows so the table schema is year-independent.
    unpivot_month_columns: bool = False
    description: Optional[str] = None


SWARMIA_ENDPOINTS: dict[str, SwarmiaEndpointConfig] = {
    "pull_requests": SwarmiaEndpointConfig(
        name="pull_requests",
        path="/reports/pullRequests",
        window="week",
        timeframe_param="date_range",
        primary_keys=["start_date", "end_date", "team"],
        incremental_fields=_END_DATE_INCREMENTAL,
        partition_key="start_date",
        default_incremental_lookback_seconds=14 * 24 * 60 * 60,
        description="Per-team pull request metrics (cycle time, review rate, merge time), one row per team per complete ISO week",
    ),
    "dora": SwarmiaEndpointConfig(
        name="dora",
        path="/reports/dora",
        window="week",
        timeframe_param="date_range",
        primary_keys=["start_date", "end_date"],
        incremental_fields=_END_DATE_INCREMENTAL,
        partition_key="start_date",
        default_incremental_lookback_seconds=14 * 24 * 60 * 60,
        description="Organization-level DORA metrics (deployment frequency, change lead time, change failure rate, MTTR), one row per complete ISO week",
    ),
    "investment": SwarmiaEndpointConfig(
        name="investment",
        path="/reports/investment",
        window="month",
        timeframe_param="date_range",
        primary_keys=["start_date", "end_date", "investment_category"],
        incremental_fields=_END_DATE_INCREMENTAL,
        partition_key="start_date",
        # FTE data for a month is generated ~10th of the following month and can be regenerated.
        default_incremental_lookback_seconds=45 * 24 * 60 * 60,
        description="Investment balance (FTE months per investment category), one row per category per complete calendar month. Data for a month is available around the 10th of the following month",
    ),
    "capex": SwarmiaEndpointConfig(
        name="capex",
        path="/reports/capex",
        window="month",
        timeframe_param="date_range",
        primary_keys=["month", "employee_id", "capitalizable_work"],
        default_lookback_days=730,
        description="Software capitalization report, one row per employee per capitalizable issue per complete calendar month. Full refresh only: Swarmia regenerates FTE data and the issue title is not a stable identifier",
    ),
    "capex_employees": SwarmiaEndpointConfig(
        name="capex_employees",
        path="/reports/capex/employees",
        window="year",
        timeframe_param="year",
        primary_keys=["month", "employee_id"],
        default_lookback_days=1095,
        unpivot_month_columns=True,
        description="Total FTEs per employee per month for software capitalization, unpivoted to one row per employee per month",
    ),
    "fte": SwarmiaEndpointConfig(
        name="fte",
        path="/reports/fte",
        window="month",
        timeframe_param="month",
        primary_keys=["month", "author_id", "issue_key"],
        default_lookback_days=730,
        description="Effort report (FTE per author per issue), one row per author per issue per complete calendar month. Full refresh only: Swarmia regenerates FTE data for past months",
    ),
}

ENDPOINTS = tuple(SWARMIA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SWARMIA_ENDPOINTS.items()
}
