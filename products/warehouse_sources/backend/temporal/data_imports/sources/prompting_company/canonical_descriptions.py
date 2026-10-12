from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "published_content": {
        "description": "Published content for the selected product. Drafts and archived content are excluded.",
        "docs_url": "https://docs.promptingcompany.com/api/reference/content/list-content",
        "columns": {
            "id": "Unique document identifier.",
            "title": "Document title.",
            "filePath": "Content path within the product.",
            "publishedAt": "Time when the document was published.",
            "createdAt": "Time when the document was created.",
            "updatedAt": "Time when the document was last updated.",
            "domains": "Domains associated with the document.",
        },
    },
    "prompt_suggestions": {
        "description": "Suggested prompts for the selected product, with target personas and answer engines.",
        "docs_url": "https://docs.promptingcompany.com/api/reference/visibility-&-mentions/list-prompt-suggestions-for-a-product",
        "columns": {
            "id": "Unique suggestion identifier.",
            "message": "Suggested prompt text.",
            "topicId": "Topic associated with the suggestion.",
            "answerEngines": "Answer engines selected for the suggestion.",
            "userPersonaId": "Persona associated with the suggestion.",
            "createdAt": "Time when the suggestion was created.",
        },
    },
    "simulation_runs": {
        "description": "Agent simulation runs across the organization, including results, token usage, and cost.",
        "docs_url": "https://docs.promptingcompany.com/api/reference/simulations/list-agent-simulation-runs",
        "columns": {
            "id": "Unique run identifier.",
            "environmentId": "Environment used for the run.",
            "taskId": "Task attempted during the run.",
            "overallScore": "Overall evaluation score.",
            "tokensUsed": "Number of tokens used during the run.",
            "costUsd": "Run cost in US dollars.",
            "createdAt": "Time when the run was created.",
        },
    },
    "share_of_voice": {
        "description": "Daily share of voice for the selected product, using a one-day calculation window in UTC.",
        "docs_url": "https://docs.promptingcompany.com/api/reference/visibility-&-mentions/get-rolling-share-of-voice-time-series-and-breakdowns",
        "columns": {
            "date": "UTC calendar date of the measurement.",
            "sov": "Percentage of completed runs that mention the product.",
            "mentions": "Number of completed runs that mention the product on this date.",
            "runs": "Number of completed runs on this date.",
        },
    },
}
