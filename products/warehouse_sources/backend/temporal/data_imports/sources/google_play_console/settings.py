from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Play aggregates vitals per calendar day (it also exposes HOURLY, but the user-weighted
# release-quality metrics teams care about are the daily ones).
AGGREGATION_PERIOD = "DAILY"

# Days of history requested on a first sync. The Reporting API keeps roughly a year of daily
# vitals; error reports are retained for a much shorter window, so they start closer to today.
METRIC_SET_HISTORY_DAYS = 180
ERROR_HISTORY_DAYS = 30

# Play keeps revising the most recent days of vitals (and the 7d/28d rolling metrics move with
# them), so an incremental run re-reads a trailing week and merges the corrected rows.
METRIC_SET_LOOKBACK_SECONDS = 7 * 24 * 60 * 60
# Error reports are immutable events, but a run interrupted part-way through a day may have
# advanced the watermark past rows it never fetched, so re-read the day.
ERROR_REPORT_LOOKBACK_SECONDS = 24 * 60 * 60

# Days requested per metric-set query. Rows are buffered per window and yielded oldest day
# first, so the window trades request count against how much is held in memory at once.
METRIC_SET_WINDOW_DAYS = 30

IntervalMode = Literal["none", "trailing", "daily"]


@dataclass(frozen=True)
class MetricSetEndpoint:
    """One `apps/{app}/<resource>:query` metric set exposed as a table."""

    name: str
    resource: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class ListEndpoint:
    """One paginated collection endpoint exposed as a table."""

    name: str
    # Path under the API root; `{app}` is substituted with the package name when `per_app`.
    path: str
    # Key the rows live under in the response body.
    data_key: str
    primary_key: tuple[str, ...]
    per_app: bool
    description: str
    # "none": no time filter. "trailing": one request covering the whole history window.
    # "daily": one request per day, walking the window oldest day first.
    interval_mode: IntervalMode = "none"
    # Cursor field, when the endpoint's time filter makes incremental sync real.
    incremental_field: str | None = None
    # Top-level fields carrying a google.type.DateTime / RFC 3339 timestamp to coerce.
    datetime_fields: tuple[str, ...] = ()


# Every vitals metric set is sliced by `versionCode` only. Play drops rows whose user counts fall
# under its privacy threshold, and each extra dimension multiplies the slices, so a wider default
# breakdown would silently lose data on smaller apps.
_VERSION_CODE = ("versionCode",)

METRIC_SETS: dict[str, MetricSetEndpoint] = {
    "crash_rate": MetricSetEndpoint(
        name="crash_rate",
        resource="crashRateMetricSet",
        metrics=(
            "crashRate",
            "crashRate7dUserWeighted",
            "crashRate28dUserWeighted",
            "userPerceivedCrashRate",
            "userPerceivedCrashRate7dUserWeighted",
            "userPerceivedCrashRate28dUserWeighted",
            "distinctUsers",
        ),
        dimensions=_VERSION_CODE,
        description="Daily crash rate from Android vitals, broken out by app version.",
    ),
    "anr_rate": MetricSetEndpoint(
        name="anr_rate",
        resource="anrRateMetricSet",
        metrics=(
            "anrRate",
            "anrRate7dUserWeighted",
            "anrRate28dUserWeighted",
            "userPerceivedAnrRate",
            "userPerceivedAnrRate7dUserWeighted",
            "userPerceivedAnrRate28dUserWeighted",
            "distinctUsers",
        ),
        dimensions=_VERSION_CODE,
        description="Daily ANR (application not responding) rate, broken out by app version.",
    ),
    "excessive_wakeup_rate": MetricSetEndpoint(
        name="excessive_wakeup_rate",
        resource="excessiveWakeupRateMetricSet",
        metrics=(
            "excessiveWakeupRate",
            "excessiveWakeupRate7dUserWeighted",
            "excessiveWakeupRate28dUserWeighted",
            "distinctUsers",
        ),
        dimensions=_VERSION_CODE,
        description="Daily rate of sessions waking the device more than twice an hour.",
    ),
    "stuck_background_wakelock_rate": MetricSetEndpoint(
        name="stuck_background_wakelock_rate",
        resource="stuckBackgroundWakelockRateMetricSet",
        metrics=(
            "stuckBgWakelockRate",
            "stuckBgWakelockRate7dUserWeighted",
            "stuckBgWakelockRate28dUserWeighted",
            "distinctUsers",
        ),
        dimensions=_VERSION_CODE,
        description="Daily rate of sessions holding a background wakelock for over an hour.",
    ),
    "slow_start_rate": MetricSetEndpoint(
        name="slow_start_rate",
        resource="slowStartRateMetricSet",
        metrics=(
            "slowStartRate",
            "slowStartRate7dUserWeighted",
            "slowStartRate28dUserWeighted",
            "distinctUsers",
        ),
        # `startType` splits cold, warm, and hot starts, which have different thresholds — the
        # combined rate is not meaningful.
        dimensions=("startType", "versionCode"),
        description="Daily rate of slow app starts, broken out by start type and app version.",
    ),
    "slow_rendering_rate": MetricSetEndpoint(
        name="slow_rendering_rate",
        resource="slowRenderingRateMetricSet",
        metrics=(
            "slowRenderingRate20Fps",
            "slowRenderingRate20Fps7dUserWeighted",
            "slowRenderingRate20Fps28dUserWeighted",
            "slowRenderingRate30Fps",
            "slowRenderingRate30Fps7dUserWeighted",
            "slowRenderingRate30Fps28dUserWeighted",
            "distinctUsers",
        ),
        dimensions=_VERSION_CODE,
        description="Daily rate of sessions with slow frame rendering, broken out by app version.",
    ),
    "lmk_rate": MetricSetEndpoint(
        name="lmk_rate",
        resource="lmkRateMetricSet",
        metrics=(
            "userPerceivedLmkRate",
            "userPerceivedLmkRate7dUserWeighted",
            "userPerceivedLmkRate28dUserWeighted",
            "distinctUsers",
        ),
        dimensions=_VERSION_CODE,
        description="Daily rate of low-memory kills the user perceived, broken out by app version.",
    ),
    "error_counts": MetricSetEndpoint(
        name="error_counts",
        resource="errorCountMetricSet",
        metrics=("errorReportCount", "distinctUsers"),
        dimensions=("reportType", "versionCode"),
        description="Daily error report counts, broken out by report type and app version.",
    ),
}

LIST_ENDPOINTS: dict[str, ListEndpoint] = {
    "apps": ListEndpoint(
        name="apps",
        path="apps:search",
        data_key="apps",
        primary_key=("packageName",),
        per_app=False,
        description="Apps the connected service account can report on.",
    ),
    "error_issues": ListEndpoint(
        name="error_issues",
        path="apps/{app}/errorIssues:search",
        data_key="errorIssues",
        primary_key=("name",),
        per_app=True,
        interval_mode="trailing",
        datetime_fields=("lastErrorReportTime", "firstErrorReportTime"),
        description="Clustered crash, ANR, and non-fatal issues with their report and user counts.",
    ),
    "error_reports": ListEndpoint(
        name="error_reports",
        path="apps/{app}/errorReports:search",
        data_key="errorReports",
        primary_key=("name",),
        per_app=True,
        interval_mode="daily",
        incremental_field="eventTime",
        datetime_fields=("eventTime",),
        description="Individual crash, ANR, and non-fatal error reports, including stack traces.",
    ),
    "anomalies": ListEndpoint(
        name="anomalies",
        path="apps/{app}/anomalies",
        data_key="anomalies",
        primary_key=("name",),
        per_app=True,
        description="Metric anomalies Play detected against its expected range.",
    ),
}

ENDPOINTS: tuple[str, ...] = (*METRIC_SETS, *LIST_ENDPOINTS)

PRIMARY_KEYS: dict[str, list[str]] = {
    # A metric row is identified by the app, the day, and the slice it aggregates — the
    # package name is part of the key because one source syncs every app the account can see.
    **{name: ["app", "date", *endpoint.dimensions] for name, endpoint in METRIC_SETS.items()},
    **{name: list(endpoint.primary_key) for name, endpoint in LIST_ENDPOINTS.items()},
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{name: [incremental_field("date", IncrementalFieldType.Date)] for name in METRIC_SETS},
    "error_reports": [incremental_field("eventTime", IncrementalFieldType.DateTime)],
}

DESCRIPTIONS: dict[str, str] = {
    **{name: endpoint.description for name, endpoint in METRIC_SETS.items()},
    **{name: endpoint.description for name, endpoint in LIST_ENDPOINTS.items()},
}

LOOKBACK_SECONDS: dict[str, int] = {
    **dict.fromkeys(METRIC_SETS, METRIC_SET_LOOKBACK_SECONDS),
    "error_reports": ERROR_REPORT_LOOKBACK_SECONDS,
}

# Play restates recent metric days, so appending would keep both the old and corrected rows.
MERGE_ONLY: tuple[str, ...] = tuple(METRIC_SETS)
