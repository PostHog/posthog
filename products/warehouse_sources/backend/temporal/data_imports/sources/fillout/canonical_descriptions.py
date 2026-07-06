from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "forms": {
        "description": "A form (or survey) in your Fillout account.",
        "docs_url": "https://www.fillout.com/help/api-reference/get-forms",
        "columns": {
            "formId": "The public identifier of the form.",
            "name": "The name of the form.",
        },
    },
    "submissions": {
        "description": "A single finished submission (response) to a Fillout form.",
        "docs_url": "https://www.fillout.com/help/api-reference/get-all-submissions",
        "columns": {
            "submissionId": "Unique identifier for the submission within its form.",
            "form_id": "The public identifier of the form this submission belongs to.",
            "submissionTime": "When the submission was completed.",
            "lastUpdatedAt": "When the submission was last edited.",
            "questions": "Answers to the form's questions, each with id, name, type, and value.",
            "calculations": "Values of any calculation fields configured on the form.",
            "urlParameters": "URL parameters captured when the form was opened.",
            "scheduling": "Meetings scheduled through the form.",
            "payments": "Payments collected through the form.",
            "quiz": "Quiz score and maximum score, when the form is configured as a quiz.",
            "login": "The authenticated email address of the respondent, when login is required.",
        },
    },
}
