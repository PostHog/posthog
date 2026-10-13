from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Companies": {
        "description": "Companies matching the configured search term (and optional jurisdiction), aggregated from official national company registries.",
        "docs_url": "https://api.opencorporates.com/documentation/API-Reference#companies-search",
        "columns": {
            "name": "The current registered name of the company.",
            "company_number": "The company's identifier as issued by its registry. Unique within a jurisdiction, not globally.",
            "jurisdiction_code": "The jurisdiction the company is registered in, e.g. `gb` or `us_de`.",
            "company_type": "The type of the company, as defined by the company register.",
            "current_status": "The current status of the company, as defined by the company register.",
            "inactive": "Whether OpenCorporates considers the company inactive.",
            "incorporation_date": "The date the company was incorporated.",
            "dissolution_date": "The date the company was dissolved, if applicable.",
            "branch": "Whether the company is a branch of a company registered elsewhere.",
            "branch_status": "The status of the branch relationship, if `branch` is true.",
            "created_at": "When the company record was added to OpenCorporates.",
            "updated_at": "When the company record was last updated on OpenCorporates. The record is considered updated when any associated data changes.",
            "retrieved_at": "When the underlying registry data was last retrieved.",
            "opencorporates_url": "The canonical OpenCorporates URL for the company.",
            "previous_names": "Names the company has previously been registered under.",
            "registered_address_in_full": "The company's registered address as a single string.",
            "registry_url": "A link to the company's record on its source registry, if available.",
            "source": "The registry that published this data, including publisher name and license terms.",
        },
    },
    "Officers": {
        "description": "Officers (directors, secretaries, and agents) matching the configured search term (and optional jurisdiction).",
        "docs_url": "https://api.opencorporates.com/documentation/API-Reference#officers-search",
        "columns": {
            "id": "The officer's OpenCorporates-wide identifier.",
            "name": "The officer's name.",
            "position": "The position held, e.g. director, secretary, or CEO.",
            "uid": "The identifier given to the officer by the company registry.",
            "start_date": "The date the officership started.",
            "end_date": "The date the officership ended, if applicable.",
            "address": "The officer's address, if known.",
            "date_of_birth": "The officer's date of birth, if known.",
            "opencorporates_url": "The canonical OpenCorporates URL for the officer.",
        },
    },
}
