from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "jobs": {
        "description": "A localization job — one target locale within a job group, tracking the translation of submitted content through your Lingo.dev localization engine.",
        "docs_url": "https://lingo.dev/en/docs/api/localization/list",
        "columns": {
            "id": "Unique identifier for the localization job, prefixed with ljb_.",
            "groupId": "Identifier of the parent job group the job belongs to, prefixed with ljg_.",
            "targetLocale": "The locale this job translates the submitted content into (e.g. ja, es).",
            "status": "Current job status: queued, processing, completed, completed_with_warnings, or failed.",
            "warnings": "Warnings raised while processing the job, empty when the job completed cleanly.",
            "createdAt": "Timestamp when the job was created.",
            "completedAt": "Timestamp when the job reached a terminal state, null while queued or processing.",
        },
    },
}
