import dataclasses

from products.warehouse_sources.backend.types import IncrementalField

BEA_API_BASE_URL = "https://apps.bea.gov/api/data"

CUSTOM_QUERY_ENDPOINT = "CustomQuery"

# Cheap probe used by validate_credentials: GetParameterList needs only UserID + DatasetName,
# no table/geography/year selection.
VALIDATION_DATASET_NAME = "Regional"


@dataclasses.dataclass(frozen=True)
class BeaEndpointConfig:
    dataset_name: str
    """BEA `DatasetName` GetData parameter, e.g. "Regional"."""
    table_name: str
    """BEA `TableName` GetData parameter, e.g. "SAINC1"."""
    line_codes: tuple[str, ...]
    """Documented `LineCode` values for this table. The Regional dataset accepts only one
    LineCode per request (MultipleAcceptedFlag=0), so the transport issues one GetData call
    per code and merges the results."""
    extra_params: dict[str, str]
    """Static GetData params beyond DatasetName/TableName/LineCode, e.g. GeoFips/Year."""
    primary_keys: tuple[str, ...]


# Both tables and their LineCode values are taken directly from BEA's own API user guide
# examples: SAINC1's GetParameterValuesFiltered example lists LineCode 1/2/3 as personal
# income/population/per capita personal income, and CAINC1's GetData example's PublicTable
# field ("CAINC1 County personal income summary: personal income, population, per capita
# personal income") shows the identical three-statistic layout for the county table.
ENDPOINTS: dict[str, BeaEndpointConfig] = {
    "StatePersonalIncomeSummary": BeaEndpointConfig(
        dataset_name="Regional",
        table_name="SAINC1",
        line_codes=("1", "2", "3"),
        # GeoFips=STATE covers every state plus a handful of BEA regions (~65 geographies),
        # so pairing it with Year=ALL stays well inside BEA's throttling limits.
        extra_params={"GeoFips": "STATE", "Year": "ALL"},
        primary_keys=("Code", "GeoFips", "TimePeriod"),
    ),
    "CountyPersonalIncomeSummary": BeaEndpointConfig(
        dataset_name="Regional",
        table_name="CAINC1",
        line_codes=("1", "2", "3"),
        # BEA advises against combining more than one "all values" wildcard in a request.
        # GeoFips=COUNTY already returns all ~3,100 counties, so Year is capped to the last
        # 10 years rather than ALL to avoid stacking a second wildcard on a multi-decade series.
        extra_params={"GeoFips": "COUNTY", "Year": "LAST10"},
        primary_keys=("Code", "GeoFips", "TimePeriod"),
    ),
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "StatePersonalIncomeSummary": "SAINC1 State annual personal income summary: personal income, population, per capita personal income, for every US state.",
    "CountyPersonalIncomeSummary": "CAINC1 County personal income summary: personal income, population, per capita personal income, for every US county (last 10 years).",
    CUSTOM_QUERY_ENDPOINT: "Rows returned by the custom BEA GetData query configured on this source (dataset name and parameters chosen by the user).",
}

# BEA has no updated-since filter. The `Year` GetData parameter selects which periods a
# request returns rather than filtering by modification time, and BEA revises recently
# published years on its own release schedule (independent of when we last synced), so every
# table is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
