from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "requests": {
        "description": (
            "One row per LLM request logged through Helicone, with the model, provider, token usage, "
            "cost, latency, user, and custom properties attached to the call."
        ),
        "docs_url": "https://docs.helicone.ai/rest/request/post-v1requestquery-clickhouse",
        "columns": {
            "request_id": "Unique identifier (UUID) of the logged request.",
            "request_created_at": "Timestamp when Helicone received the request.",
            "response_id": "Unique identifier of the response paired with the request.",
            "response_created_at": "Timestamp when the provider's response was received.",
            "response_status": "HTTP status code returned by the LLM provider.",
            "request_body": "The request payload sent to the provider (may be truncated or offloaded to storage).",
            "response_body": "The response payload from the provider (may be truncated or offloaded to storage).",
            "signed_body_url": "Short-lived signed URL to the full request/response bodies in Helicone's storage.",
            "request_model": "Model name as sent in the request.",
            "response_model": "Model name as reported in the provider's response.",
            "model": "Resolved model name for the request.",
            "provider": "LLM provider that served the request (e.g. OpenAI, Anthropic).",
            "request_path": "Provider API path the request was sent to.",
            "target_url": "Full provider URL the request was forwarded to.",
            "request_user_id": "User identifier attached to the request via the Helicone-User-Id header.",
            "request_properties": "Custom properties attached to the request via Helicone-Property-* headers.",
            "prompt_tokens": "Number of prompt (input) tokens used by the request.",
            "completion_tokens": "Number of completion (output) tokens generated.",
            "total_tokens": "Total tokens used by the request.",
            "reasoning_tokens": "Reasoning tokens used, for models that report them.",
            "prompt_cache_read_tokens": "Prompt tokens served from the provider's prompt cache.",
            "prompt_cache_write_tokens": "Prompt tokens written to the provider's prompt cache.",
            "cost": "Cost of the request as calculated by Helicone.",
            "delay_ms": "End-to-end latency of the request in milliseconds.",
            "time_to_first_token": "Milliseconds until the first token of the response arrived.",
            "prompt_id": "Identifier of the Helicone prompt used for the request, if any.",
            "prompt_version": "Version of the Helicone prompt used for the request, if any.",
            "feedback_rating": "User feedback rating submitted for the request, if any.",
            "scores": "Evaluation scores attached to the request, if any.",
            "country_code": "Country the request originated from.",
            "cache_enabled": "Whether Helicone response caching was enabled for the request.",
            "cached": "Whether the response was served from Helicone's cache.",
        },
    },
    "sessions": {
        "description": (
            "Aggregated metrics for each Helicone session (requests grouped via the Helicone-Session-Id "
            "header): totals for cost, requests, and tokens, plus the users involved."
        ),
        "docs_url": "https://docs.helicone.ai/rest/session/post-v1sessionquery",
        "columns": {
            "session_id": "Unique identifier of the session (Helicone-Session-Id header value).",
            "session_name": "Name given to the session via the Helicone-Session-Name header.",
            "created_at": "Timestamp of the first request in the session.",
            "latest_request_created_at": "Timestamp of the most recent request in the session.",
            "total_cost": "Total cost of all requests in the session.",
            "total_requests": "Number of requests in the session.",
            "prompt_tokens": "Total prompt (input) tokens used across the session.",
            "completion_tokens": "Total completion (output) tokens generated across the session.",
            "total_tokens": "Total tokens used across the session.",
            "avg_latency": "Average request latency across the session, in milliseconds.",
            "user_ids": "User identifiers that appear on the session's requests.",
        },
    },
    "users": {
        "description": (
            "Per-user usage aggregates across all logged requests: request count, token usage, and cost, "
            "keyed by the Helicone-User-Id header value."
        ),
        "docs_url": "https://docs.helicone.ai/rest/user/post-v1userquery",
        "columns": {
            "user_id": "User identifier attached to requests via the Helicone-User-Id header.",
            "count": "Number of requests made by the user.",
            "prompt_tokens": "Total prompt (input) tokens used by the user.",
            "completion_tokens": "Total completion (output) tokens generated for the user.",
            "cost": "Total cost of the user's requests.",
        },
    },
    "prompts": {
        "description": "Prompts managed in Helicone's prompt registry, with their names and tags.",
        "docs_url": "https://docs.helicone.ai/rest/prompts/post-v1prompt-2025-query",
        "columns": {
            "id": "Unique identifier of the prompt.",
            "name": "Name of the prompt.",
            "tags": "Tags associated with the prompt.",
            "created_at": "Timestamp when the prompt was created.",
        },
    },
}
