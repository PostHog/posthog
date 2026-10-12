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
    "events": {
        "description": "A Vercel team activity event: one action taken on the team, such as a deployment being created, a project renamed, or an environment variable changed. Where the other tables hold current state, this one holds the transitions between states.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/user/list-user-events",
        "columns": {
            "id": "Unique identifier for the event.",
            "type": "The type of action the event records, such as deployment-created or env-variable-edit.",
            "text": "Human-readable summary of the event.",
            "createdAt": "Time the event was generated, as a Unix timestamp in milliseconds.",
            "entities": "Spans within the event text marking the entities it refers to, as JSON.",
            "categories": "Categories grouping this event with related types. An event can belong to more than one.",
            "payload": "Event-specific detail about the entity acted on, as JSON. The shape varies by event type.",
            "principalId": "Identifier of the principal that generated the event, usually a user but sometimes an app or integration.",
            "userId": "Identifier of the user that generated the event, empty when the principal was not a user.",
            "user": "Metadata about the user that generated the event, as JSON.",
            "via": "Chain of principals the authority was delegated through, as JSON, when a user acted through an app.",
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
    "check_runs": {
        "description": "A Vercel check run: one pass/fail gate (a build check or CI integration) that ran against a deployment. Where a deployment's state only reports that it failed, check runs report which gate failed.",
        "docs_url": "https://vercel.com/docs/rest-api/reference/endpoints/checks-v2/list-check-runs-for-a-deployment",
        "columns": {
            "id": "Unique identifier for the check run.",
            "deploymentId": "Identifier of the deployment the check run ran against.",
            "name": "Display name of the check run.",
            "ownerId": "Identifier of the user or team that owns the check run.",
            "source": "Where the check run originated, such as the integration or Vercel CI that produced it.",
            "status": "Lifecycle state of the check run: registered, running, or completed.",
            "checkId": "Identifier of the project-level check definition this run belongs to. Absent for Vercel CI runs that have no parent check.",
            "timeout": "Time in milliseconds after which the check run is considered timed out.",
            "createdAt": "Time the check run was created, as a Unix timestamp in milliseconds.",
            "updatedAt": "Time the check run was last updated, as a Unix timestamp in milliseconds.",
        },
    },
    # Column keys are the normalized (snake_case) names the columns land under in the warehouse, not
    # the PascalCase FOCUS field names from the API.
    "billing_charges": {
        "description": "A team's billing usage and cost, one row per charge in the FOCUS v1.3 open cost-and-usage standard at 1-day granularity.",
        "docs_url": "https://vercel.com/docs/rest-api/billing/list-focus-billing-charges",
        "columns": {
            "id": "Surrogate key for the charge, derived from the charge period and its billing dimensions so it stays stable as the charge is restated.",
            "billed_cost": "Charge amount serving as the basis for invoicing.",
            "billing_currency": "Currency used for billing (ISO 4217), e.g. USD.",
            "charge_category": "Classification of the charge: Adjustment, Credit, Purchase, Tax, or Usage.",
            "charge_period_start": "Inclusive start of the charge period, as an ISO 8601 UTC timestamp.",
            "charge_period_end": "Exclusive end of the charge period, as an ISO 8601 UTC timestamp.",
            "consumed_quantity": "Volume of the resource consumed; null when the charge has no measurable quantity.",
            "consumed_unit": "Unit of measurement for the consumed quantity; null when not measured in units.",
            "effective_cost": "Amortized cost including discounts and pre-commitment credit purchase amounts.",
            "region_id": "Provider-assigned identifier for the region the charge applies to.",
            "region_name": "Display name for the region the charge applies to.",
            "service_name": "Display name for the Vercel service or product the charge is for.",
            "service_category": "High-level category of the service (e.g. Compute, Storage, Networking).",
            "service_provider_name": "Entity making the resource or service available for purchase.",
            "tags": "Charge metadata, including the Vercel ProjectId and ProjectName the charge relates to.",
            "pricing_category": "Pricing model used for the charge: Committed, Dynamic, Other, or Standard.",
            "pricing_currency": "Currency the pricing is expressed in (ISO 4217), e.g. USD.",
            "pricing_quantity": "Quantity the charge was priced on.",
            "pricing_unit": "Unit the pricing quantity is expressed in.",
        },
    },
}
