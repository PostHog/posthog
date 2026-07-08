from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from Vercel's public REST API reference (https://vercel.com/docs/rest-api/reference).
# Partial coverage is fine — any column not listed here falls back to LLM enrichment, which is
# given the source name, endpoint, docs_url, and column types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "deployments": {
        "description": "A Vercel deployment: a single build and release of a project, with its state, target environment, and URL.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/deployments/list-deployments",
        "columns": {
            "uid": "Unique identifier for the deployment.",
            "name": "Name of the project the deployment belongs to.",
            "url": "The deployment's unique URL (without the scheme).",
            "created": "Time the deployment was created, as a Unix timestamp in milliseconds.",
            "createdAt": "Time the deployment was created, as a Unix timestamp in milliseconds.",
            "state": "Current state of the deployment (e.g. BUILDING, READY, ERROR, CANCELED).",
            "readyState": "Readiness state of the deployment.",
            "type": "Deployment type (e.g. LAMBDAS).",
            "target": "Deployment target environment (e.g. production, staging, or null for preview).",
            "creator": "The user or team member who created the deployment.",
            "inspectorUrl": "URL of the deployment's inspector page in the Vercel dashboard.",
        },
    },
    "projects": {
        "description": "A Vercel project: a codebase connected to Vercel with its build, environment, and deployment configuration.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/projects/retrieve-a-list-of-projects",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Name of the project.",
            "accountId": "Identifier of the user or team that owns the project.",
            "createdAt": "Time the project was created, as a Unix timestamp in milliseconds.",
            "updatedAt": "Time the project was last updated, as a Unix timestamp in milliseconds.",
            "framework": "Framework preset configured for the project (e.g. nextjs).",
        },
    },
    "teams": {
        "description": "A Vercel team the access token can access.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/teams/list-all-teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "slug": "URL-friendly unique slug for the team.",
            "name": "Display name of the team.",
            "createdAt": "Time the team was created, as a Unix timestamp in milliseconds.",
        },
    },
    "domains": {
        "description": "A domain registered with or added to Vercel.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/domains/list-all-the-domains",
        "columns": {
            "id": "Unique identifier for the domain.",
            "name": "The domain name.",
            "createdAt": "Time the domain was added, as a Unix timestamp in milliseconds.",
            "verified": "Whether the domain has been verified.",
            "serviceType": "How the domain's DNS is served (e.g. zeit.world, external).",
        },
    },
    "aliases": {
        "description": "An alias mapping a custom or vercel.app URL to a specific deployment.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/aliases/list-aliases",
        "columns": {
            "uid": "Unique identifier for the alias.",
            "alias": "The aliased URL (without the scheme).",
            "created": "Time the alias was created, as a Unix timestamp in milliseconds.",
            "createdAt": "Time the alias was created, as a Unix timestamp in milliseconds.",
            "deployment": "The deployment the alias points to.",
            "deploymentId": "Identifier of the deployment the alias points to.",
        },
    },
}
