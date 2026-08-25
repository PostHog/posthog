from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "surveys": {
        "description": "A survey in the SurveySparrow account, such as a conversational form, NPS, CSAT, or CES survey.",
        "docs_url": "https://developers.surveysparrow.com/rest-apis/survey",
        "columns": {
            "id": "Unique identifier for the survey.",
            "name": "Name of the survey.",
            "archived": "Whether the survey has been archived.",
            "survey_type": "Type of the survey (e.g. Conversational, ClassicForm, NPS, CES, CSAT).",
            "created_at": "Timestamp when the survey was created.",
            "updated_at": "Timestamp when the survey was last updated.",
            "survey_folder_id": "Identifier of the folder the survey belongs to.",
            "survey_folder_name": "Name of the folder the survey belongs to.",
        },
    },
    "responses": {
        "description": "A completed submission to a survey, including the answers given to each question.",
        "docs_url": "https://developers.surveysparrow.com/rest-apis/response",
        "columns": {
            "id": "Identifier for the response within its survey.",
            "survey_id": "Identifier of the survey the response belongs to.",
            "contact_id": "Identifier of the contact who submitted the response, if known.",
            "completed": "Submission status of the response.",
            "completed_time": "Timestamp when the response was submitted.",
            "channel_id": "Identifier of the share channel the response came through.",
            "channel": "Share channel the response came through (name, type, and status).",
            "language": "Language the response was submitted in.",
            "answers": "Answers given to each question in the survey.",
        },
    },
    "questions": {
        "description": "A question belonging to a survey.",
        "docs_url": "https://developers.surveysparrow.com/rest-apis/questions",
        "columns": {
            "id": "Unique identifier for the question.",
            "survey_id": "Identifier of the survey the question belongs to.",
            "section_id": "Identifier of the survey section the question belongs to.",
            "type": "Question type (e.g. TextInput, OpinionScale, Rating).",
            "position": "Position of the question within the survey.",
            "hasDisplayLogic": "Whether the question has display logic attached.",
            "properties": "Additional configuration of the question.",
            "account_id": "Identifier of the SurveySparrow account.",
            "parent_question_id": "Identifier of the parent question, if this is a follow-up.",
        },
    },
    "contacts": {
        "description": "A contact stored in the SurveySparrow audience, used to share surveys and track who responded.",
        "docs_url": "https://developers.surveysparrow.com/rest-apis/contacts",
        "columns": {
            "id": "Unique identifier for the contact.",
        },
    },
    "contact_lists": {
        "description": "A named list grouping contacts for survey distribution.",
        "docs_url": "https://developers.surveysparrow.com/rest-apis/contact-lists",
        "columns": {
            "id": "Unique identifier for the contact list.",
            "name": "Name of the contact list.",
            "description": "Description of the contact list.",
        },
    },
}
