from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from Usersnap's REST API v0.1 OpenAPI spec
# (https://app.swaggerhub.com/apis/usersnap6/usersnap-api/0.1).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Usersnap project: a feedback widget/board that collects feedback items.",
        "docs_url": "https://help.usersnap.com/reference/rest-api",
        "columns": {
            "project_id": "Unique identifier of the project.",
            "api_key": "The project's widget API key (used by widget-facing endpoints).",
            "company_id": "Identifier of the company the project belongs to.",
            "space_id": "Identifier of the space the project belongs to.",
            "created_at": "When the project was created.",
            "updated_at": "When the project was last updated.",
            "archived_at": "When the project was archived, if it has been.",
            "owner_id": "Identifier of the user who owns the project.",
            "default_assignee_id": "Identifier of the user new feedback items are assigned to by default.",
            "name": "Display name of the project.",
            "is_live": "Whether the project is live.",
            "feedback_count": "Total number of feedback items in the project.",
            "open_feedback_count": "Number of feedback items still open in the project.",
        },
    },
    "feedbacks": {
        "description": "A feedback item (bug report, rating, or comment) submitted to a project, including its screenshot, labels, and custom data.",
        "docs_url": "https://help.usersnap.com/reference/rest-api",
        "columns": {
            "feedback_id": "Unique identifier of the feedback item.",
            "feedback_number": "Sequential number of the feedback item within its project.",
            "public_link": "Public URL of the feedback item in Usersnap.",
            "project_id": "Identifier of the project the feedback item belongs to.",
            "created_at": "When the feedback item was created.",
            "updated_at": "When the feedback item was last updated.",
            "status_type": "Workflow state of the feedback item (e.g. open, in_progress, done).",
            "priority": "Priority assigned to the feedback item.",
            "assignee_id": "Identifier of the user the feedback item is assigned to.",
            "is_demo": "Whether this is a demo feedback item.",
            "email": "Email address of the person who submitted the feedback.",
            "client": "Client context captured at submission: page URL, browser, OS, screen size, and geolocation.",
            "custom_data": "Custom JSON data attached to the feedback item by the widget.",
            "screenshot": "Annotated screenshot attached to the feedback item, with its comments.",
            "screen_recording": "Screen recording attached to the feedback item.",
            "ordered_inputs": "The form field values submitted with the feedback item, in display order.",
            "labels": "Labels applied to the feedback item.",
        },
    },
    "project_assignees": {
        "description": "Users available as assignees on a project, one row per project/user pair.",
        "docs_url": "https://help.usersnap.com/reference/rest-api",
        "columns": {
            "project_id": "Identifier of the project (added by PostHog during the per-project fan-out).",
            "user_id": "Unique identifier of the user.",
            "first_name": "First name of the user.",
            "last_name": "Last name of the user.",
            "gravatar_url": "URL of the user's Gravatar image.",
        },
    },
}
