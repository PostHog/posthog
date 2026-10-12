from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every row carries `analysis_timestamp`, a derived ISO 8601 UTC timestamp of when PageSpeed Insights
# ran the Lighthouse analysis (parsed from the API's `analysisUTCTimestamp`). Each sync produces a
# fresh analysis, so this value never changes for a given row and doubles as the append cursor and a
# stable partition key.
_ANALYSIS_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "analysis_timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "analysis_timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class PageSpeedEndpointConfig:
    name: str
    # PageSpeed Insights runs the analysis under one device profile per request; each strategy is
    # modelled as its own table so a user can sync only the profiles they care about (each call is a
    # full, several-second Lighthouse run, so halving the profiles halves the quota spend).
    strategy: Literal["DESKTOP", "MOBILE"]
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_ANALYSIS_INCREMENTAL_FIELDS))
    # `analysis_timestamp` alone is not unique table-wide because rows aggregate across every configured
    # URL, so the requested URL is part of the key.
    primary_keys: list[str] = field(default_factory=lambda: ["requested_url", "analysis_timestamp"])
    # Stable datetime column used for partitioning (derived from the response's analysis timestamp).
    partition_key: str = "analysis_timestamp"
    should_sync_default: bool = True
    description: str | None = None


PAGESPEED_ENDPOINTS: dict[str, PageSpeedEndpointConfig] = {
    "pagespeed_desktop": PageSpeedEndpointConfig(
        name="pagespeed_desktop",
        strategy="DESKTOP",
        description="PageSpeed Insights / Lighthouse analysis under the desktop profile for each "
        "configured URL. One row per URL per sync; use append sync to accumulate a time series of scores.",
    ),
    "pagespeed_mobile": PageSpeedEndpointConfig(
        name="pagespeed_mobile",
        strategy="MOBILE",
        description="PageSpeed Insights / Lighthouse analysis under the mobile profile for each "
        "configured URL. One row per URL per sync; use append sync to accumulate a time series of scores.",
    ),
}

ENDPOINTS = tuple(PAGESPEED_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PAGESPEED_ENDPOINTS.items()
}
