from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the public Sprig Data Export API reference
# (https://docs.sprig.com/reference/sprig-api/overview). Keyed by the schema/endpoint name
# returned by `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Surveys": {
        "description": "Study configuration and metadata for surveys created in Sprig.",
        "docs_url": "https://docs.sprig.com/reference/get-v1-surveys-1",
        "columns": {
            "id": "Sprig-assigned unique identifier for the survey.",
            "name": "The name of the survey.",
            "status": "The survey's lifecycle status: IN_PROGRESS, PAUSED, COMPLETED, DRAFT, ARCHIVED, or NEW.",
            "createdAt": "The date and time the survey was created.",
            "updatedAt": "The date and time the survey was last updated.",
            "completedAt": "The date and time the survey was marked complete, if it has been.",
            "launchedAt": "The date and time the survey was launched, if it has been.",
            "platform": "The platform the survey targets (e.g. web).",
            "type": "The survey type (e.g. CONTINUOUS).",
            "questions": "The list of questions configured on the survey.",
            "constraints": "Targeting/audience constraints configured on the survey.",
            "totalResponseLimit": "The maximum number of responses the survey will collect, if capped.",
        },
    },
    "Responses": {
        "description": "Answer-level survey response data. Each row is one visitor's answer to one "
        "question; `responseGroupUid` groups every answer belonging to the same submission.",
        "docs_url": "https://docs.sprig.com/reference/get-v1-responses-1",
        "columns": {
            "visitorId": "Sprig-assigned identifier for the visitor who answered.",
            "surveyId": "The id of the survey this response belongs to.",
            "questionId": "The id of the question this row answers.",
            "questionText": "The text of the question as shown to the visitor.",
            "questionType": "The type of question (e.g. rating, multiple choice, open text).",
            "response": "The visitor's answer. Shape varies by question type.",
            "responseGroupUid": "Identifier grouping every answer from a single response submission.",
            "createdAt": "The date and time the answer was created.",
            "updatedAt": "The date and time the answer was last updated.",
            "visitorUuid": "The visitor's UUID.",
            "externalUserId": "The visitor's external user id, if one was set.",
            "selectedIndexes": "The index/indexes selected by the visitor, for choice-based questions.",
            "meta": "Client metadata (browser, OS, viewport) when requested via `with_meta`.",
            "customMetadata": "Custom metadata attached to the response, when requested via `with_custom_metadata`.",
            "url": "The page URL the survey was shown on, when requested via `with_urls`.",
            "visitorSnapshot": "Visitor events/attributes at response time, when requested via `with_snapshots`.",
            "deletedAt": "When the response was deleted, only returned when `with_deleted_responses` is true.",
        },
    },
}
