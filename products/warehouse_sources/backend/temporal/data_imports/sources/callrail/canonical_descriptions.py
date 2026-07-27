from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from CallRail's public v3 API docs (https://apidocs.callrail.com). Keyed by
# the endpoint name from ENDPOINTS / get_schemas. Partial coverage is fine — anything not listed
# here falls back to LLM enrichment using the docs_url and column data types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "calls": {
        "description": "Tracked phone calls captured by CallRail, including caller details, attribution source, and outcome.",
        "docs_url": "https://apidocs.callrail.com/#calls",
        "columns": {
            "id": "Unique identifier for the call.",
            "answered": "Whether the call was answered.",
            "business_phone_number": "The business phone number that received the call.",
            "customer_city": "City of the caller, derived from their phone number.",
            "customer_country": "Country of the caller.",
            "customer_name": "Name of the caller, when known.",
            "customer_phone_number": "Phone number of the caller.",
            "customer_state": "State/region of the caller.",
            "direction": "Whether the call was inbound or outbound.",
            "duration": "Length of the call in seconds.",
            "start_time": "When the call started (ISO 8601). Stable, used for incremental sync.",
            "created_at": "When CallRail created the call record (ISO 8601).",
            "tracking_phone_number": "The CallRail tracking number that was dialed.",
            "source_name": "Marketing source attributed to the call.",
            "first_call": "Whether this was the caller's first tracked call.",
            "recording": "URL to the call recording, when available.",
            "voicemail": "Whether the call went to voicemail.",
            "company_id": "Identifier of the company the call belongs to.",
        },
    },
    "companies": {
        "description": "Companies configured in the CallRail account. A company groups trackers, calls, and form submissions.",
        "docs_url": "https://apidocs.callrail.com/#companies",
        "columns": {
            "id": "Unique identifier for the company.",
            "name": "Display name of the company.",
            "status": "Whether the company is active or disabled.",
            "time_zone": "Time zone configured for the company.",
            "created_at": "When the company was created (ISO 8601).",
            "callscribe_enabled": "Whether call transcription is enabled.",
        },
    },
    "form_submissions": {
        "description": "Form submissions captured by CallRail Form Tracking, with attribution to the originating marketing source.",
        "docs_url": "https://apidocs.callrail.com/#form-submissions",
        "columns": {
            "id": "Unique identifier for the form submission.",
            "company_id": "Identifier of the company the submission belongs to.",
            "person_id": "Identifier of the person who submitted the form.",
            "form_data": "The submitted form field values.",
            "submitted_at": "When the form was submitted (ISO 8601). Stable, used for incremental sync.",
            "source": "Marketing source attributed to the submission.",
            "landing_page_url": "Page the visitor landed on before submitting.",
            "form_url": "URL of the page containing the form.",
            "first_form": "Whether this was the person's first form submission.",
        },
    },
    "text_messages": {
        "description": "SMS conversations between callers and the business, captured by CallRail.",
        "docs_url": "https://apidocs.callrail.com/#text-messages",
        "columns": {
            "id": "Unique identifier for the conversation.",
            "company_id": "Identifier of the company the conversation belongs to.",
            "initial_tracker_id": "Tracker the conversation started on.",
            "customer_phone_number": "Phone number of the customer.",
            "customer_name": "Name of the customer, when known.",
            "last_message_at": "Timestamp of the most recent message in the conversation.",
            "messages": "The individual text messages in the conversation.",
        },
    },
    "trackers": {
        "description": "Tracking phone numbers and form trackers used to attribute calls and submissions to marketing sources.",
        "docs_url": "https://apidocs.callrail.com/#trackers",
        "columns": {
            "id": "Unique identifier for the tracker.",
            "name": "Display name of the tracker.",
            "type": "Tracker type (e.g. source, session).",
            "status": "Whether the tracker is active or disabled.",
            "destination_number": "Number calls are forwarded to.",
            "tracking_numbers": "The tracking phone numbers assigned to this tracker.",
            "company_id": "Identifier of the company the tracker belongs to.",
        },
    },
    "users": {
        "description": "Users with access to the CallRail account.",
        "docs_url": "https://apidocs.callrail.com/#users",
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "Email address of the user.",
            "first_name": "First name of the user.",
            "last_name": "Last name of the user.",
            "name": "Full name of the user.",
            "role": "Account role assigned to the user.",
            "created_at": "When the user was created (ISO 8601).",
        },
    },
    "tags": {
        "description": "Tags available in the CallRail account for categorizing calls and conversations.",
        "docs_url": "https://apidocs.callrail.com/#tags",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Display name of the tag.",
            "color": "Color associated with the tag in the UI.",
            "status": "Whether the tag is enabled.",
            "company_id": "Identifier of the company the tag belongs to.",
            "created_at": "When the tag was created (ISO 8601).",
        },
    },
}
