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
    "models": {
        "description": "Language models that Promptwatch supports, including deprecated models.",
        "docs_url": "https://promptwatch.com/docs/api-reference/models/list-models",
        "columns": {
            "id": "Unique model identifier, as used in responses and monitors.",
            "label": "Readable model label.",
            "provider": "Provider identifier, for example openai or anthropic.",
            "providerName": "Readable provider name.",
            "modelName": "Model name.",
            "apiIdentifier": "API identifier for the model.",
            "description": "Model description.",
            "searchEnabled": "Whether search is enabled for this model.",
            "liveSearch": "Whether this model supports live search.",
            "deprecated": "Whether the model is deprecated.",
        },
    },
    "brands": {
        "description": "Brands tracked in the project, with their relation to the project.",
        "docs_url": "https://promptwatch.com/docs/api-reference/brands/list-brands",
        "columns": {
            "id": "Unique brand identifier.",
            "name": "Brand name.",
            "domain": "Brand hostname, when known.",
            "relation": "Relation to the project: SELF, DIRECT_COMPETITOR, OTHER, or IGNORED.",
        },
    },
    "grouped_citations": {
        "description": (
            "Cited URLs over the last 92 days, with citation count, share, and position. "
            "Each sync keeps the 1,000 most cited URLs."
        ),
        "docs_url": "https://promptwatch.com/docs/api-reference/citations/grouped-citations",
        "columns": {
            "urlId": "Unique identifier of the cited URL.",
            "url": "Cited page, with its title, source type, content type, page rank, traffic, and domain metrics.",
            "count": "Number of times this URL was cited.",
            "citationShare": "Percentage of analyzed responses that cite this URL.",
            "avgPosition": "Average citation position, starting at 1.",
            "minPosition": "Best (lowest) citation position.",
            "maxPosition": "Worst (highest) citation position.",
            "models": "Models that cited this URL most often.",
            "totalModels": "Number of models that cited this URL.",
            "providers": "Providers of the models that cited this URL.",
        },
    },
    "visitor_trends": {
        "description": "Daily website visits from AI referrers, with one row for each date and referrer.",
        "docs_url": "https://promptwatch.com/docs/api-reference/analytics/visitor-trends",
        "columns": {
            "date": "Day of the visits, in UTC.",
            "referrer": "AI referrer domain, for example chatgpt.com.",
            "visitors": "Number of visits from this referrer on this day.",
        },
    },
}
