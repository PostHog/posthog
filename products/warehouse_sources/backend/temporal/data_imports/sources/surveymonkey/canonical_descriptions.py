"""Canonical, documentation-sourced descriptions for SurveyMonkey endpoints and columns.

Sourced from the official SurveyMonkey API reference (https://api.surveymonkey.com/v3/docs).
Keyed by the endpoint names in `settings.py` `SURVEYMONKEY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced SurveyMonkey table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "surveys": {
        "description": "A survey in your SurveyMonkey account, with its title, structure, and response counts.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#surveys",
        "columns": {
            "id": "Unique identifier for the survey.",
            "title": "The survey's title.",
            "nickname": "Internal nickname for the survey, not shown to respondents.",
            "language": "Language the survey is written in.",
            "category": "Category the survey belongs to.",
            "question_count": "Number of questions in the survey.",
            "page_count": "Number of pages in the survey.",
            "response_count": "Number of responses collected for the survey.",
            "date_created": "Time at which the survey was created.",
            "date_modified": "Time at which the survey was last modified.",
            "preview": "URL to preview the survey.",
            "href": "API URL of the survey resource.",
        },
    },
    "survey_responses": {
        "description": "An individual respondent's submission to a survey, including their answers.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#survey-responses",
        "columns": {
            "id": "Unique identifier for the response.",
            "survey_id": "ID of the survey this response belongs to.",
            "collector_id": "ID of the collector that gathered this response.",
            "recipient_id": "ID of the recipient who submitted the response, if known.",
            "response_status": "Status of the response (e.g. completed, partial, overquota, disqualified).",
            "total_time": "Total time the respondent spent on the survey, in seconds.",
            "ip_address": "IP address from which the response was submitted.",
            "date_created": "Time at which the response was started.",
            "date_modified": "Time at which the response was last modified.",
            "pages": "Array of pages with the respondent's answers to each question.",
            "href": "API URL of the response resource.",
        },
    },
    "survey_pages": {
        "description": "A page within a survey that groups a set of questions.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#survey-pages",
        "columns": {
            "id": "Unique identifier for the page.",
            "title": "The page's title.",
            "description": "Description shown at the top of the page.",
            "position": "Position of the page within the survey.",
            "question_count": "Number of questions on the page.",
            "href": "API URL of the page resource.",
        },
    },
    "survey_questions": {
        "description": "A question on a survey, extracted from the survey's page details.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#survey-pages-id-questions",
        "columns": {
            "id": "Unique identifier for the question.",
            "heading": "The question's text as shown to respondents.",
            "position": "Position of the question within its page.",
            "family": "Question family (e.g. single_choice, multiple_choice, open_ended, matrix).",
            "subtype": "Question subtype that refines the family (e.g. vertical, menu, essay).",
            "required": "Whether an answer to the question is required.",
            "answers": "Available answer choices and options for the question.",
            "href": "API URL of the question resource.",
        },
    },
    "collectors": {
        "description": "A method used to distribute a survey and gather responses (e.g. a web link or email invitation).",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#collectors",
        "columns": {
            "id": "Unique identifier for the collector.",
            "name": "The collector's name.",
            "type": "Type of collector (e.g. weblink, email).",
            "status": "Status of the collector (e.g. open, closed).",
            "response_count": "Number of responses collected by this collector.",
            "date_created": "Time at which the collector was created.",
            "date_modified": "Time at which the collector was last modified.",
            "href": "API URL of the collector resource.",
        },
    },
}
