from dataclasses import dataclass

# The Indicators API defaults to 50 rows per page and accepts values in the tens of thousands.
# 1000 keeps the indicator catalog (~30k rows) to ~30 requests without building huge pages.
PER_PAGE = 1000

# One row per country/period observation for a single indicator. Handled separately from the
# catalog endpoints below because its path carries a user-supplied indicator code.
INDICATOR_DATA_ENDPOINT = "indicator_data"


@dataclass(frozen=True)
class WorldBankEndpointConfig:
    name: str
    # Path relative to the versioned base URL (e.g. `https://api.worldbank.org/v2`).
    path: str
    primary_keys: list[str]
    description: str


CATALOG_ENDPOINTS: dict[str, WorldBankEndpointConfig] = {
    "countries": WorldBankEndpointConfig(
        name="countries",
        path="/country",
        # `id` is the ISO 3166-1 alpha-3 code (or the World Bank's own code for aggregates).
        primary_keys=["id"],
        description="Countries and aggregates, with their region, income level, lending type, and capital city.",
    ),
    "indicators": WorldBankEndpointConfig(
        name="indicators",
        path="/indicator",
        primary_keys=["id"],
        description="Catalog of every indicator series the API exposes, with its unit, source, and topics.",
    ),
    "sources": WorldBankEndpointConfig(
        name="sources",
        path="/source",
        primary_keys=["id"],
        description="Databases the indicator data comes from, such as World Development Indicators.",
    ),
    "topics": WorldBankEndpointConfig(
        name="topics",
        path="/topic",
        primary_keys=["id"],
        description="Subject areas indicators are grouped under, such as Health or Climate Change.",
    ),
    "regions": WorldBankEndpointConfig(
        name="regions",
        path="/region",
        # Rows carry an empty `id` for aggregate regions, so `code` is the only stable key.
        primary_keys=["code"],
        description="Geographic regions and regional aggregates used to group countries.",
    ),
    "income_levels": WorldBankEndpointConfig(
        name="income_levels",
        path="/incomeLevel",
        primary_keys=["id"],
        description="World Bank income classifications, such as high income or low income.",
    ),
    "lending_types": WorldBankEndpointConfig(
        name="lending_types",
        path="/lendingType",
        primary_keys=["id"],
        description="World Bank lending categories, such as IBRD, IDA, or blend.",
    ),
}

# One row per indicator, country, and period, so all three are needed for a table-wide unique key.
# `indicator_id` and `country_id` are lifted out of the nested objects the API returns.
INDICATOR_DATA_PRIMARY_KEYS = ["indicator_id", "country_id", "date"]

INDICATOR_DATA_DESCRIPTION = "Observations for every indicator code you configured, one row per country and period."

ENDPOINTS: tuple[str, ...] = (*CATALOG_ENDPOINTS.keys(), INDICATOR_DATA_ENDPOINT)

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    **{name: endpoint.description for name, endpoint in CATALOG_ENDPOINTS.items()},
    INDICATOR_DATA_ENDPOINT: INDICATOR_DATA_DESCRIPTION,
}

PRIMARY_KEYS: dict[str, list[str]] = {
    **{name: endpoint.primary_keys for name, endpoint in CATALOG_ENDPOINTS.items()},
    INDICATOR_DATA_ENDPOINT: INDICATOR_DATA_PRIMARY_KEYS,
}
