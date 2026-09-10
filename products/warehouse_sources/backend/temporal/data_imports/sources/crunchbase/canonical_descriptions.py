"""Canonical, documentation-sourced descriptions for Crunchbase endpoints and columns.

Sourced from the official Crunchbase Data API v4 reference
(https://data.crunchbase.com/docs). Keyed by the endpoint names in `settings.py`
`CRUNCHBASE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Crunchbase table.
Column names mirror the `field_ids` requested per collection in `settings.py`. Columns absent here
fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by every Crunchbase entity; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "uuid": "Unique identifier for the entity.",
    "identifier": "Human-readable reference to the entity, including its name and permalink.",
    "created_at": "Date and time the entity was created in Crunchbase.",
    "updated_at": "Date and time the entity was last updated in Crunchbase.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "A company or organization profile in Crunchbase.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            short_description="Brief summary of what the organization does.",
            website_url="Primary website URL of the organization.",
            founded_on="Date the organization was founded.",
            categories="Industry categories the organization belongs to.",
            location_identifiers="Locations associated with the organization (city, region, country).",
            funding_total="Total funding the organization has raised across all rounds.",
            num_employees_enum="Bucketed range of the organization's employee count.",
            operating_status="Operating status of the organization (e.g. active, closed).",
        ),
    },
    "people": {
        "description": "A person profile in Crunchbase, such as a founder, executive, or investor.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            first_name="First name of the person.",
            last_name="Last name of the person.",
        ),
    },
    "funding_rounds": {
        "description": "A funding round raised by an organization in Crunchbase.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            announced_on="Date the funding round was announced.",
            investment_type="Type of the funding round (e.g. seed, series_a, series_b).",
            money_raised="Total amount of money raised in the funding round.",
            funded_organization_identifier="The organization that raised the funding round.",
            num_investors="Number of investors that participated in the funding round.",
        ),
    },
    "acquisitions": {
        "description": "An acquisition of one organization by another in Crunchbase.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            announced_on="Date the acquisition was announced.",
            acquirer_identifier="The organization that made the acquisition.",
            acquiree_identifier="The organization that was acquired.",
            price="Price paid for the acquisition.",
        ),
    },
    "investments": {
        "description": "An investment made by an investor into a funding round in Crunchbase.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            announced_on="Date the investment was announced.",
            investor_identifier="The investor that made the investment.",
            funding_round_identifier="The funding round the investment was part of.",
            money_invested="Amount of money invested.",
        ),
    },
    "ipos": {
        "description": "An initial public offering (IPO) by an organization in Crunchbase.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            went_public_on="Date the organization went public.",
            stock_symbol="Stock ticker symbol assigned at the IPO.",
            money_raised="Amount of money raised in the IPO.",
            valuation="Valuation of the organization at the IPO.",
        ),
    },
    "funds": {
        "description": "A fund raised by an investment firm in Crunchbase.",
        "docs_url": "https://data.crunchbase.com/docs/crunchbase-basic-getting-started",
        "columns": _columns(
            announced_on="Date the fund was announced.",
            money_raised="Total amount of money raised by the fund.",
            name="Name of the fund.",
        ),
    },
}
