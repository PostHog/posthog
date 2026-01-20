from typing import Any
from uuid import uuid4

import posthoganalytics

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.request_context import get_auth_user


class PostHogCallback(InstrumentedCallback):
    """Custom PostHog callback for LLM analytics."""

    callback_name = "posthog"

    def __init__(self, api_key: str, host: str):
        super().__init__()
        self._api_key = api_key
        self._host = host
        posthoganalytics.api_key = api_key
        posthoganalytics.host = host

    async def _on_success(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        metadata = self._extract_metadata(kwargs)
        auth_user = get_auth_user()

        trace_id = metadata.get("user_id") or str(uuid4())
        distinct_id = auth_user.distinct_id if auth_user else str(uuid4())
        team_id = str(auth_user.team_id) if auth_user and auth_user.team_id else None

        properties: dict[str, Any] = {
            "$ai_model": standard_logging_object.get("model", ""),
            "$ai_provider": standard_logging_object.get("custom_llm_provider", ""),
            "$ai_input": standard_logging_object.get("messages"),
            "$ai_input_tokens": standard_logging_object.get("prompt_tokens", 0),
            "$ai_output_tokens": standard_logging_object.get("completion_tokens", 0),
            "$ai_latency": standard_logging_object.get("response_time", 0.0),
            "$ai_trace_id": trace_id,
            "$ai_span_id": str(uuid4()),
        }

        if team_id:
            properties["team_id"] = team_id

        response_cost = standard_logging_object.get("response_cost")
        if response_cost is not None:
            properties["$ai_total_cost_usd"] = response_cost

        response = standard_logging_object.get("response")
        if response:
            properties["$ai_output_choices"] = response

        capture_kwargs: dict[str, Any] = {
            "distinct_id": distinct_id,
            "event": "$ai_generation",
            "properties": properties,
        }
        if team_id:
            capture_kwargs["groups"] = {"project": team_id}

        posthoganalytics.capture(**capture_kwargs)

    async def _on_failure(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        metadata = self._extract_metadata(kwargs)
        auth_user = get_auth_user()

        trace_id = metadata.get("user_id") or str(uuid4())
        distinct_id = auth_user.distinct_id if auth_user else str(uuid4())
        team_id = str(auth_user.team_id) if auth_user and auth_user.team_id else None

        properties: dict[str, Any] = {
            "$ai_model": standard_logging_object.get("model", ""),
            "$ai_provider": standard_logging_object.get("custom_llm_provider", ""),
            "$ai_trace_id": trace_id,
            "$ai_is_error": True,
            "$ai_error": standard_logging_object.get("error_str", ""),
        }

        if team_id:
            properties["team_id"] = team_id

        capture_kwargs: dict[str, Any] = {
            "distinct_id": distinct_id,
            "event": "$ai_generation",
            "properties": properties,
        }
        if team_id:
            capture_kwargs["groups"] = {"project": team_id}

        posthoganalytics.capture(**capture_kwargs)

    def _extract_metadata(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        litellm_params = kwargs.get("litellm_params", {}) or {}
        return litellm_params.get("metadata", {}) or {}
