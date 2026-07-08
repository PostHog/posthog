from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Zonka Feedback API v2.1 docs (https://apidocs.zonkafeedback.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "responses": {
        "description": "A single feedback response submitted to a Zonka Feedback survey, including answers and respondent context.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the response.",
            "surveyId": "The ID of the survey this response was submitted to.",
            "contactId": "The ID of the contact who submitted the response, if known.",
            "channel": "The channel the response was collected through (email, SMS, web, kiosk, etc.).",
            "status": "The completion status of the response (e.g. complete, partial).",
            "language": "The language the survey was answered in.",
            "responseDate": "The timestamp the response was submitted, in ISO 8601 UTC.",
            "location": "The location associated with the response, if any.",
            "device": "The device the response was collected on, if any.",
            "answers": "The list of answers given to the survey's questions.",
        },
    },
    "surveys": {
        "description": "A Zonka Feedback survey — the questionnaire (CSAT, NPS, CES, etc.) distributed to collect feedback.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the survey.",
            "name": "The name of the survey.",
            "type": "The survey type (e.g. CSAT, NPS, CES).",
            "status": "Whether the survey is active or inactive.",
            "language": "The default language of the survey.",
            "createdOn": "The timestamp the survey was created, in ISO 8601 UTC.",
            "modifiedOn": "The timestamp the survey was last modified, in ISO 8601 UTC.",
        },
    },
    "contacts": {
        "description": "A contact in the Zonka Feedback account — a person surveys can be sent to and whose responses are attributed.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the contact.",
            "email": "The contact's email address.",
            "phone": "The contact's phone number.",
            "firstName": "The contact's first name.",
            "lastName": "The contact's last name.",
            "createdOn": "The timestamp the contact was created, in ISO 8601 UTC.",
            "modifiedOn": "The timestamp the contact was last modified, in ISO 8601 UTC.",
        },
    },
}
