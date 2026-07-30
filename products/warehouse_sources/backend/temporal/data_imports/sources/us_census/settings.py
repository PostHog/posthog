import dataclasses

from products.warehouse_sources.backend.types import IncrementalField

CENSUS_API_BASE_URL = "https://api.census.gov/data"

# Documented API cap on the number of variables per `get=` clause.
MAX_VARIABLES_PER_QUERY = 50

# Schema name for the user-defined query built from the source's custom_* config fields.
CUSTOM_QUERY_ENDPOINT = "CustomQuery"

# Cheap probe used by validate_credentials: one variable, one row per state.
VALIDATION_DATASET = "2024/acs/acs5"
VALIDATION_GEOGRAPHY = "us:*"


@dataclasses.dataclass(frozen=True)
class CensusEndpoint:
    dataset: str
    """Vintage/dataset path under api.census.gov/data, e.g. "2024/acs/acs5"."""
    variables: tuple[str, ...]
    """Census variable codes for the `get=` clause. The API also returns the geography id columns."""
    geography: str
    """`for=` geography clause, e.g. "state:*"."""
    primary_keys: tuple[str, ...]
    """Geography (plus any predicate) columns that uniquely identify a row."""
    predicates: tuple[tuple[str, str], ...] = ()
    """Extra filter params appended to the query, e.g. (("NAICS2017", "00"),)."""


_ACS5_DATASET = "2024/acs/acs5"
_ACS5_VARIABLES = (
    "NAME",
    "B01001_001E",  # total population
    "B01002_001E",  # median age
    "B19013_001E",  # median household income
    "B19301_001E",  # per capita income
    "B25077_001E",  # median home value
    "B23025_003E",  # civilian labor force
    "B23025_005E",  # unemployed
    "B15003_022E",  # bachelor's degree holders (25+)
)

_DECENNIAL_DATASET = "2020/dec/pl"
_DECENNIAL_VARIABLES = (
    "NAME",
    "P1_001N",  # total population
    "H1_001N",  # total housing units
)

ENDPOINTS: dict[str, CensusEndpoint] = {
    "AcsDemographicsByState": CensusEndpoint(
        dataset=_ACS5_DATASET,
        variables=_ACS5_VARIABLES,
        geography="state:*",
        primary_keys=("state",),
    ),
    "AcsDemographicsByCounty": CensusEndpoint(
        dataset=_ACS5_DATASET,
        variables=_ACS5_VARIABLES,
        geography="county:*",
        primary_keys=("state", "county"),
    ),
    "DecennialPopulationByState": CensusEndpoint(
        dataset=_DECENNIAL_DATASET,
        variables=_DECENNIAL_VARIABLES,
        geography="state:*",
        primary_keys=("state",),
    ),
    "DecennialPopulationByCounty": CensusEndpoint(
        dataset=_DECENNIAL_DATASET,
        variables=_DECENNIAL_VARIABLES,
        geography="county:*",
        primary_keys=("state", "county"),
    ),
    "CountyBusinessPatternsByState": CensusEndpoint(
        dataset="2023/cbp",
        variables=("NAME", "NAICS2017", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN"),
        geography="state:*",
        # NAICS2017 is a "default displayed" predicate; pin it to 00 (total for all
        # sectors) so the row grain stays one row per state across API changes.
        primary_keys=("state", "NAICS2017"),
        predicates=(("NAICS2017", "00"),),
    ),
    "PopulationEstimatesByState": CensusEndpoint(
        dataset="2021/pep/population",
        variables=("NAME", "POP_2021", "DENSITY_2021"),
        geography="state:*",
        primary_keys=("state",),
    ),
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "AcsDemographicsByState": "American Community Survey 5-year estimates (2020-2024) of population, income, housing, employment, and education for every US state.",
    "AcsDemographicsByCounty": "American Community Survey 5-year estimates (2020-2024) of population, income, housing, employment, and education for every US county.",
    "DecennialPopulationByState": "2020 Decennial Census (PL 94-171) population and housing unit counts for every US state.",
    "DecennialPopulationByCounty": "2020 Decennial Census (PL 94-171) population and housing unit counts for every US county.",
    "CountyBusinessPatternsByState": "County Business Patterns (2023) establishment, employment, and payroll totals for every US state.",
    "PopulationEstimatesByState": "Population Estimates Program (vintage 2021) population and density for every US state.",
    CUSTOM_QUERY_ENDPOINT: "Your own query against any Census dataset, built from the custom query fields on the source.",
}

# Census datasets are versioned by vintage and expose no server-side created/updated
# timestamp filters, so every table is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
