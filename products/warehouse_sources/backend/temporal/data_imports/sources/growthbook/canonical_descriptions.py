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
    "teams": {"description": "Teams with their members, global roles, project roles, and environment access."},
    "namespaces": {
        "description": "Namespaces that split traffic so experiments in the same namespace stay mutually exclusive."
    },
    "holdouts": {
        "description": "Holdouts that keep a persistent control group out of features and experiments, with their linked experiments, features, and lifecycle stage."
    },
    "experiment_results": {
        "description": "The latest completed results snapshot for each experiment, with per-variation metric results and analysis settings.",
        "docs_url": "https://docs.growthbook.io/api/",
        "columns": {
            "id": "Unique identifier of the results snapshot.",
            "experimentId": "ID of the experiment the snapshot belongs to.",
            "phase": "Experiment phase the snapshot analyzes.",
            "dateStart": "Start of the analysis window.",
            "dateEnd": "End of the analysis window.",
            "dateUpdated": "When the snapshot was last updated.",
            "results": "Results per dimension, with total users, the sample ratio mismatch check, and metric analyses for each variation.",
        },
    },
}
