from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Coassemble Headless API docs (https://developers.coassemble.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment. Coassemble timestamps
# are ISO 8601 strings.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "courses": {
        "description": "A course in the Coassemble workspace, including publish state and access settings.",
        "docs_url": "https://developers.coassemble.com/api/courses",
        "columns": {
            "id": "The unique ID of the course.",
            "active": "Whether the course is active.",
            "title": "The course title.",
            "description": "The course description.",
            "image": "URL of the course image.",
            "thumbnail": "URL of the course thumbnail.",
            "start": "When access to the course opens, if scheduled.",
            "finish": "When access to the course closes, if scheduled.",
            "theme": "The theme applied to the course.",
            "identified": "Whether learners must be identified to take the course.",
            "private": "Whether the course is private.",
            "paid": "Whether the course is paid.",
            "price": "The course price, if paid.",
            "key": "The shareable key for the course.",
            "identifier": "The user identifier the course is scoped to, if any.",
            "clientIdentifier": "The client identifier the course is scoped to, if any.",
            "revision": "The current revision of the course.",
            "published": "When the course was last published (ISO 8601).",
            "translations": "Languages the course has been translated into.",
            "created": "When the course was created (ISO 8601).",
            "updated": "When the course was last updated (ISO 8601).",
            "deleted": "When the course was deleted, if soft-deleted (ISO 8601).",
        },
    },
    "collections": {
        "description": "A collection — an ordered group of courses shared and tracked together.",
        "docs_url": "https://developers.coassemble.com/api/collections",
        "columns": {
            "id": "The unique ID of the collection.",
            "title": "The collection title.",
            "description": "The collection description.",
            "key": "The shareable key for the collection.",
            "active": "Whether the collection is active.",
            "identifier": "The user identifier the collection is scoped to, if any.",
            "clientIdentifier": "The client identifier the collection is scoped to, if any.",
            "created": "When the collection was created (ISO 8601).",
            "updated": "When the collection was last updated (ISO 8601).",
            "deleted": "When the collection was deleted, if soft-deleted (ISO 8601).",
        },
    },
    "clients": {
        "description": "A client — a grouping of users in a headless workspace, typically one of your customers or tenants.",
        "docs_url": "https://developers.coassemble.com/api/identities",
        "columns": {
            "clientIdentifier": "The workspace-unique identifier of the client.",
            "userCount": "The number of users belonging to the client.",
            "created": "When the client was created (ISO 8601).",
            "updated": "When the client was last updated (ISO 8601).",
        },
    },
    "users": {
        "description": "A user (learner) identity in the headless workspace.",
        "docs_url": "https://developers.coassemble.com/api/identities",
        "columns": {
            "identifier": "The workspace-unique identifier of the user.",
            "clientIdentifier": "The identifier of the client the user belongs to, if any.",
            "name": "The user's display name.",
            "avatar": "URL of the user's avatar.",
            "testMode": "Whether the user is a test user whose activity is excluded from usage.",
            "created": "When the user was created (ISO 8601).",
            "updated": "When the user was last updated (ISO 8601).",
        },
    },
    "course_trackings": {
        "description": "A learner's progress record for a course (one row per learner per course attempt).",
        "docs_url": "https://developers.coassemble.com/api/tracking",
        "columns": {
            "id": "The unique ID of the tracking record.",
            "course_id": "The ID of the course the tracking belongs to (injected by PostHog; trackings are listed per course).",
            "identifier": "The identifier of the user the tracking belongs to.",
            "email": "The learner's email address, if captured.",
            "commenced": "When the learner started the course (ISO 8601).",
            "completed": "When the learner completed the course, if finished (ISO 8601).",
            "passed": "Whether the learner passed the course.",
            "progress_percent": "The learner's progress through the course, as a percentage.",
            "total_time": "Total time the learner spent in the course.",
            "feedback": "Feedback the learner left on the course.",
            "language": "The language the learner took the course in.",
            "scorm": "Whether the tracking came from a SCORM export.",
        },
    },
}
