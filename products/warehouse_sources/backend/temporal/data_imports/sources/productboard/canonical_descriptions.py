"""Canonical, documentation-sourced descriptions for Productboard endpoints and columns.

Sourced from the official Productboard API reference (https://developer.productboard.com/reference).
Keyed by the endpoint names in `settings.py` `PRODUCTBOARD_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Productboard table. Most endpoints are served by the generic
`/entities` resource and share a common shape. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by Productboard entity objects (served via the `/entities` resource).
_ENTITY_COLUMNS = {
    "id": "Unique identifier for the entity.",
    "name": "The entity's name.",
    "description": "The entity's description.",
    "createdAt": "Time at which the entity was created.",
    "updatedAt": "Time at which the entity was last updated.",
}


def _entity_columns(**overrides: str) -> dict[str, str]:
    return {**_ENTITY_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "features": {
        "description": "A feature in Productboard — a unit of product work being planned or built.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            status="The feature's current status (e.g. candidate, planned, in progress, done).",
            type="The feature's type.",
            owner="The user who owns the feature.",
            parent="The parent entity (component or product) the feature belongs to.",
        ),
    },
    "subfeatures": {
        "description": "A sub-feature nested under a feature in Productboard.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            status="The sub-feature's current status.",
            owner="The user who owns the sub-feature.",
            parent="The parent feature the sub-feature belongs to.",
        ),
    },
    "components": {
        "description": "A component in Productboard — a grouping of features within a product.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            owner="The user who owns the component.",
            parent="The product the component belongs to.",
        ),
    },
    "products": {
        "description": "A product in Productboard's product hierarchy.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            owner="The user who owns the product.",
        ),
    },
    "initiatives": {
        "description": "An initiative in Productboard — a strategic effort grouping related work.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            status="The initiative's current status.",
            owner="The user who owns the initiative.",
        ),
    },
    "objectives": {
        "description": "An objective in Productboard representing a measurable goal.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            status="The objective's current status.",
            owner="The user who owns the objective.",
        ),
    },
    "key_results": {
        "description": "A key result tracking progress toward an objective in Productboard.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            owner="The user who owns the key result.",
            parent="The objective the key result belongs to.",
        ),
    },
    "releases": {
        "description": "A release in Productboard grouping features to be shipped together.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            state="The release's state (e.g. planned, in progress, released).",
            timeframe="The release's planned timeframe.",
            parent="The release group the release belongs to.",
        ),
    },
    "release_groups": {
        "description": "A release group in Productboard organizing related releases.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(),
    },
    "companies": {
        "description": "A company in Productboard, used to attribute feedback to customer accounts.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            domain="The company's domain name.",
        ),
    },
    "users": {
        "description": "A user (maker) in the Productboard workspace.",
        "docs_url": "https://developer.productboard.com/reference/get-entities",
        "columns": _entity_columns(
            email="The user's email address.",
            role="The user's role in the workspace.",
        ),
    },
    "notes": {
        "description": "A piece of customer feedback (note) captured in Productboard.",
        "docs_url": "https://developer.productboard.com/reference/get-notes",
        "columns": {
            "id": "Unique identifier for the note.",
            "title": "The note's title.",
            "content": "The note's content.",
            "state": "The note's state (e.g. unprocessed, processed, archived).",
            "displayUrl": "URL to view the note in Productboard.",
            "tags": "Tags applied to the note.",
            "company": "The company the note's feedback is attributed to, if any.",
            "user": "The end user the feedback came from, if any.",
            "owner": "The user who owns the note.",
            "source": "Where the note originated from (e.g. email, integration).",
            "createdAt": "Time at which the note was created.",
            "updatedAt": "Time at which the note was last updated.",
            "createdBy": "The maker who created the note.",
        },
    },
    "members": {
        "description": "A member of the Productboard workspace.",
        "docs_url": "https://developer.productboard.com/reference/get-members",
        "columns": {
            "id": "Unique identifier for the member.",
            "name": "The member's name.",
            "email": "The member's email address.",
            "role": "The member's role in the workspace.",
        },
    },
    "teams": {
        "description": "A team in the Productboard workspace.",
        "docs_url": "https://developer.productboard.com/reference/get-teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "The team's name.",
            "createdAt": "Time at which the team was created.",
            "updatedAt": "Time at which the team was last updated.",
        },
    },
}
