from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "surveys": {
        "description": "Surveys in the workspace, with their settings and response counts.",
        "docs_url": "https://developers.survicate.com/data-export/survey/",
        "columns": {
            "id": "The survey identifier.",
            "name": "The survey name.",
            "type": "The method used to deliver the survey.",
            "created_at": "The time when the survey was created.",
            "enabled": "Whether respondents can access the survey.",
            "responses": "The number of responses to the survey.",
            "launch": "The survey schedule and response limit.",
        },
    },
    "questions": {
        "description": "Questions and answer choices for each survey.",
        "docs_url": "https://developers.survicate.com/data-export/survey/",
        "columns": {
            "survey_id": "The identifier of the survey that contains the question.",
            "id": "The question identifier.",
            "type": "The question type.",
            "question": "The question text shown to respondents.",
            "introduction": "The introduction shown before the question.",
            "answer_choices": "The available answer choices and their identifiers.",
        },
    },
    "responses": {
        "description": "Survey responses, including answers and respondent identifiers.",
        "docs_url": "https://developers.survicate.com/data-export/response/",
        "columns": {
            "survey_id": "The identifier of the survey that received the response.",
            "uuid": "The response identifier.",
            "collected_at": "The time when Survicate received the response.",
            "answers": "The submitted answers. This list excludes skipped questions.",
            "respondent": "The respondent identifier and requested attributes.",
            "attributes": "The requested attributes recorded with this response.",
            "url": "The page where the survey appeared.",
            "device_type": "The type of device used to submit the response.",
            "operating_system": "The operating system of the respondent's device.",
            "platform": "The platform identifier reported by the respondent's device.",
            "language": "The language of the survey translation shown to the respondent.",
        },
    },
}
