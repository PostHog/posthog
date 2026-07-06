from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken from the Paperform/Papersign API docs
# (https://paperform.readme.io/reference/papersign). Partial coverage is fine — any column not
# listed here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "documents": {
        "description": "A Papersign e-signature document, tracking its signers, status, and lifecycle timestamps.",
        "docs_url": "https://paperform.readme.io/reference/listpapersigndocuments",
        "columns": {
            "id": "Unique identifier of the document.",
            "name": "Name of the document.",
            "status": "Lifecycle status of the document (draft, in_progress, completed, canceled, expired, or rejected).",
            "folder": "The Papersign folder the document belongs to (nested object with id, name, parent_id, space_id).",
            "space": "The Papersign space the document belongs to (nested object with id, name, root_folder_id, allow_team_access).",
            "signers": "List of signers on the document.",
            "variables": "List of Papersign variables (merge fields) defined on the document.",
            "created_at_utc": "Timestamp the document was created (UTC).",
            "updated_at_utc": "Timestamp the document was last updated (UTC).",
            "sent_at_utc": "Timestamp the document was sent to signers (UTC), or null.",
            "completed_at_utc": "Timestamp all signers completed the document (UTC), or null.",
        },
    },
    "folders": {
        "description": "A folder that organises Papersign documents within a space.",
        "docs_url": "https://paperform.readme.io/reference/listpapersignfolders",
        "columns": {
            "id": "Unique identifier of the folder.",
            "name": "Name of the folder.",
            "parent_id": "Identifier of the parent folder, or null for a top-level folder.",
            "space_id": "Identifier of the space the folder belongs to.",
        },
    },
    "spaces": {
        "description": "A Papersign space — a top-level workspace grouping folders and documents.",
        "docs_url": "https://paperform.readme.io/reference/listpapersignspaces",
        "columns": {
            "id": "Unique identifier of the space.",
            "name": "Name of the space.",
            "root_folder_id": "Identifier of the space's root folder.",
            "allow_team_access": "Whether team members can access this space.",
        },
    },
}
