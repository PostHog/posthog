from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# OpenCorporates caps `per_page` at 100 and `page` at 100, so at most ~10,000 rows are reachable
# per search query — narrower jurisdiction/query scoping is required to go deeper.
PER_PAGE = 100
MAX_PAGE = 100


def _updated_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass(frozen=True)
class OpencorporatesEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: list[str]
    supports_incremental: bool
    # Stable creation-time field to partition by. None when the resource has no reliable created_at.
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    sends_query: bool = True
    sends_jurisdiction_code: bool = True
    paginated: bool = True
    # Rows wrapped in a single key (e.g. `{"jurisdiction": {...}}`) are unwrapped when present.
    item_key: str | None = None
    # Fan-out child of the company search: `path` holds `{jurisdiction_code}` and `{company_number}`.
    company_fanout: bool = False


OPENCORPORATES_ENDPOINTS: dict[str, OpencorporatesEndpointConfig] = {
    "Companies": OpencorporatesEndpointConfig(
        name="Companies",
        path="/companies/search",
        data_selector="results.companies[*].company",
        # jurisdiction_code + company_number is OpenCorporates' documented globally unique
        # company identifier (the pair used to build /companies/{jurisdiction}/{number} URLs).
        primary_keys=["jurisdiction_code", "company_number"],
        supports_incremental=True,
        partition_key="created_at",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "Officers": OpencorporatesEndpointConfig(
        name="Officers",
        path="/officers/search",
        data_selector="results.officers[*].officer",
        # `id` is the officer's OpenCorporates-wide identifier (distinct from `uid`, the
        # registry-issued id), so it's unique across the whole table.
        primary_keys=["id"],
        # officers/search documents no created_at/updated_at date filter, so this stays full refresh.
        supports_incremental=False,
    ),
    "Jurisdictions": OpencorporatesEndpointConfig(
        name="Jurisdictions",
        path="/jurisdictions",
        data_selector="results.jurisdictions",
        primary_keys=["code"],
        supports_incremental=False,
        sends_query=False,
        sends_jurisdiction_code=False,
        paginated=False,
        item_key="jurisdiction",
    ),
    "CompanyFilings": OpencorporatesEndpointConfig(
        name="CompanyFilings",
        path="/companies/{jurisdiction_code}/{company_number}/filings",
        data_selector="results.filings[*].filing",
        primary_keys=["company_jurisdiction_code", "company_number", "id"],
        # The filings endpoint documents no date filter.
        supports_incremental=False,
        company_fanout=True,
    ),
    "CompanyStatements": OpencorporatesEndpointConfig(
        name="CompanyStatements",
        path="/companies/{jurisdiction_code}/{company_number}/statements",
        data_selector="results.statements[*].statement",
        # One statement (e.g. a subsidiary relationship) can relate to several companies.
        primary_keys=["company_jurisdiction_code", "company_number", "id"],
        supports_incremental=False,
        company_fanout=True,
    ),
    "AlternateRegistrations": OpencorporatesEndpointConfig(
        name="AlternateRegistrations",
        path="/statements/alternate_registrations/search",
        data_selector="results.statements[*].statement",
        primary_keys=["id"],
        # Ordered by created_at, but the endpoint documents no date filter.
        supports_incremental=False,
        sends_jurisdiction_code=False,
    ),
    "SubsequentRegistrations": OpencorporatesEndpointConfig(
        name="SubsequentRegistrations",
        path="/statements/subsequent_registrations/search",
        data_selector="results.statements[*].statement",
        primary_keys=["id"],
        supports_incremental=False,
        sends_jurisdiction_code=False,
    ),
}

COMPANY_FANOUT_PARENT = "Companies"

ENDPOINTS = tuple(OPENCORPORATES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENCORPORATES_ENDPOINTS.items()
}
