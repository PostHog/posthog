from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "threads": {
        "description": "Conversations with nested question-answer pairs, feedback, tags, end user, and integration data.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-projects-threads-list",
        "columns": {
            "id": "Unique conversation identifier.",
            "created_at": "Time the conversation started in UTC.",
            "last_activity_at": "Time of the most recent conversation activity, which can be null.",
            "question_answers": "Question-answer pairs included in the thread listing.",
            "has_more_question_answers": "Whether the conversation has question-answer pairs beyond those included in the listing.",
        },
    },
    "end_users": {
        "description": "People who interact with the project's assistant.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-projects-end-users-list",
        "columns": {"id": "Unique end user identifier.", "created_at": "Time the end user record was created."},
    },
    "sources": {
        "description": "Knowledge sources connected to the project.",
        "docs_url": "https://docs.kapa.ai/api/reference/ingestion-v-1-projects-sources-list",
        "columns": {"id": "Unique knowledge source identifier.", "created_at": "Time the source was created."},
    },
    "source_groups": {
        "description": "Groups of knowledge sources, including nested groups.",
        "docs_url": "https://docs.kapa.ai/api/reference/ingestion-v-1-projects-source-groups-list",
        "columns": {"id": "Unique source group identifier.", "created_at": "Time the group was created."},
    },
    "integrations": {
        "description": "Deployment integrations configured for the project.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-projects-integrations-list",
        "columns": {"id": "Unique integration identifier.", "created_at": "Time the integration was created."},
    },
    "activity": {
        "description": "Project activity snapshot with aggregate and per-integration query, feedback, user, and deflection statistics.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-projects-activity-retrieve",
        "columns": {
            "project_id": "Project identifier attached to the activity snapshot.",
            "aggregate_statistics": "Activity totals for the project.",
            "statistics_by_integration": "Activity totals grouped by deployment integration.",
        },
    },
    "top_question_periods": {
        "description": "Completed weekly, monthly, or quarterly periods used to group frequently asked questions.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-projects-top-questions-periods-list",
        "columns": {"id": "Unique period identifier.", "start_date": "Start date of the period in UTC."},
    },
    "coverage_gap_periods": {
        "description": "Completed periods used to group conversations with uncertain answers.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-projects-coverage-gaps-periods-list",
        "columns": {"id": "Unique period identifier.", "start_date": "Start date of the period in UTC."},
    },
    "top_questions": {
        "description": "Question clusters for each completed period, with titles, summaries, counts, and recent conversations.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-top-questions-periods-retrieve",
        "columns": {
            "id": "Unique cluster identifier.",
            "period_id": "Identifier of the parent analytics period.",
            "period_start_date": "Start date of the parent period in UTC.",
            "thread_count": "Total conversation count, including conversations outside the inline sample.",
            "threads": "At most 100 of the most recent conversations in the cluster.",
        },
    },
    "coverage_gaps": {
        "description": "Clusters of uncertain answers for each completed period, with suggestions for improving documentation.",
        "docs_url": "https://docs.kapa.ai/api/reference/query-v-1-coverage-gaps-periods-retrieve",
        "columns": {
            "id": "Unique cluster identifier.",
            "period_id": "Identifier of the parent analytics period.",
            "period_start_date": "Start date of the parent period in UTC.",
            "thread_count": "Total conversation count, including conversations outside the inline sample.",
            "threads": "At most 100 of the most recent conversations in the cluster.",
        },
    },
}
