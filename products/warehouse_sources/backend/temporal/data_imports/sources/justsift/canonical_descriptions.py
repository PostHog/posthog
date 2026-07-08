from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Sift (JustSift) API docs (https://developers.justsift.com).
# Person profiles are largely dynamic (custom fields vary per organization), so only the stable,
# built-in columns are described here — the rest fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "people": {
        "description": "A person in the Sift directory — an employee profile with built-in and organization-specific fields.",
        "docs_url": "https://developers.justsift.com",
        "columns": {
            "id": "The unique identifier of the person.",
            "firstName": "The person's first name.",
            "lastName": "The person's last name.",
            "email": "The person's email address.",
            "directoryId": "The identifier of the directory the person belongs to.",
            "pictureUrl": "The URL of the person's profile photo (custom or official).",
            "teamLeaderId": "The id of the person's direct leader.",
            "isTeamLeader": "Whether the person has any direct reports.",
            "directReportCount": "The number of people who report directly to this person.",
            "totalReportCount": "The total number of direct and indirect reports.",
            "reportingPath": "The ordered list of leader ids from the top of the hierarchy down to this person.",
        },
    },
    "fields": {
        "description": "A field definition in the Sift schema — describes a searchable property that can appear on a person profile.",
        "docs_url": "https://developers.justsift.com",
        "columns": {
            "objectKey": "The stable key that identifies the field and is used to reference it in person objects, sorting, and filters.",
            "name": "The human-readable display name of the field.",
            "type": "The data type of the field's values.",
            "kind": "The category of the field (for example built-in or custom).",
            "searchable": "Whether the field can be used as a search filter.",
        },
    },
}
