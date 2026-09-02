from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The API returns the full result set for a request with no default page cap, but $top is
# capped by the server at 1000. Paginate every endpoint at that cap to keep responses bounded --
# some indicators carry hundreds of thousands of observations.
PAGE_SIZE = 1000

INDICATORS_ENDPOINT = "indicators"
DIMENSIONS_ENDPOINT = "dimensions"
DIMENSION_VALUES_ENDPOINT = "dimension_values"
INDICATOR_DATA_ENDPOINT = "indicator_data"

# Querying every configured code walks its full observation history on every refresh, so bound
# the list to keep a single source from consuming worker and storage capacity indefinitely.
MAX_INDICATOR_CODES = 50

# Source-create probes one request per indicator code; cap how many are checked so the form
# stays responsive. Codes beyond the cap still sync -- an unknown one surfaces as a sync error.
MAX_VALIDATED_INDICATOR_CODES = 20


@dataclass(frozen=True)
class GHOEndpointConfig:
    name: str
    # Path relative to https://ghoapi.azureedge.net/api.
    path: str
    primary_keys: list[str]
    description: str


CATALOG_ENDPOINTS: dict[str, GHOEndpointConfig] = {
    INDICATORS_ENDPOINT: GHOEndpointConfig(
        name=INDICATORS_ENDPOINT,
        path="/Indicator",
        primary_keys=["IndicatorCode"],
        description="Catalog of every health indicator code the Global Health Observatory publishes.",
    ),
    DIMENSIONS_ENDPOINT: GHOEndpointConfig(
        name=DIMENSIONS_ENDPOINT,
        path="/DIMENSION",
        primary_keys=["Code"],
        description="Dimensions observations can be disaggregated by, such as country, sex, or age group.",
    ),
}

# One shared DIMENSION_VALUE entity backs every dimension's values -- the API declares Code as
# that entity's only key, so it is unique across the whole table. This differs from indicator
# observations below: each indicator code has its own entity type with its own Id sequence, so
# Id alone is only unique within one indicator, not across the indicators merged into one table.
DIMENSION_VALUES_PRIMARY_KEYS = ["Code"]
DIMENSION_VALUES_DESCRIPTION = (
    "Values for every dimension, such as country codes for the COUNTRY dimension "
    "or SEX_MLE / SEX_FMLE for the SEX dimension."
)

INDICATOR_DATA_PRIMARY_KEYS = ["IndicatorCode", "Id"]
INDICATOR_DATA_DESCRIPTION = (
    "Observations for every indicator code you configured, one row per country, year, and disaggregation."
)

ENDPOINTS: tuple[str, ...] = (*CATALOG_ENDPOINTS.keys(), DIMENSION_VALUES_ENDPOINT, INDICATOR_DATA_ENDPOINT)

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    **{name: endpoint.description for name, endpoint in CATALOG_ENDPOINTS.items()},
    DIMENSION_VALUES_ENDPOINT: DIMENSION_VALUES_DESCRIPTION,
    INDICATOR_DATA_ENDPOINT: INDICATOR_DATA_DESCRIPTION,
}

PRIMARY_KEYS: dict[str, list[str]] = {
    **{name: endpoint.primary_keys for name, endpoint in CATALOG_ENDPOINTS.items()},
    DIMENSION_VALUES_ENDPOINT: DIMENSION_VALUES_PRIMARY_KEYS,
    INDICATOR_DATA_ENDPOINT: INDICATOR_DATA_PRIMARY_KEYS,
}

# Every observation row on an indicator carries the same last-modified `Date` (the whole
# indicator's dataset is stamped as one unit whenever WHO republishes it), so filtering on it is
# an all-or-nothing decision per sync: unchanged since last time returns zero rows, changed
# returns the full set again for the merge to upsert. The catalog/reference endpoints have no
# comparable field, so they stay full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    INDICATOR_DATA_ENDPOINT: [
        {
            "label": "Date",
            "type": IncrementalFieldType.DateTime,
            "field": "Date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
