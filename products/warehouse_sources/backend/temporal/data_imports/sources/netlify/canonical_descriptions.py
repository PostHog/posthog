"""Canonical, documentation-sourced descriptions for Netlify endpoints and columns.

Sourced from the official Netlify API reference (https://open-api.netlify.com/). Keyed by the
endpoint names in `settings.py` `NETLIFY_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Netlify table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sites": {
        "description": "A site hosted on Netlify, including its domains, SSL, and published deploy.",
        "docs_url": "https://open-api.netlify.com/#tag/site",
        "columns": {
            "id": "Unique identifier for the site.",
            "name": "The site's name (the subdomain on netlify.app).",
            "state": "Current state of the site.",
            "custom_domain": "The site's custom domain, if configured.",
            "url": "The site's primary URL.",
            "ssl_url": "The site's HTTPS URL.",
            "admin_url": "URL of the site's admin dashboard on Netlify.",
            "account_id": "Identifier of the account that owns the site.",
            "account_slug": "Slug of the account that owns the site.",
            "created_at": "Time at which the site was created.",
            "updated_at": "Time at which the site was last updated.",
            "published_deploy": "The currently published deploy for the site.",
        },
    },
    "deploys": {
        "description": "A deploy of a site: a build of the site's content published to Netlify.",
        "docs_url": "https://open-api.netlify.com/#tag/deploy",
        "columns": {
            "id": "Unique identifier for the deploy.",
            "site_id": "Identifier of the site this deploy belongs to.",
            "build_id": "Identifier of the build that produced this deploy.",
            "state": "Current state of the deploy (e.g. new, building, ready, error).",
            "name": "The site name at the time of the deploy.",
            "url": "URL the deploy is served from.",
            "branch": "The git branch the deploy was built from.",
            "commit_ref": "The git commit SHA the deploy was built from.",
            "error_message": "Error message if the deploy failed.",
            "created_at": "Time at which the deploy was created.",
            "updated_at": "Time at which the deploy was last updated.",
            "published_at": "Time at which the deploy was published.",
        },
    },
    "builds": {
        "description": "A build of a site, producing a deploy. Includes build status and errors.",
        "docs_url": "https://open-api.netlify.com/#tag/build",
        "columns": {
            "id": "Unique identifier for the build.",
            "site_id": "Identifier of the site this build belongs to (injected from the parent site).",
            "deploy_id": "Identifier of the deploy this build produced.",
            "sha": "The git commit SHA the build was triggered from.",
            "done": "Whether the build has finished.",
            "error": "Error message if the build failed.",
            "created_at": "Time at which the build was created.",
        },
    },
    "forms": {
        "description": "A form defined on a Netlify site that collects submissions.",
        "docs_url": "https://open-api.netlify.com/#tag/form",
        "columns": {
            "id": "Unique identifier for the form.",
            "site_id": "Identifier of the site this form belongs to.",
            "name": "The form's name.",
            "paths": "The site paths the form is available on.",
            "submission_count": "Total number of submissions received by the form.",
            "fields": "The form's fields.",
            "created_at": "Time at which the form was created.",
        },
    },
    "submissions": {
        "description": "A single submission to a Netlify form, including the submitted field data.",
        "docs_url": "https://open-api.netlify.com/#tag/submission",
        "columns": {
            "id": "Unique identifier for the submission.",
            "site_id": "Identifier of the site the submission belongs to (injected from the parent site).",
            "number": "Sequential number of the submission within its form.",
            "email": "Email address submitted, if present.",
            "name": "Name submitted, if present.",
            "summary": "A short summary of the submission.",
            "body": "The submission body.",
            "data": "The raw submitted field data as a key/value object.",
            "created_at": "Time at which the submission was received.",
        },
    },
    "dns_zones": {
        "description": "A DNS zone managed by Netlify for a domain.",
        "docs_url": "https://open-api.netlify.com/#tag/dnsZone",
        "columns": {
            "id": "Unique identifier for the DNS zone.",
            "name": "The zone's domain name.",
            "account_id": "Identifier of the account that owns the zone.",
            "account_slug": "Slug of the account that owns the zone.",
            "site_id": "Identifier of the site the zone is linked to, if any.",
            "dns_servers": "The zone's authoritative DNS servers.",
            "created_at": "Time at which the zone was created.",
            "updated_at": "Time at which the zone was last updated.",
        },
    },
    "accounts": {
        "description": "A Netlify account (team) the authenticated user is a member of.",
        "docs_url": "https://open-api.netlify.com/#tag/account",
        "columns": {
            "id": "Unique identifier for the account.",
            "name": "The account's name.",
            "slug": "The account's slug, used in account-scoped API paths.",
            "type": "The account's plan type.",
            "owner_ids": "Identifiers of the account's owners.",
            "created_at": "Time at which the account was created.",
            "updated_at": "Time at which the account was last updated.",
        },
    },
    "members": {
        "description": "A member of a Netlify account, fanned out one row per account.",
        "docs_url": "https://open-api.netlify.com/#tag/member",
        "columns": {
            "id": "Unique identifier for the member.",
            "account_slug": "Slug of the account this membership belongs to (injected from the parent account).",
            "full_name": "The member's full name.",
            "email": "The member's email address.",
            "role": "The member's role within the account.",
        },
    },
}
