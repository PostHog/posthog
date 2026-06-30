from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclass
class AppsFlyerEndpointConfig:
    name: str
    # Report slug in /api/agg-data/export/app/{app_id}/{report}/v5.
    report: str
    # Aggregate reports have no row ids; the dimension columns (normalized
    # headers) form the key, and collisions are tolerated via the duplicate-pk
    # flag.
    primary_keys: list[str] = field(
        default_factory=lambda: ["date", "agency_pmd_af_prt", "media_source_pid", "campaign_c"]
    )
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DATE_INCREMENTAL_FIELDS))


# AppsFlyer's aggregate Pull API returns CSV per date window (max ~1000 days);
# headers are normalized to snake_case columns. Raw-data Pull APIs require
# separate subscriptions and are a follow-up.
APPSFLYER_ENDPOINTS: dict[str, AppsFlyerEndpointConfig] = {
    "daily_report": AppsFlyerEndpointConfig(
        name="daily_report",
        report="daily_report",
    ),
    "geo_report": AppsFlyerEndpointConfig(
        name="geo_report",
        report="geo_by_date_report",
        primary_keys=["date", "agency_pmd_af_prt", "media_source_pid", "campaign_c", "country"],
    ),
    "partners_report": AppsFlyerEndpointConfig(
        name="partners_report",
        report="partners_by_date_report",
    ),
}

ENDPOINTS = tuple(APPSFLYER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPSFLYER_ENDPOINTS.items() if config.incremental_fields
}
