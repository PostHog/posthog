from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "prompts": {
        "description": "Tracked prompts and their response counts and visibility scores.",
        "docs_url": "https://promptwatch.com/docs/api-reference/prompts/list-prompts",
        "columns": {
            "id": "Unique prompt identifier.",
            "prompt": "Text sent to the model.",
            "llmMonitorId": "Monitor that owns this prompt.",
            "isActive": "Whether the prompt is active.",
            "createdAt": "Time when the prompt was created.",
            "updatedAt": "Time when the prompt was last updated.",
        },
    },
    "responses": {
        "description": "Model answers to tracked prompts, with citations and brand mentions.",
        "docs_url": "https://promptwatch.com/docs/api-reference/responses/list-responses",
        "columns": {
            "id": "Unique response identifier.",
            "content": "Text of the model answer.",
            "model": "Model that produced the answer.",
            "createdAt": "Time when the response was created.",
            "citations": "Sources cited in the answer.",
            "brandMentions": "Brands found in the answer, with metrics for each brand.",
            "visibilityScore": "Brand visibility score for this response.",
        },
    },
    "monitors": {
        "description": "Active project monitors. Visibility and response metrics use the API's default seven-day range.",
        "docs_url": "https://promptwatch.com/docs/api-reference/monitors/list-monitors",
        "columns": {
            "id": "Unique monitor identifier.",
            "name": "Monitor name.",
            "models": "Models selected for this monitor.",
        },
    },
    "tags": {
        "description": "Project tags and the number of prompts that use each tag.",
        "docs_url": "https://promptwatch.com/docs/api-reference/tags/list-tags",
        "columns": {
            "id": "Unique tag identifier.",
            "name": "Tag name.",
            "promptCount": "Number of prompts with this tag.",
        },
    },
    "topics": {
        "description": "Project topics and the number of prompts that use each topic.",
        "docs_url": "https://promptwatch.com/docs/api-reference/topics/list-topics",
        "columns": {
            "id": "Unique topic identifier.",
            "name": "Topic name.",
            "promptCount": "Number of prompts with this topic.",
        },
    },
    "personas": {
        "description": "Audience profiles configured for the project.",
        "docs_url": "https://promptwatch.com/docs/api-reference/personas/list-personas",
        "columns": {
            "id": "Unique persona identifier.",
            "name": "Persona name.",
            "description": "Description of the audience profile.",
        },
    },
}
