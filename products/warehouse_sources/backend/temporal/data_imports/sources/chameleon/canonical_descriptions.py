"""Canonical, documentation-sourced descriptions for Chameleon endpoints and columns.

Sourced from the official Chameleon API reference (https://developers.chameleon.io). Keyed by the
endpoint names in `settings.py` `CHAMELEON_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Chameleon table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Every Chameleon model carries these.
_ID = "The Chameleon ID (a globally-unique, time-ordered ObjectId)."
_CREATED_AT = "Time at which this record was created or first added to Chameleon."
_UPDATED_AT = "Time at which any property of this record was last updated."

_EXPERIENCE_STATS = {
    "stats": "Aggregated all-time statistics for this Experience.",
    "stats.started_count": "Number of end-users who saw this Experience.",
    "stats.last_started_at": "Most recent time any user saw this Experience.",
    "stats.completed_count": "Number of end-users who completed/finished this Experience.",
    "stats.last_completed_at": "Most recent time any user completed/finished this Experience.",
    "stats.exited_count": "Number of end-users who dismissed/exited this Experience.",
    "stats.last_exited_at": "Most recent time any user dismissed/exited this Experience.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "profiles": {
        "description": "A User Profile: one of your product's identified end-users, with the properties Chameleon has stored about them.",
        "docs_url": "https://developers.chameleon.io/apis/profiles",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "uid": "The external user ID that came from your backend system.",
            "company_id": "The Chameleon ID of the Company this user is associated with, if any.",
            "browser_x": "Browser width in pixels.",
            "browser_tz": "Browser timezone as an integer offset from UTC.",
            "browser_l": "Language code reported by the Accept-Language header.",
            "browser_n": "Browser name (chrome, firefox, safari, opera, ie10, ie11, or edge).",
            "browser_k": "Browser kind (desktop or mobile).",
            "percent": "A randomly assigned but stable value used for A/B testing.",
            "last_seen_at": "When the user was last active on a page where Chameleon is installed.",
            "last_seen_session_count": "Number of sessions (a session ends after 90 minutes of inactivity).",
            "delivery_ids": "Ordered list of Delivery model IDs for this user.",
        },
    },
    "companies": {
        "description": "A Company (account): one of your identified customer accounts, with the properties Chameleon has stored about it.",
        "docs_url": "https://developers.chameleon.io/apis/companies",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "uid": "The external company ID that came from your backend system.",
        },
    },
    "segments": {
        "description": "A Segment: a reusable set of user-targeting filters used to decide which users see which Experiences.",
        "docs_url": "https://developers.chameleon.io/apis/segments",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "name": "The name given to the Segment by a Chameleon administrator.",
            "items": "The array of Segmentation Filter expressions that define this Segment.",
            "items_op": "How the filter items are joined: 'and' or 'or'.",
        },
    },
    "tours": {
        "description": "A Tour: a sequence of steps shown to end-users who match the configured targeting criteria.",
        "docs_url": "https://developers.chameleon.io/apis/tours",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "name": "The name given to the Tour by a Chameleon administrator.",
            "style": "The delivery method of this Tour: 'auto' or 'manual'.",
            "position": "The order this appears in lists (starting from 0).",
            "experiment_at": "When A/B experimentation was turned on for this Tour.",
            "experiment_range": "The range of Profile#percent included in the experiment.",
            "segment_ids": "The Chameleon IDs of the Segments targeted by this Tour.",
            "published_at": "The time this Tour was most recently published.",
            "tag_ids": "The Chameleon IDs of the Tags attached to this Tour.",
            "dashboard_url": "Direct link to this Tour in the Chameleon Dashboard.",
            **_EXPERIENCE_STATS,
        },
    },
    "surveys": {
        "description": "A Microsurvey: an in-product question step used to collect contextual user feedback.",
        "docs_url": "https://developers.chameleon.io/apis/surveys",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "name": "The name given to the Microsurvey by a Chameleon administrator.",
            "position": "The order this appears in lists (starting from 0).",
            "segment_ids": "The Chameleon IDs of the Segments targeted by this Microsurvey.",
            "published_at": "The time this Microsurvey was most recently published.",
            "tag_ids": "The Chameleon IDs of the Tags attached to this Microsurvey.",
            "experiment_at": "When A/B experimentation was turned on for this Microsurvey.",
            "dashboard_url": "Direct link to this Microsurvey in the Chameleon Dashboard.",
            "last_dropdown_items": "All dropdown options that have been selected by any user.",
            **_EXPERIENCE_STATS,
        },
    },
    "launchers": {
        "description": "A Launcher: a menu of items (Tours, surveys, links) shown to end-users who match the configured criteria.",
        "docs_url": "https://developers.chameleon.io/apis/launchers",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "name": "The name given to the Launcher by a Chameleon administrator.",
            "title": "The display title.",
            "description": "The display description.",
            "preset": "The preconfigured type (icon, element, icon_checklist, updates, or faqs).",
            "segment_ids": "The Chameleon IDs of the Segments targeted by this Launcher.",
            "published_at": "The time this Launcher was most recently published.",
            "tag_ids": "The Chameleon IDs of the Tags attached to this Launcher.",
            "list_type": "Whether this is a checklist or a normal list (default or checklist).",
            "items": "The array of items that define the Launcher menu contents.",
        },
    },
    "event_names": {
        "description": "An Event Name: a tracked or custom event configured in your Chameleon account, usable in Segmentation filters.",
        "docs_url": "https://developers.chameleon.io/apis/event-names",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "name": "The display name given to the event by a Chameleon administrator.",
            "description": "A description of the event.",
            "uid": "The normalized identifier for the event (e.g. 'Signed up' becomes 'signed_up').",
            "kind": "The kind of event: 'tracked' or 'custom'.",
            "source": "The source of the event (api_js, api_v3, segment, freshpaint, heap, mixpanel, rudderstack, or amplitude).",
            "published_at": "When this event was set to be a Tracked event. Null if not actively tracked.",
            "last_seen_at": "When this event was last triggered by any user.",
            "dashboard_url": "Direct link to this Event Name in the Chameleon Dashboard.",
        },
    },
    "responses": {
        "description": "A Microsurvey response: a single user's interaction with a Microsurvey, including buttons clicked and text entered.",
        "docs_url": "https://developers.chameleon.io/apis/survey-responses",
        "columns": {
            "id": _ID,
            "created_at": _CREATED_AT,
            "updated_at": _UPDATED_AT,
            "survey_id": "The Chameleon ID of the Microsurvey this response belongs to.",
            "profile_id": "The Chameleon ID of the User Profile that submitted this response.",
            "href": "The page URL where the Microsurvey was displayed.",
            "button_text": "The text of the button that was clicked.",
            "button_order": "The 0-indexed position of the button that was clicked.",
            "button_id": "The Chameleon ID of the button that was clicked.",
            "input_text": "Free-text comment left by the user on the first step or follow-up question 1.",
            "dropdown_items": "The selected dropdown options on the first step.",
            "finished_at": "When the last step of the Microsurvey response was completed.",
        },
    },
}
