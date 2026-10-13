from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspaces": {
        "description": "A workspace groups forms and the members who can access them.",
        "docs_url": "https://developers.tally.so/api-reference/endpoint/workspaces/list",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Name of the workspace.",
            "index": "Position of the workspace in the account's workspace list.",
            "members": "Users who belong to the workspace.",
            "invites": "Pending invitations to join the workspace.",
            "folders": "Folders used to organize the workspace's forms.",
            "createdByUserId": "Identifier of the user who created the workspace.",
            "createdAt": "When the workspace was created.",
            "updatedAt": "When the workspace was last updated.",
        },
    },
    "forms": {
        "description": "A form or survey, including its publication status and submission count.",
        "docs_url": "https://developers.tally.so/api-reference/endpoint/forms/list",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "Name of the form.",
            "workspaceId": "Identifier of the workspace the form belongs to.",
            "status": "Publication status of the form: BLANK, DRAFT, PUBLISHED, or DELETED.",
            "numberOfSubmissions": "Number of submissions the form has received.",
            "isClosed": "Whether the form has stopped accepting submissions.",
            "payments": "Payment amounts and currencies configured on the form.",
            "createdAt": "When the form was created.",
            "updatedAt": "When the form was last updated.",
        },
    },
    "questions": {
        "description": (
            "A question in a form. Submission answers are keyed by question id, so this table is "
            "what makes the submissions table readable."
        ),
        "docs_url": "https://developers.tally.so/api-reference/endpoint/forms/questions/list",
        "columns": {
            "id": "Unique identifier for the question within its form.",
            "formId": "Identifier of the form the question belongs to.",
            "type": "Block type of the question, such as INPUT_TEXT or MULTIPLE_CHOICE.",
            "title": "Question text shown to respondents.",
            "isTitleModifiedByUser": "Whether the question title was edited rather than left at its default.",
            "isDeleted": "Whether the question has been removed from the form.",
            "numberOfResponses": "Number of responses recorded for this question.",
            "fields": "Individual input fields that make up the question block.",
            "createdAt": "When the question was created.",
            "updatedAt": "When the question was last updated.",
        },
    },
    "folders": {
        "description": "A folder used to organize a workspace's forms. Folders can nest under a parent folder.",
        "docs_url": "https://developers.tally.so/api-reference/endpoint/workspaces/folders/list",
        "columns": {
            "id": "Unique identifier for the folder within its workspace.",
            "name": "Name of the folder.",
            "workspaceId": "Identifier of the workspace the folder belongs to.",
            "parentId": "Identifier of the parent folder, or null for a top-level folder.",
            "createdByUserId": "Identifier of the user who created the folder.",
            "createdAt": "When the folder was created.",
            "updatedAt": "When the folder was last updated.",
        },
    },
    "form_analytics_metrics": {
        "description": (
            "Aggregate performance metrics for a form over its whole history. One row per form, "
            "recomputed on every sync."
        ),
        "docs_url": "https://developers.tally.so/api-reference/endpoint/forms/analytics/metrics",
        "columns": {
            "formId": "Identifier of the form the metrics are for.",
            "visits": "Number of visits to the form.",
            "visitDuration": "Average time spent on the form, in seconds.",
            "submissions": "Number of submissions the form received.",
            "uniqueRespondents": "Number of distinct respondents who submitted the form.",
            "totalViews": "Total number of times the form was viewed.",
            "starts": "Number of respondents who began filling in the form.",
            "completions": "Number of respondents who completed the form.",
            "completionDuration": "Average time to complete the form, in seconds.",
            "completionRate": "Share of starts that resulted in a completion.",
        },
    },
    "submissions": {
        "description": (
            "A single submission of a form, with every answer nested under `responses`. Answers are "
            "keyed by question id, which joins to the questions table."
        ),
        "docs_url": "https://developers.tally.so/api-reference/endpoint/forms/submissions/list",
        "columns": {
            "id": "Unique identifier for the submission within its form.",
            "formId": "Identifier of the form that was submitted.",
            "isCompleted": "Whether the respondent finished the form or left it partially filled in.",
            "submittedAt": "When the submission was recorded.",
            "previewUrl": "Link to a rendered preview of the submission.",
            "pdfUrl": "Link to a PDF export of the submission.",
            "responses": (
                "The answers in this submission. Each carries the question id it answers, the raw "
                "answer, a formatted answer, and the respondent and session identifiers."
            ),
        },
    },
    "webhooks": {
        "description": "A webhook registered on a form to push form events to an external URL.",
        "docs_url": "https://developers.tally.so/api-reference/endpoint/webhooks/get",
        "columns": {
            "id": "Unique identifier for the webhook.",
            "formId": "Identifier of the form the webhook is registered on.",
            "url": "Destination the webhook posts events to.",
            "signingSecret": "Secret used to sign webhook payloads, if one was set.",
            "httpHeaders": "Custom headers sent with each delivery.",
            "eventTypes": "Events the webhook is subscribed to.",
            "externalSubscriber": "Optional identifier of the system that registered the webhook.",
            "isEnabled": "Whether the webhook is currently delivering events.",
            "lastSyncedAt": "When the webhook last delivered successfully.",
            "createdAt": "When the webhook was created.",
            "updatedAt": "When the webhook was last updated.",
        },
    },
}
