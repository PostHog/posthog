"""Canonical, documentation-sourced descriptions for Vendr endpoints and columns.

Sourced from the official Vendr developer docs (https://developers.vendr.com/api/catalog-api).
Keyed by the resource names in `settings.py` `VENDR_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Vendr table. Columns absent here fall back to LLM
enrichment - the docs page renders parameter/response schemas without expandable nested object
fields (e.g. `pagination`, `category`, `defaultPriceRange`), so coverage here is intentionally
partial rather than guessed.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Companies": {
        "description": "A software vendor in Vendr's catalog, with the product families and products it sells.",
        "docs_url": "https://developers.vendr.com/api/catalog-api",
        "columns": {
            "id": "Unique identifier for the company.",
            "name": "Display name of the company.",
            "legalName": "Company's registered legal name.",
            "domain": "Primary domain of the company's website.",
            "description": "Description of the company and what it sells.",
            "discontinued": "Whether the company (and its products) is discontinued.",
            "lastUpdatedAt": "Time the catalog entry was last updated by Vendr.",
            "url": "URL of the company's website.",
            "icon": "URL of the company's logo.",
            "fiscalYearEnd": "Month the company's fiscal year ends.",
            "realPurchaseCount": "Number of real, verified purchases behind this catalog entry.",
        },
    },
    "Categories": {
        "description": "A product category in Vendr's catalog, used to classify companies and products.",
        "docs_url": "https://developers.vendr.com/api/catalog-api",
        "columns": {
            "id": "Unique identifier for the category.",
            "name": "Display name of the category.",
        },
    },
    "ProductFamilies": {
        "description": "A group of related products sold by the same company (e.g. editions of one product line).",
        "docs_url": "https://developers.vendr.com/api/catalog-api",
        "columns": {
            "id": "Unique identifier for the product family.",
            "name": "Display name of the product family.",
            "lastUpdatedAt": "Time the catalog entry was last updated by Vendr.",
            "company_id": "Identifier of the company this product family belongs to.",
        },
    },
    "Products": {
        "description": "A single product sold by a company, with its pricing tiers and add-ons.",
        "docs_url": "https://developers.vendr.com/api/catalog-api",
        "columns": {
            "id": "Unique identifier for the product.",
            "name": "Display name of the product.",
            "description": "Description of the product.",
            "isCustomEstimateAvailable": "Whether a custom price estimate is available for this product via the Pricing API.",
            "lastUpdatedAt": "Time the catalog entry was last updated by Vendr.",
            "productFamilyId": "Identifier of the product family this product belongs to, if any.",
            "icon": "URL of the product's icon.",
            "url": "URL of the product's page.",
            "currency": "Currency of the product's default price.",
            "company_id": "Identifier of the company this product belongs to.",
        },
    },
}
