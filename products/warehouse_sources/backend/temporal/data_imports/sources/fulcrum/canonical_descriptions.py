from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Fulcrum (Spatial Networks) REST API v2 docs
# (https://docs.fulcrumapp.com/reference). Partial coverage is fine — anything not described
# here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "records": {
        "description": "Individual data-collection entries captured against a form, including their geospatial location and per-form field values.",
        "docs_url": "https://docs.fulcrumapp.com/reference/records-intro",
        "columns": {
            "id": "Unique identifier for the record.",
            "form_id": "Identifier of the form this record belongs to.",
            "created_at": "Timestamp when the record was synced to the cloud.",
            "updated_at": "Timestamp when the record was last synced to or processed in the cloud.",
            "latitude": "Record location latitude in WGS 84 decimal degrees.",
            "longitude": "Record location longitude in WGS 84 decimal degrees.",
            "form_values": "Object of the record's field values, keyed by the form schema's element keys.",
            "status": "The record's status value, which sets the color of its map marker.",
            "project_id": "Identifier of the project this record is assigned to, if any.",
            "assigned_to_id": "Identifier of the member this record is assigned to, if any.",
        },
    },
    "forms": {
        "description": "Form definitions (the schema of a data-collection app), including their custom elements.",
        "docs_url": "https://docs.fulcrumapp.com/reference/forms-intro",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The name given to this form.",
            "description": "The description given to this form.",
            "created_at": "Timestamp when the form was created.",
            "updated_at": "Timestamp when the form was last updated.",
            "elements": "The form's custom elements (its field schema).",
            "status_field": "The form's status field configuration.",
            "record_count": "The number of records in this form.",
        },
    },
    "choice_lists": {
        "description": "Reusable lists of choices that can be referenced by choice fields across forms.",
        "docs_url": "https://docs.fulcrumapp.com/reference/choice-lists-intro",
        "columns": {
            "id": "Unique identifier for the choice list.",
            "name": "The name of the choice list.",
            "created_at": "Timestamp when the choice list was created.",
            "updated_at": "Timestamp when the choice list was last updated.",
        },
    },
    "classification_sets": {
        "description": "Hierarchical classification taxonomies referenced by classification fields on forms.",
        "docs_url": "https://docs.fulcrumapp.com/reference/classification-sets-intro",
        "columns": {
            "id": "Unique identifier for the classification set.",
            "name": "The name of the classification set.",
            "created_at": "Timestamp when the classification set was created.",
            "updated_at": "Timestamp when the classification set was last updated.",
        },
    },
    "projects": {
        "description": "Projects used to group and organize records.",
        "docs_url": "https://docs.fulcrumapp.com/reference/projects-intro",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "The name of the project.",
            "description": "The description of the project.",
            "created_at": "Timestamp when the project was created.",
            "updated_at": "Timestamp when the project was last updated.",
        },
    },
    "memberships": {
        "description": "Members of the organization and their role assignments.",
        "docs_url": "https://docs.fulcrumapp.com/reference/memberships-intro",
        "columns": {
            "id": "Unique identifier for the membership.",
            "name": "The member's name.",
            "email": "The member's email address.",
            "role_id": "Identifier of the role assigned to the member.",
            "created_at": "Timestamp when the membership was created.",
            "updated_at": "Timestamp when the membership was last updated.",
        },
    },
    "roles": {
        "description": "Roles that define the permissions granted to organization members.",
        "docs_url": "https://docs.fulcrumapp.com/reference/roles-get-all",
        "columns": {
            "id": "Unique identifier for the role.",
            "name": "The name of the role.",
            "is_default": "Whether this is the default role for new members.",
        },
    },
    "changesets": {
        "description": "Groups of record changes captured together, used to track edits over time.",
        "docs_url": "https://docs.fulcrumapp.com/reference/changesets-intro",
        "columns": {
            "id": "Unique identifier for the changeset.",
            "form_id": "Identifier of the form the changeset applies to.",
            "created_at": "Timestamp when the changeset was created.",
            "updated_at": "Timestamp when the changeset was last updated.",
            "closed_at": "Timestamp when the changeset was closed, if closed.",
            "number_of_changes": "The count of record changes in this changeset.",
        },
    },
    "webhooks": {
        "description": "Registered webhook endpoints that receive record, form, and other change events.",
        "docs_url": "https://docs.fulcrumapp.com/reference/webhooks-intro",
        "columns": {
            "id": "Unique identifier for the webhook.",
            "url": "The destination URL that receives webhook events.",
            "active": "Whether the webhook is currently enabled.",
            "created_at": "Timestamp when the webhook was created.",
            "updated_at": "Timestamp when the webhook was last updated.",
        },
    },
    "photos": {
        "description": "Metadata for photos captured against records (the binary files are fetched separately).",
        "docs_url": "https://docs.fulcrumapp.com/reference/photos-intro",
        "columns": {
            "access_key": "Unique identifier for the photo.",
            "record_id": "Identifier of the record this photo belongs to.",
            "form_id": "Identifier of the form the record belongs to.",
            "created_at": "Timestamp when the photo was created.",
            "updated_at": "Timestamp when the photo was last updated.",
            "latitude": "Photo capture latitude in WGS 84 decimal degrees.",
            "longitude": "Photo capture longitude in WGS 84 decimal degrees.",
        },
    },
    "signatures": {
        "description": "Metadata for signatures captured against records (the binary files are fetched separately).",
        "docs_url": "https://docs.fulcrumapp.com/reference/signatures-intro",
        "columns": {
            "access_key": "Unique identifier for the signature.",
            "record_id": "Identifier of the record this signature belongs to.",
            "form_id": "Identifier of the form the record belongs to.",
            "created_at": "Timestamp when the signature was created.",
            "updated_at": "Timestamp when the signature was last updated.",
        },
    },
    "videos": {
        "description": "Metadata for videos captured against records (the binary files are fetched separately).",
        "docs_url": "https://docs.fulcrumapp.com/reference/videos-intro",
        "columns": {
            "access_key": "Unique identifier for the video.",
            "record_id": "Identifier of the record this video belongs to.",
            "form_id": "Identifier of the form the record belongs to.",
            "created_at": "Timestamp when the video was created.",
            "updated_at": "Timestamp when the video was last updated.",
        },
    },
    "audio": {
        "description": "Metadata for audio clips captured against records (the binary files are fetched separately).",
        "docs_url": "https://docs.fulcrumapp.com/reference/audio-intro",
        "columns": {
            "access_key": "Unique identifier for the audio resource.",
            "record_id": "Identifier of the record this audio belongs to.",
            "form_id": "Identifier of the form the record belongs to.",
            "created_at": "Timestamp when the audio was created.",
            "updated_at": "Timestamp when the audio was last updated.",
        },
    },
}
