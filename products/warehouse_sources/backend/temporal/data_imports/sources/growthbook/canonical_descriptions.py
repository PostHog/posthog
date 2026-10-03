from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "features": {
        "description": "Feature flags with default values, targeting rules, environments, and revision metadata."
    },
    "experiments": {"description": "Experiments with hypotheses, variations, phases, analysis settings, and status."},
    "metrics": {
        "description": "Legacy metric definitions with data sources, query settings, and measurement behavior."
    },
    "fact_tables": {"description": "Fact table definitions with SQL, identifier columns, and data source references."},
    "fact_metrics": {
        "description": "Metrics built from fact tables, including numerator, denominator, and analysis settings."
    },
    "segments": {"description": "Reusable experiment populations defined by queries or fact table filters."},
    "dimensions": {"description": "Query-based dimensions for grouping experiment results."},
    "projects": {"description": "Projects that organize feature flags, experiments, and access settings."},
    "environments": {
        "description": "Feature flag environments and their default states, project scopes, and parent environments."
    },
    "saved_groups": {"description": "Reusable targeting groups defined by attribute values or conditions."},
    "data_sources": {"description": "Data source definitions with identifier types and experiment assignment queries."},
    "members": {"description": "Organization members with global roles, project roles, and environment access."},
}
