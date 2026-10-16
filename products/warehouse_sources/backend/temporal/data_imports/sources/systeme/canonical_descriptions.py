from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "Contacts with registration details, email status, custom fields, and tags.",
        "docs_url": "https://developer.systeme.io/reference/api_contacts_get_collection-1",
        "columns": {
            "id": "Unique contact identifier.",
            "email": "Contact email address.",
            "registeredAt": "Date and time of contact registration.",
            "locale": "Contact language code.",
            "sourceURL": "URL associated with the contact source.",
            "unsubscribed": "Whether the contact has unsubscribed.",
            "bounced": "Whether email to the contact has bounced.",
            "needsConfirmation": "Whether the contact needs confirmation.",
            "fields": "Custom fields and their values for the contact.",
            "tags": "Tags assigned to the contact.",
        },
    },
    "tags": {
        "description": "Tags used to organize contacts.",
        "docs_url": "https://developer.systeme.io/reference/api_tags_get_collection-1",
        "columns": {
            "id": "Unique tag identifier.",
            "name": "Tag name.",
            "createdAt": "Date and time when the tag was created.",
        },
    },
    "newsletters": {
        "description": "Email newsletters with content metadata and sending status.",
        "docs_url": "https://developer.systeme.io/reference/api_mailingnewsletters_get_collection",
        "columns": {
            "id": "Unique newsletter identifier.",
            "type": "Newsletter type.",
            "content": "Newsletter subject, preview text, editor type, and sender details.",
            "state": "Whether the newsletter has been sent.",
        },
    },
    "courses": {
        "description": "Courses with language, address, status, and module details.",
        "docs_url": "https://developer.systeme.io/reference/api_schoolcourses_get_collection-1",
        "columns": {
            "id": "Unique course identifier.",
            "name": "Course name.",
            "description": "Course description.",
            "locale": "Course language code.",
            "domainName": "Domain used by the course.",
            "path": "Course URL path.",
            "active": "Whether the course is active.",
            "modules": "Course modules with their identifiers and names.",
        },
    },
    "enrollments": {
        "description": "Contact enrollments in courses.",
        "docs_url": "https://developer.systeme.io/reference/api_schoolenrollments_get_collection-1",
        "columns": {
            "id": "Unique enrollment identifier.",
            "contact": "Contact enrolled in the course.",
            "course": "Course associated with the enrollment.",
            "accessType": "Type of access granted by the enrollment.",
            "active": "Whether the enrollment is active.",
        },
    },
    "communities": {
        "description": "Communities available in the account.",
        "docs_url": "https://developer.systeme.io/reference/api_communitycommunities_get_collection-1",
        "columns": {
            "id": "Unique community identifier.",
            "name": "Community name.",
            "domainName": "Domain used by the community.",
            "path": "Community URL path.",
        },
    },
    "memberships": {
        "description": "Contact memberships in communities.",
        "docs_url": "https://developer.systeme.io/reference/api_communitymemberships_get_collection-1",
        "columns": {
            "id": "Unique membership identifier.",
            "community": "Community associated with the membership.",
            "contact": "Contact associated with the membership.",
        },
    },
}
