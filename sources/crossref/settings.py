from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

CROSSREF_BASE_URL = "https://api.crossref.org"

# Crossref caps `rows` (page size) at 1000 for every list endpoint.
MAX_PAGE_SIZE = 1000


@dataclass(frozen=True)
class CrossrefIncrementalOption:
    """One of Crossref's `from-<x>-date` filters, paired with the `sort=` value that returns
    rows in the matching ascending order. Cursor deep paging keeps whatever order the request
    asks for, but the pipeline's incremental watermark only advances correctly if that order
    matches `SourceResponse.sort_mode` — so an incremental sync must always request the sort
    that corresponds to its filter.
    """

    filter_prefix: str
    sort: str


# Only fields backed by a real per-item timestamp Crossref returns (`indexed`, `deposited`,
# `created`) are offered. `from-update-date` and `from-pub-date` also exist as request filters,
# but there's no matching item field to track a watermark against: publication dates are often
# year-only, and Crossref doesn't return a distinct "last updated" timestamp separate from
# `deposited`.
INCREMENTAL_OPTIONS: dict[str, CrossrefIncrementalOption] = {
    "indexed_date": CrossrefIncrementalOption(filter_prefix="from-index-date", sort="indexed"),
    "deposited_date": CrossrefIncrementalOption(filter_prefix="from-deposit-date", sort="deposited"),
    "created_date": CrossrefIncrementalOption(filter_prefix="from-created-date", sort="created"),
}


@dataclass(frozen=True)
class CrossrefEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Every list endpoint supports Crossref's cursor deep paging except /types, which always
    # returns its full ~30-row controlled vocabulary in one response and rejects a cursor param.
    supports_cursor: bool = True
    partition_key: str | None = None
    # Works alone needs a member/funder/ISSN scope: Crossref indexes 160M+ works, so syncing it
    # unscoped is impractical (see CrossrefSource.validate_credentials).
    requires_scope: bool = False
    description: str | None = None


ENDPOINTS: dict[str, CrossrefEndpointConfig] = {
    "Works": CrossrefEndpointConfig(
        name="Works",
        path="/works",
        primary_keys=["DOI"],
        incremental_fields=[
            incremental_field("indexed_date", label="Indexed date"),
            incremental_field("deposited_date", label="Deposited date"),
            incremental_field("created_date", label="Created date"),
        ],
        # `created_date` never changes after registration, unlike `indexed_date`/`deposited_date`
        # which advance every time Crossref re-processes the record.
        partition_key="created_date",
        requires_scope=True,
        description="Scholarly work metadata (DOIs, titles, authors, references) registered with Crossref.",
    ),
    "Members": CrossrefEndpointConfig(
        name="Members",
        path="/members",
        primary_keys=["id"],
        description="Publisher and society organizations that deposit metadata with Crossref.",
    ),
    "Funders": CrossrefEndpointConfig(
        name="Funders",
        path="/funders",
        primary_keys=["id"],
        description="Funding bodies in Crossref's Open Funder Registry, used to tag works with grant and funding information.",
    ),
    "Types": CrossrefEndpointConfig(
        name="Types",
        path="/types",
        primary_keys=["id"],
        supports_cursor=False,
        description="The controlled vocabulary of work types Crossref recognizes (journal-article, book-chapter, dataset, etc).",
    ),
    "Licenses": CrossrefEndpointConfig(
        name="Licenses",
        path="/licenses",
        primary_keys=["URL"],
        description="Distinct license URLs referenced by works, with a count of works that use each.",
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in ENDPOINTS.items()
}
