import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeVar

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel, ValidationError

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

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
    allowed_values: Mapping[str, Sequence[str]] | None = None,
    analytics_client: Any = None,
) -> Schema | None:
    """One Claude call that answers in `schema`, or None when the call fails or the answer does not fit.

    The generation goes to LLM analytics through `analytics_client`, failed calls included, so a bad rollout
    shows up there with the model's input and output.
    """
    properties = {"ai_product": "workflows", "ai_feature": feature, "team_id": team.id}
    callbacks: list[BaseCallbackHandler] = []
    if analytics_client is not None:
        callbacks.append(
            CallbackHandler(
                analytics_client,
                distinct_id=user.distinct_id,
                trace_id=f"workflows-{feature}-{uuid.uuid4()}",
                properties=properties,
                privacy_mode=is_privacy_mode_enabled(team),
            )
        )
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
                    "format": {
                        "type": "json_schema",
                        "schema": strict_schema(schema, excluded_values, allowed_values or {}),
                    },
                }
            },
            default_request_timeout=_TIMEOUT_SECONDS,
            # Retries would outlast the three minutes the frontend polls for, so a failed call fails the run.
            max_retries=0,
            posthog_properties=properties,
        )
        response = llm.invoke([("system", system), ("human", human)], config=RunnableConfig(callbacks=callbacks))
        return schema.model_validate_json(_response_text(response.content))
    except ValidationError as error:
        # The error's input holds model output, which can carry project content, so only types and paths are logged.
        logger.warning(
            "workflows.data_suggestions.llm_malformed",
            team_id=team.id,
            feature=feature,
            errors=[{"type": item["type"], "loc": item["loc"]} for item in error.errors(include_input=False)],
        )
        return None
    except Exception as error:
        logger.warning("workflows.data_suggestions.llm_failed", team_id=team.id, feature=feature, exc_info=True)
        capture_exception(error, {"team_id": team.id, "ai_feature": feature})
        return None


def strict_schema(
    schema: type[BaseModel], excluded_values: frozenset[str], allowed_values: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    # The API's JSON schema output requires every object to forbid properties the schema does not list.
    # Removing a value from every enum means the model cannot pick a channel the team has not connected.
    # A property in `allowed_values` only accepts those strings, so the model cannot make up an event name. It is
    # restricted after the exclusions, so an event named like a channel stays available.
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

    def restrict(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                for name, values in allowed_values.items():
                    if name in node.get("properties", {}):
                        _restrict_strings(node["properties"][name], list(values))
            for value in node.values():
                restrict(value)
        elif isinstance(node, list):
            for value in node:
                restrict(value)

    json_schema = schema.model_json_schema()
    close_objects(json_schema)
    restrict(json_schema)
    return json_schema


def _restrict_strings(property_schema: dict[str, Any], values: list[str]) -> None:
    # A nullable string is `anyOf: [{type: string}, {type: null}]`, so the enum goes on the string branch.
    branches = property_schema.get("anyOf", [property_schema])
    for branch in branches:
        if branch.get("type") == "string":
            branch["enum"] = values


def _response_text(content: str | list[Any]) -> str:
    # With thinking on, the answer is the text blocks after the thinking blocks.
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
    )
