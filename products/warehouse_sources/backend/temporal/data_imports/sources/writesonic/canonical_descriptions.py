from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the official Writesonic GEO Presence API reference
# (https://docs.writesonic.com/reference).

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "performance_summary": {
        "description": "Daily aggregated GEO KPIs per tracked website: visibility score, rank, prompt and mention totals, averaged across prompts and AI platforms.",
        "docs_url": "https://docs.writesonic.com/reference/performance_summary_v2_geo_presence_business_export_performance_summary_get",
        "columns": {
            "date": "UTC day the metrics were measured on.",
            "website_id": "Unique identifier of the tracked website (your own site or a competitor).",
            "website_name": "Display name of the tracked website.",
            "website_url": "URL of the tracked website.",
            "total_prompts": "Number of prompts (queries) evaluated for the day.",
            "total_results": "Number of AI responses collected for the day.",
            "total_mentions": "Number of AI responses that mentioned the website.",
            "visibility_score": "Share of AI responses mentioning the website, as a percentage.",
            "rank": "Average position of the website within AI responses that mention it.",
        },
    },
    "performance_prompts": {
        "description": "Daily aggregated GEO performance per prompt: mentions, average visibility score, and average rank across the AI platforms that answered it.",
        "docs_url": "https://docs.writesonic.com/reference/performance_prompts_v2_geo_presence_business_export_performance_prompts_get",
        "columns": {
            "date": "UTC day the metrics were measured on.",
            "prompt_id": "Unique identifier of the prompt (query).",
            "prompt_text": "The prompt text as asked to the AI platforms.",
            "topic_id": "Unique identifier of the topic the prompt belongs to.",
            "topic_name": "Name of the topic the prompt belongs to.",
            "total_models": "Number of AI platforms that answered the prompt on the day.",
            "total_mentions": "Number of AI responses that mentioned your brand.",
            "avg_visibility_score": "Average visibility score for the prompt across platforms.",
            "avg_rank": "Average position of your brand within responses that mention it.",
        },
    },
    "performance_answers": {
        "description": "Raw, response-level AI answers per prompt-topic-platform for a day, including the answer text and the brands each response mentioned.",
        "docs_url": "https://docs.writesonic.com/reference/performance_answers_v2_geo_presence_business_export_performance_answers_get",
        "columns": {
            "date": "UTC day the response was collected on.",
            "prompt_id": "Unique identifier of the prompt (query).",
            "prompt": "The prompt text as asked to the AI platform.",
            "topic_id": "Unique identifier of the topic the prompt belongs to.",
            "topic_name": "Name of the topic the prompt belongs to.",
            "platform_id": "Unique identifier of the AI platform (e.g. ChatGPT, Perplexity).",
            "platform_name": "Name of the AI platform that produced the response.",
            "response_id": "Unique identifier of the individual AI response.",
            "answer_text": "Full text of the AI response.",
            "rank": "Position of your brand within the response, when mentioned.",
            "visibility_score": "Visibility score of your brand for this response.",
            "brand_mentions": "List of tracked websites mentioned in the response, with per-brand rank, visibility score, and the sentences that mention them.",
        },
    },
    "content_citations": {
        "description": "Citations (source pages) referenced by AI answers on a day, with the tracked websites each citation mentions and the responses that used it.",
        "docs_url": "https://docs.writesonic.com/reference/content_citations_v2_geo_presence_business_export_content_citations_get",
        "columns": {
            "date": "UTC day the export covers (stamped from the request date).",
            "citation_id": "Unique identifier of the citation.",
            "citation_title": "Title of the cited page.",
            "citation_uri": "URL of the cited page.",
            "citation_domain": "Domain of the cited page.",
            "created_at": "When the citation was first recorded.",
            "mentioned_websites_json": "Tracked websites (own and competitors) the citation mentions.",
            "responses_json": "AI responses that referenced the citation, with prompt, platform, and topic context.",
        },
    },
    "content_keywords": {
        "description": "Keywords and themes extracted from AI answers on a day, with the responses and sentiment behind each keyword.",
        "docs_url": "https://docs.writesonic.com/reference/content_keywords_v2_geo_presence_business_export_content_keywords_get",
        "columns": {
            "date": "UTC day the export covers (stamped from the request date).",
            "id": "Unique identifier of the keyword record.",
            "keyword": "The extracted keyword.",
            "theme": "Theme the keyword belongs to.",
            "subtheme": "Subtheme the keyword belongs to.",
            "responses": "AI responses the keyword was extracted from, with platform, query, sentence, and sentiment.",
            "created_at": "When the keyword was first recorded.",
        },
    },
    "topics": {
        "description": "The topics configured for the tracked site. Prompts are grouped under topics.",
        "docs_url": "https://docs.writesonic.com/reference/topics_export_v2_geo_presence_business_export_config_topics_get",
        "columns": {
            "topic_id": "Unique identifier of the topic.",
            "name": "Name of the topic.",
            "created_at": "When the topic was created.",
            "updated_at": "When the topic was last updated.",
        },
    },
    "platforms": {
        "description": "The AI platforms/models (e.g. ChatGPT, Perplexity, Google AI Overviews) enabled for the tracked site.",
        "docs_url": "https://docs.writesonic.com/reference/platforms_export_v2_geo_presence_business_export_config_platforms_get",
        "columns": {
            "platform_id": "Unique identifier of the AI platform.",
            "name": "Name of the AI platform.",
            "provider": "Provider of the AI platform.",
            "category_id": "Unique identifier of the platform category.",
            "category": "Category of the platform (e.g. Search Models).",
        },
    },
    "websites": {
        "description": "All websites associated with the tracked site: your own properties and every tracked competitor.",
        "docs_url": "https://docs.writesonic.com/reference/websites_export_v2_geo_presence_business_export_config_websites_get",
        "columns": {
            "website_id": "Unique identifier of the website.",
            "name": "Display name of the website.",
            "url": "URL of the website.",
            "is_competitor": "Whether the website is a tracked competitor.",
            "is_self_website": "Whether the website is one of your own properties.",
            "logo": "URL of the website's logo/favicon.",
            "created_at": "When the website was added.",
            "updated_at": "When the website was last updated.",
        },
    },
    "prompts": {
        "description": "All prompts (queries) configured for the tracked site, with their topic, country, and status.",
        "docs_url": "https://docs.writesonic.com/reference/prompts_export_v2_geo_presence_business_export_config_prompts_get",
        "columns": {
            "prompt_id": "Unique identifier of the prompt.",
            "prompt": "The prompt text.",
            "topic_id": "Unique identifier of the topic the prompt belongs to.",
            "topic": "Name of the topic the prompt belongs to.",
            "country_code": "Country the prompt is evaluated for.",
            "status": "Status of the prompt (e.g. ACTIVE).",
            "created_at": "When the prompt was created.",
            "updated_at": "When the prompt was last updated.",
        },
    },
}
