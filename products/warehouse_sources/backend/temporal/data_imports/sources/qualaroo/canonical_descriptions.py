from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Qualaroo REST Reporting API docs
# (https://help.qualaroo.com/hc/en-us/articles/201969438-The-REST-Reporting-API).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "nudges": {
        "description": "A Qualaroo nudge (survey) configured in your account.",
        "docs_url": "https://help.qualaroo.com/hc/en-us/articles/201969438-The-REST-Reporting-API",
        "columns": {
            "id": "The unique ID of the nudge (survey).",
            "name": "The internal name of the nudge.",
            "alias": "The human-readable alias of the nudge.",
            "type": "The nudge type (for example, survey or exit).",
            "status": "The current status of the nudge (for example, active or paused).",
            "created_at": "When the nudge was created.",
            "updated_at": "When the nudge was last updated.",
        },
    },
    "responses": {
        "description": "One respondent's response to a Qualaroo nudge (survey), with their answers and metadata.",
        "docs_url": "https://help.qualaroo.com/hc/en-us/articles/201969438-The-REST-Reporting-API",
        "columns": {
            "id": "The ID of the response record.",
            "nudge_id": "The ID of the nudge (survey) that the response belongs to.",
            "time": "When the response was recorded, in the account time zone with its UTC offset.",
            "token": "An anonymous identifier of the respondent.",
            "ip_address": "The IP address of the respondent.",
            "identity": "The identity that you tagged the respondent with.",
            "page": "The page of your website where the respondent interacted with the survey.",
            "referrer": "The URL of the referrer page, if there was one.",
            "user_agent": "The User-Agent of the respondent's browser.",
            "answered_questions": "A map of the questions that the respondent answered, with each question ID, title, answer text, selected option ID and comment.",
            "properties": "The custom name/value properties that you tagged the respondent with.",
        },
    },
}
