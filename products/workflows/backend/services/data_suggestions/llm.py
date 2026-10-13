from typing import Any, Literal, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 120
_MAX_OUTPUT_TOKENS = 16000

Schema = TypeVar("Schema", bound=BaseModel)


def invoke_structured(
    *,
    team: Team,
    user: User,
    model: str,
    effort: Literal["low", "medium", "high"],
    feature: str,
    schema: type[Schema],
    system: str,
    human: str,
    excluded_values: frozenset[str],
) -> Schema | None:
    """One Claude call that answers in `schema`, or None when the call fails or the answer does not fit."""
    try:
        llm = MaxChatAnthropic(
            model=model,
            user=user,
            team=team,
            # PostHog covers these calls, so suggestions never draw on the customer's AI credits.
            billable=False,
            inject_context=False,
            streaming=False,
            disable_streaming=True,
            stream_usage=False,
            max_tokens=_MAX_OUTPUT_TOKENS,
            # Current Claude models only think adaptively, and a forced tool call (langchain's structured output)
            # does not work with thinking. The API's own JSON schema output does.
            thinking={"type": "adaptive"},
            model_kwargs={
                "output_config": {
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": strict_schema(schema, excluded_values)},
                }
            },
            default_request_timeout=_TIMEOUT_SECONDS,
            posthog_properties={"ai_product": "workflows", "ai_feature": feature},
        )
        response = llm.invoke([("system", system), ("human", human)])
        return schema.model_validate_json(_response_text(response.content))
    except ValidationError:
        logger.warning("workflows.data_suggestions.llm_malformed", team_id=team.id, feature=feature, exc_info=True)
        return None
    except Exception:
        logger.warning("workflows.data_suggestions.llm_failed", team_id=team.id, feature=feature, exc_info=True)
        return None


def strict_schema(schema: type[BaseModel], excluded_values: frozenset[str]) -> dict[str, Any]:
    # The API's JSON schema output requires every object to forbid properties the schema does not list.
    # Removing a value from every enum means the model cannot pick a channel the team has not connected.
    def close_objects(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            if isinstance(node.get("enum"), list):
                node["enum"] = [value for value in node["enum"] if value not in excluded_values]
            for value in node.values():
                close_objects(value)
        elif isinstance(node, list):
            for value in node:
                close_objects(value)

    json_schema = schema.model_json_schema()
    close_objects(json_schema)
    return json_schema


def _response_text(content: str | list[Any]) -> str:
    # With thinking on, the answer is the text blocks after the thinking blocks.
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
    )
