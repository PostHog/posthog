from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Doc-sourced descriptions for Jotform's well-known tables. See https://api.jotform.com/docs/.
# Partial coverage is fine — any missing endpoint/column falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "forms": {
        "description": "One row per form on the account, with its title, status, and submission counts.",
        "docs_url": "https://api.jotform.com/docs/#user-forms",
        "columns": {
            "id": "Unique identifier of the form.",
            "username": "Username of the account that owns the form.",
            "title": "Display title of the form.",
            "height": "Configured form height in pixels.",
            "url": "Public URL of the form.",
            "status": "Form status (e.g. ENABLED, DISABLED, DELETED).",
            "created_at": "Timestamp the form was created.",
            "updated_at": "Timestamp the form was last updated.",
            "last_submission": "Timestamp of the most recent submission to the form.",
            "new": "Number of unread submissions.",
            "count": "Total number of submissions to the form.",
            "type": "Form type (e.g. LEGACY, CARD).",
            "favorite": "Whether the form is marked as a favorite.",
            "archived": "Whether the form is archived.",
        },
    },
    "submissions": {
        "description": "One row per submission across all of the account's forms, including answers.",
        "docs_url": "https://api.jotform.com/docs/#user-submissions",
        "columns": {
            "id": "Unique identifier of the submission.",
            "form_id": "Identifier of the form the submission belongs to.",
            "ip": "IP address the submission was made from.",
            "created_at": "Timestamp the submission was created.",
            "updated_at": "Timestamp the submission was last updated.",
            "status": "Submission status (e.g. ACTIVE, OVERQUOTA).",
            "new": "Whether the submission is unread.",
            "flag": "Whether the submission is flagged.",
            "notes": "Free-text notes attached to the submission.",
            "answers": "Object of the submitted answers keyed by question id.",
        },
    },
    "reports": {
        "description": "One row per report (e.g. grid, table, or visual report) created on the account.",
        "docs_url": "https://api.jotform.com/docs/#user-reports",
        "columns": {
            "id": "Unique identifier of the report.",
            "form_id": "Identifier of the form the report is built from.",
            "title": "Display title of the report.",
            "type": "Report type (e.g. excel, csv, grid, table).",
            "status": "Report status.",
            "url": "Public URL of the report.",
            "created_at": "Timestamp the report was created.",
            "updated_at": "Timestamp the report was last updated.",
        },
    },
    "questions": {
        "description": "One row per question (field) of a form. `qid` is unique only within a form, so each row also carries `form_id`.",
        "docs_url": "https://api.jotform.com/docs/#form-id-questions",
        "columns": {
            "form_id": "Identifier of the form the question belongs to.",
            "qid": "Question identifier, unique within its form.",
            "type": "Question/control type (e.g. control_textbox, control_email).",
            "text": "Label shown to respondents for the question.",
            "name": "Internal field name of the question.",
            "order": "Display order of the question within the form.",
        },
    },
}
