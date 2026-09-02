from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Categories": {
        "description": "The categories your organization tracks. Every report is scoped to one category.",
        "docs_url": "https://docs.tryprofound.com/api-reference/organization/get-categories",
        "columns": {
            "id": "Unique identifier for the category, used as `category_id` on every report row.",
            "name": "Display name of the category.",
            "internal_name": "Internal name Profound uses for the category.",
            "organization": "The organization the category belongs to.",
        },
    },
    "Models": {
        "description": "The answer engines Profound queries on your behalf, such as ChatGPT or Perplexity.",
        "docs_url": "https://docs.tryprofound.com/api-reference/organization/get-models",
        "columns": {
            "id": "Unique identifier for the model.",
            "name": "Display name of the model.",
        },
    },
    "Regions": {
        "description": "The regions prompts are run from.",
        "docs_url": "https://docs.tryprofound.com/api-reference/organization/get-regions",
        "columns": {
            "id": "Unique identifier for the region.",
            "name": "Display name of the region.",
        },
    },
    "Domains": {
        "description": "The domains your organization tracks citations for.",
        "docs_url": "https://docs.tryprofound.com/api-reference/organization/get-domains",
        "columns": {
            "id": "Unique identifier for the domain.",
            "name": "The domain name.",
            "created_at": "When the domain was added.",
            "organization": "The organization the domain belongs to.",
        },
    },
    "Assets": {
        "description": "The brands tracked in each category, both the ones you own and the competitors you rank against.",
        "docs_url": "https://docs.tryprofound.com/api-reference/organization/get-assets",
        "columns": {
            "id": "Unique identifier for the asset.",
            "name": "Display name of the brand.",
            "website": "Primary website for the brand.",
            "alternate_domains": "Other domains that count as this brand.",
            "is_owned": "Whether this is one of your own brands rather than a competitor.",
            "logo_url": "Link to the brand's logo.",
            "created_at": "When the asset was added.",
            "category": "The category the asset is tracked in.",
            "organization": "The organization the asset belongs to.",
        },
    },
    "Personas": {
        "description": "The audience profiles prompts are run as, one row per persona and category.",
        "docs_url": "https://docs.tryprofound.com/api-reference/organization/get-personas",
        "columns": {
            "id": "Unique identifier for the persona.",
            "name": "Display name of the persona.",
            "persona": "The persona profile, covering behavior, employment, and demographics.",
            "category": "The category the persona is used in.",
            "organization": "The organization the persona belongs to.",
        },
    },
    "Visibility": {
        "description": "Daily brand visibility per category: how often each brand appears in AI answers, with share of voice and average position.",
        "docs_url": "https://docs.tryprofound.com/rest-api/reports/query-visibility-v2",
        "columns": {
            "category_id": "The category this row was measured in, stamped on from the request.",
            "date": "The day the metrics cover.",
            "asset_name": "Name of the brand the row measures.",
            "asset_owned": "Whether the brand is one of your own rather than a competitor.",
            "rank": "Position of the brand against the others in the category.",
            "visibility_score": "Share of answers the brand appeared in.",
            "share_of_voice": "Share of all brand mentions that went to this brand.",
            "average_position": "Average rank of the brand when it was mentioned. Lower is better.",
        },
    },
    "Citations": {
        "description": "Daily citation counts per category: which domains AI answers cited, and how large a share each took.",
        "docs_url": "https://docs.tryprofound.com/rest-api/reports/query-citations-v2",
        "columns": {
            "category_id": "The category this row was measured in, stamped on from the request.",
            "date": "The day the metrics cover.",
            "domain": "The cited domain.",
            "rank": "Position of the domain against the others cited in the category.",
            "count": "Number of citations the domain received.",
            "citation_share": "Share of citations that went to this domain, averaged per model.",
        },
    },
}
