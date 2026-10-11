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
    "form_metadata": {
        "description": "The question catalog for a Fillout form: every question, calculation, URL parameter, scheduling and payment field, with the ids that submission answers reference.",
        "docs_url": "https://www.fillout.com/help/api-reference/get-form-metadata",
        "columns": {
            "form_id": "The public identifier of the form this metadata describes.",
            "id": "The public identifier of the form.",
            "name": "The name of the form.",
            "questions": "The form's questions, each with id, name, and type.",
            "calculations": "The form's calculation fields, each with id, name, and type.",
            "urlParameters": "The URL parameters the form accepts, each with id and name.",
            "scheduling": "The form's Fillout Scheduling fields, each with id and name.",
            "payments": "The form's Fillout Payments fields, each with id and name.",
            "quiz": "Quiz configuration, present only when quiz mode is enabled on the form.",
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
