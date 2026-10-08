"""Canonical, documentation-sourced descriptions for Aha! endpoints and columns.

Sourced from the official Aha! API reference (https://www.aha.io/api). Keyed by the endpoint names
in `settings.py` `AHA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Aha! table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields common to most Aha! record types.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the record.",
    "reference_num": "Human-readable reference number (e.g. PRJ1-123).",
    "name": "The record's name.",
    "created_at": "Time at which the record was created.",
    "updated_at": "Time at which the record was last updated.",
    "url": "URL of the record in the Aha! web app.",
    "resource": "API URL of the record.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "A product (workspace) in your Aha! account that groups releases, features, and ideas.",
        "docs_url": "https://www.aha.io/api/resources/products",
        "columns": {
            "id": "Unique identifier for the product.",
            "reference_prefix": "Prefix used for reference numbers of records in this product.",
            "name": "The product's name.",
            "product_line": "Whether the product is a product line (container) rather than a leaf product.",
            "created_at": "Time at which the product was created.",
            "updated_at": "Time at which the product was last updated.",
        },
    },
    "features": {
        "description": "A feature in Aha! — a unit of work delivered as part of a release.",
        "docs_url": "https://www.aha.io/api/resources/features",
        "columns": {
            **_COMMON_COLUMNS,
            "workflow_status": "The feature's current status in its workflow.",
            "release_id": "Identifier of the release this feature belongs to.",
            "initiative": "The initiative this feature is associated with.",
            "epic": "The epic this feature is associated with.",
            "score": "The feature's score from the configured scorecard.",
            "progress": "Completion progress of the feature, as a percentage.",
            "start_date": "Planned start date for the feature.",
            "due_date": "Planned due date for the feature.",
            "assigned_to_user": "The user the feature is assigned to.",
        },
    },
    "epics": {
        "description": "An epic in Aha! — a large body of work that groups related features.",
        "docs_url": "https://www.aha.io/api/resources/epics",
        "columns": {
            **_COMMON_COLUMNS,
            "workflow_status": "The epic's current status in its workflow.",
            "release_id": "Identifier of the release this epic belongs to.",
            "initiative": "The initiative this epic is associated with.",
            "progress": "Completion progress of the epic, as a percentage.",
        },
    },
    "initiatives": {
        "description": "An initiative in Aha! — a strategic effort that groups goals, epics, and features.",
        "docs_url": "https://www.aha.io/api/resources/initiatives",
        "columns": {
            **_COMMON_COLUMNS,
            "workflow_status": "The initiative's current status in its workflow.",
            "effort": "Estimated effort for the initiative.",
            "value": "Estimated value of the initiative.",
            "start_date": "Planned start date for the initiative.",
            "end_date": "Planned end date for the initiative.",
        },
    },
    "ideas": {
        "description": "An idea submitted in Aha! Ideas — feedback that can be promoted into features.",
        "docs_url": "https://www.aha.io/api/resources/ideas",
        "columns": {
            **_COMMON_COLUMNS,
            "workflow_status": "The idea's current status in its workflow.",
            "score": "The idea's score.",
            "votes": "Number of votes the idea has received.",
            "endorsements_count": "Number of endorsements the idea has received.",
            "product_id": "Identifier of the product the idea belongs to.",
            "created_by_idea_user": "The user who submitted the idea.",
        },
    },
    "goals": {
        "description": "A goal in Aha! — a measurable objective that initiatives and releases roll up to.",
        "docs_url": "https://www.aha.io/api/resources/goals",
        "columns": {
            **_COMMON_COLUMNS,
            "description": "Description of the goal.",
            "effort": "Estimated effort for the goal.",
            "value": "Estimated value of the goal.",
            "start_date": "Planned start date for the goal.",
            "end_date": "Planned end date for the goal.",
        },
    },
    "todos": {
        "description": "A to-do (task) in Aha! assigned to a user against a record.",
        "docs_url": "https://www.aha.io/api/resources/to-dos",
        "columns": {
            "id": "Unique identifier for the to-do.",
            "name": "The to-do's name.",
            "body": "The to-do's description.",
            "status": "Current status of the to-do (e.g. pending, complete).",
            "due_date": "Date the to-do is due.",
            "assigned_to_user": "The user the to-do is assigned to.",
            "created_at": "Time at which the to-do was created.",
            "updated_at": "Time at which the to-do was last updated.",
        },
    },
    "users": {
        "description": "A user in your Aha! account.",
        "docs_url": "https://www.aha.io/api/resources/users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "created_at": "Time at which the user was created.",
            "updated_at": "Time at which the user was last updated.",
        },
    },
    "releases": {
        "description": "A release in Aha! — a dated container of features and epics delivered together.",
        "docs_url": "https://www.aha.io/api/resources/releases",
        "columns": {
            **_COMMON_COLUMNS,
            "product_id": "Identifier of the product this release belongs to.",
            "release_date": "Planned external release date.",
            "development_started_on": "Date development on the release started.",
            "released": "Whether the release has shipped.",
            "parking_lot": "Whether the release is a parking lot for un-scheduled work.",
            "workflow_status": "The release's current status in its workflow.",
        },
    },
    "requirements": {
        "description": "A requirement in Aha! — a child record under a feature capturing delivery detail.",
        "docs_url": "https://www.aha.io/api/resources/requirements",
        "columns": {
            **_COMMON_COLUMNS,
            "feature_id": "Identifier of the feature this requirement belongs to.",
            "workflow_status": "The requirement's current status in its workflow.",
            "assigned_to_user": "The user the requirement is assigned to.",
            "description": "Description of the requirement.",
        },
    },
    "idea_votes": {
        "description": "A vote (endorsement) cast on an Aha! idea — the demand signal behind an idea.",
        "docs_url": "https://www.aha.io/api/resources/idea_votes",
        "columns": {
            "id": "Unique identifier for the vote.",
            "idea_id": "Identifier of the idea the vote was cast on.",
            "weight": "Weight of the vote.",
            "link": "URL of the idea the vote belongs to.",
            "created_at": "Time at which the vote was cast.",
            "updated_at": "Time at which the vote was last updated.",
        },
    },
}
