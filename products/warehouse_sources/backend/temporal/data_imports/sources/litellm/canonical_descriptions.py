"""Canonical, documentation-sourced descriptions for LiteLLM endpoints and columns.

Sourced from the LiteLLM proxy docs (https://docs.litellm.ai/docs/proxy/cost_tracking) and the
proxy's database schema. Keyed by the endpoint names in `settings.py`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "spend_logs": {
        "description": "One row per request the LiteLLM proxy served, with its cost, tokens and the key, user and team that sent it.",
        "docs_url": "https://docs.litellm.ai/docs/proxy/cost_tracking",
        "columns": {
            "request_id": "Unique identifier for the request.",
            "call_type": "Kind of call, such as completion, embedding or image generation.",
            "api_key": "Hash of the virtual key that sent the request.",
            "spend": "Cost of the request in US dollars.",
            "total_tokens": "Prompt and completion tokens together.",
            "prompt_tokens": "Tokens in the prompt.",
            "completion_tokens": "Tokens in the completion.",
            "startTime": "Time the proxy received the request.",
            "endTime": "Time the proxy finished the request.",
            "request_duration_ms": "Time the request took, in milliseconds.",
            "completionStartTime": "Time the first completion token arrived.",
            "model": "Model the provider served.",
            "model_id": "Identifier of the deployment in the proxy's model list.",
            "model_group": "Public model name the caller asked for.",
            "custom_llm_provider": "Provider that served the request, such as openai or bedrock.",
            "api_base": "Provider endpoint the proxy called.",
            "user": "User id the caller passed in the request.",
            "metadata": "Request metadata the proxy stored, such as key alias and team alias.",
            "cache_hit": "Whether the response came from the proxy cache.",
            "request_tags": "Tags the caller attached to the request.",
            "team_id": "Team that owns the key.",
            "organization_id": "Organization that owns the key.",
            "end_user": "End user id the caller passed in the request.",
            "session_id": "Session the request belongs to.",
            "status": "Outcome of the request, such as success or failure.",
        },
    },
    "keys": {
        "description": "A virtual key issued by the LiteLLM proxy, with its budget and spend.",
        "docs_url": "https://docs.litellm.ai/docs/proxy/virtual_keys",
        "columns": {
            "token": "Hash of the key.",
            "key_name": "Abbreviated form of the key, for display.",
            "key_alias": "Name given to the key.",
            "spend": "Total spend on the key in US dollars.",
            "max_budget": "Spend limit of the key in US dollars.",
            "budget_duration": "Period after which the key's spend resets.",
            "models": "Models the key may call. Empty means every model.",
            "user_id": "User that owns the key.",
            "team_id": "Team that owns the key.",
            "expires": "Time the key expires.",
            "blocked": "Whether the key is blocked.",
            "created_at": "Time the key was created.",
        },
    },
    "users": {
        "description": "A user of the LiteLLM proxy, with their role, budget and spend.",
        "docs_url": "https://docs.litellm.ai/docs/proxy/users",
        "columns": {
            "user_id": "Unique identifier for the user.",
            "user_email": "Email address of the user.",
            "user_role": "Role of the user, such as proxy_admin or internal_user.",
            "spend": "Total spend of the user in US dollars.",
            "max_budget": "Spend limit of the user in US dollars.",
            "teams": "Teams the user belongs to.",
            "key_count": "Number of keys the user owns.",
            "created_at": "Time the user was created.",
        },
    },
    "teams": {
        "description": "A team on the LiteLLM proxy, with its members, budget and spend.",
        "docs_url": "https://docs.litellm.ai/docs/proxy/team_budgets",
        "columns": {
            "team_id": "Unique identifier for the team.",
            "team_alias": "Name of the team.",
            "spend": "Total spend of the team in US dollars.",
            "max_budget": "Spend limit of the team in US dollars.",
            "models": "Models the team may call. Empty means every model.",
            "members_with_roles": "Members of the team and their roles.",
            "organization_id": "Organization the team belongs to.",
        },
    },
    "models": {
        "description": "A model deployment configured on the LiteLLM proxy.",
        "docs_url": "https://docs.litellm.ai/docs/proxy/model_management",
        "columns": {
            "model_id": "Identifier of the deployment, taken from model_info.id.",
            "model_name": "Public model name callers use.",
            "litellm_params": "Provider settings of the deployment, without credentials.",
            "model_info": "Pricing, context window and other details of the deployment.",
        },
    },
}
