from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

ADMOB_HOST = "https://admob.googleapis.com"

# Every call the source makes (accounts, apps, ad units, both reports) accepts the read-only scope.
REQUIRED_SCOPES = "https://www.googleapis.com/auth/admob.readonly"

# The report endpoints accept up to 100,000 rows per request and drop the rest without an error.
ADMOB_MAX_REPORT_ROWS = 100_000

# A full 100,000-row response takes several hundred MB in memory, so each request asks for fewer
# rows. A response that fills this budget is treated as truncated, and the sync asks again for a
# smaller slice.
REPORT_ROW_BUDGET = 20_000

# Rows per yielded batch, so one response never reaches the pipeline as a single large batch.
YIELD_CHUNK_ROWS = 5_000

# When one day still fills the row budget, the day is split by these dimensions, in this order.
SPLIT_DIMENSIONS = ("APP", "COUNTRY")

# Metrics for the small report that lists the values of a split dimension. A row with activity in
# the full report has ad requests, impressions or earnings.
SPLIT_VALUE_METRICS = ("AD_REQUESTS", "IMPRESSIONS", "ESTIMATED_EARNINGS")

# `apps.list` and `adUnits.list` return up to 10,000 items when no page size is set.
LIST_PAGE_SIZE = 10_000

# A report request covers at most this many days. When a window fills the row budget or times out,
# the sync halves it. A window that comes back well under the budget doubles again, up to this size.
REPORT_WINDOW_DAYS = 7

# AdMob keeps revising estimated earnings for several days, so each incremental run re-reads a
# trailing window instead of keeping a day at its first value.
REVISION_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

# The first sync reads this far back when the user does not set a start date.
DEFAULT_LOOKBACK_DAYS = 365

# AdMob launched in 2006, so an earlier start date only adds empty requests.
MIN_START_DATE = "2006-01-01"

NETWORK_REPORT = "network_report"
MEDIATION_REPORT = "mediation_report"
APPS = "apps"
AD_UNITS = "ad_units"

DATE_FIELD = "date"


@frozen
class AdMobReportConfig:
    name: str
    # The path segment after `accounts/{publisher_id}/`.
    method: str
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]

    @property
    def primary_keys(self) -> list[str]:
        return [dimension.lower() for dimension in self.dimensions]


# AD_TYPE is left out of the network report, because AdMob rejects it with AD_REQUESTS,
# MATCH_RATE and IMPRESSION_RPM.
ADMOB_REPORTS: dict[str, AdMobReportConfig] = {
    NETWORK_REPORT: AdMobReportConfig(
        name=NETWORK_REPORT,
        method="networkReport:generate",
        dimensions=("DATE", "APP", "AD_UNIT", "COUNTRY", "FORMAT", "PLATFORM"),
        metrics=(
            "AD_REQUESTS",
            "CLICKS",
            "ESTIMATED_EARNINGS",
            "IMPRESSIONS",
            "IMPRESSION_CTR",
            "IMPRESSION_RPM",
            "MATCHED_REQUESTS",
            "MATCH_RATE",
            "SHOW_RATE",
        ),
    ),
    MEDIATION_REPORT: AdMobReportConfig(
        name=MEDIATION_REPORT,
        method="mediationReport:generate",
        dimensions=("DATE", "APP", "AD_UNIT", "AD_SOURCE", "MEDIATION_GROUP", "COUNTRY", "FORMAT", "PLATFORM"),
        metrics=(
            "AD_REQUESTS",
            "CLICKS",
            "ESTIMATED_EARNINGS",
            "IMPRESSIONS",
            "IMPRESSION_CTR",
            "MATCHED_REQUESTS",
            "MATCH_RATE",
            "OBSERVED_ECPM",
        ),
    ),
}


@frozen
class AdMobListConfig:
    name: str
    # The path segment after `accounts/{publisher_id}/`.
    method: str
    # The key of the item list in the response body.
    items_key: str
    primary_key: str


ADMOB_LISTS: dict[str, AdMobListConfig] = {
    APPS: AdMobListConfig(name=APPS, method="apps", items_key="apps", primary_key="app_id"),
    AD_UNITS: AdMobListConfig(name=AD_UNITS, method="adUnits", items_key="adUnits", primary_key="ad_unit_id"),
}

DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": DATE_FIELD,
        "type": IncrementalFieldType.DateTime,
        "field": DATE_FIELD,
        "field_type": IncrementalFieldType.DateTime,
    }
]
