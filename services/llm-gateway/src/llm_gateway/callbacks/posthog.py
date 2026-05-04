import ast
import asyncio
import json
from functools import partial
from typing import Any
from uuid import UUID, uuid4, uuid5

import structlog
from posthoganalytics import Posthog

from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.request_context import (
    get_auth_user,
    get_posthog_flags,
    get_posthog_properties,
    get_product,
    get_time_to_first_token,
)

logger = structlog.get_logger(__name__)


def _replace_binary_content(data: Any) -> Any:
    """
    Replace binary content with metadata before storing in PostHog.
    Handles both raw bytes/tuples and their stringified repr() forms.
    """
    match data:
        case None | int() | float() | bool():
            return data
        case str() if "b'\\x" in data or 'b"\\x' in data:
            try:
                return _replace_binary_content(ast.literal_eval(data))
            except (ValueError, SyntaxError):
                return data
        case str():
            return data
        case bytes():
            return {"type": "binary", "size_bytes": len(data)}
        case tuple():
            return tuple(_replace_binary_content(item) for item in data)
        case list():
            return [_replace_binary_content(item) for item in data]
        case dict():
            return {k: _replace_binary_content(v) for k, v in data.items()}
        case _:
            return data


_MAX_CAPTURE_SIZE = 15 * 1024 * 1024
_MIN_FIELD_SIZE_TO_TRUNCATE = 10 * 1024
_TRUNCATION_MARKER = "[truncated: content too large for capture]"
_TRUNCATABLE_FIELDS = ("$ai_output_choices", "$ai_input")

# Stable namespace for hashing non-UUID trace identifiers (e.g. Claude Code's
# JSON-encoded session blobs sent via Anthropic's metadata.user_id) into a
# deterministic UUID. Generated once and frozen so the same input always maps
# to the same trace UUID across runs and processes.
_TRACE_ID_NAMESPACE = UUID("8d4f6b7e-6a3e-4f3a-9f3b-3b6f4d2e8a1a")


def _normalize_trace_id(raw: Any) -> str:
    """Normalize an incoming trace identifier into a UUID string.

    LLM Analytics renders trace links as `/llm-observability/traces/<id>`, so
    `$ai_trace_id` must be a URL-safe identifier. Anthropic's
    `metadata.user_id` is a free-form string that Claude Code populates with a
    serialized JSON session blob — passing that through verbatim produces
    unopenable trace links. We hash anything that isn't already a UUID into a
    deterministic UUID5 so identical inputs continue to share the same trace.
    """
    if not raw:
        return str(uuid4())
    if not isinstance(raw, str):
        raw = json.dumps(raw, default=str, sort_keys=True)
    try:
        return str(UUID(raw))
    except ValueError:
        return str(uuid5(_TRACE_ID_NAMESPACE, raw))


def _truncate_for_capture(properties: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(properties, default=str)
    if len(serialized) <= _MAX_CAPTURE_SIZE:
        return properties

    result = dict(properties)
    for field in _TRUNCATABLE_FIELDS:
        if field not in result:
            continue
        field_size = len(json.dumps(result[field], default=str))
        if field_size < _MIN_FIELD_SIZE_TO_TRUNCATE:
            continue
        result[field] = _TRUNCATION_MARKER
        if len(json.dumps(result, default=str)) <= _MAX_CAPTURE_SIZE:
            break
    return result


class PostHogCallback(InstrumentedCallback):
    """Custom PostHog callback for LLM analytics."""

    callback_name = "posthog"

    def __init__(self, api_key: str, host: str):
        super().__init__()
        self._api_key = api_key
        self._host = host

    async def _on_success(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        metadata = self._extract_metadata(kwargs)
        auth_user = get_auth_user()
        product = get_product()

        # Anthropic's metadata.user_id is co-opted as a trace id by Claude Code
        # (see _normalize_trace_id), and Claude Code sends a JSON blob there.
        trace_id = _normalize_trace_id(metadata.get("user_id"))
        if auth_user and auth_user.auth_method == "oauth_access_token":
            distinct_id = auth_user.distinct_id
        else:
            distinct_id = end_user_id or (auth_user.distinct_id if auth_user else str(uuid4()))
        team_id = auth_user.team_id if auth_user and auth_user.team_id else None

        logger.debug(
            "PostHog callback _on_success",
            end_user_id=end_user_id,
            distinct_id=distinct_id,
            team_id=team_id,
            product=product,
            model=standard_logging_object.get("model", ""),
        )

        is_streaming = standard_logging_object.get("stream", False)

        properties: dict[str, Any] = {
            "$ai_model": standard_logging_object.get("model", ""),
            "$ai_provider": standard_logging_object.get("custom_llm_provider", ""),
            "$ai_input": _replace_binary_content(standard_logging_object.get("messages")),
            "$ai_input_tokens": standard_logging_object.get("prompt_tokens", 0),
            "$ai_output_tokens": standard_logging_object.get("completion_tokens", 0),
            "$ai_latency": standard_logging_object.get("response_time", 0.0),
            "$ai_stream": is_streaming,
            "$ai_trace_id": trace_id,
            "$ai_span_id": str(uuid4()),
            "ai_product": product,
        }

        posthog_properties = get_posthog_properties() or {}
        if isinstance(posthog_properties, dict):
            for key, value in posthog_properties.items():
                properties[key] = value

        posthog_flags = get_posthog_flags() or {}
        if isinstance(posthog_flags, dict):
            for flag_key, variant in posthog_flags.items():
                properties[f"$feature/{flag_key}"] = variant

        if team_id:
            properties["team_id"] = team_id

        response_cost = standard_logging_object.get("response_cost")
        if response_cost is not None:
            properties["$ai_total_cost_usd"] = response_cost

        response = standard_logging_object.get("response")
        if response:
            properties["$ai_output_choices"] = response

        # Add time to first token for streaming requests
        time_to_first_token = get_time_to_first_token()
        if time_to_first_token is not None:
            properties["$ai_time_to_first_token"] = time_to_first_token

        properties = _truncate_for_capture(properties)

        capture_kwargs: dict[str, Any] = {
            "distinct_id": distinct_id,
            "event": "$ai_generation",
            "properties": properties,
        }
        if team_id:
            capture_kwargs["groups"] = {"project": team_id}

        logger.debug(
            "PostHog capturing event",
            distinct_id=distinct_id,
            posthog_event="$ai_generation",
            properties=properties,
            groups=capture_kwargs.get("groups"),
        )
        self._capture_fire_and_forget(**capture_kwargs)

    async def _on_failure(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        standard_logging_object = kwargs.get("standard_logging_object", {})
        metadata = self._extract_metadata(kwargs)
        auth_user = get_auth_user()
        product = get_product()

        # Anthropic's metadata.user_id is co-opted as a trace id by Claude Code
        # (see _normalize_trace_id), and Claude Code sends a JSON blob there.
        trace_id = _normalize_trace_id(metadata.get("user_id"))
        if auth_user and auth_user.auth_method == "oauth_access_token":
            distinct_id = auth_user.distinct_id
        else:
            distinct_id = end_user_id or (auth_user.distinct_id if auth_user else str(uuid4()))
        team_id = auth_user.team_id if auth_user and auth_user.team_id else None

        logger.debug(
            "PostHog callback _on_failure",
            end_user_id=end_user_id,
            distinct_id=distinct_id,
            team_id=team_id,
            product=product,
        )

        properties: dict[str, Any] = {
            "$ai_model": standard_logging_object.get("model", ""),
            "$ai_provider": standard_logging_object.get("custom_llm_provider", ""),
            "$ai_trace_id": trace_id,
            "$ai_is_error": True,
            "$ai_error": standard_logging_object.get("error_str", ""),
            "ai_product": product,
        }

        posthog_properties = get_posthog_properties() or {}
        if isinstance(posthog_properties, dict):
            for key, value in posthog_properties.items():
                properties[key] = value

        posthog_flags = get_posthog_flags() or {}
        if isinstance(posthog_flags, dict):
            for flag_key, variant in posthog_flags.items():
                properties[f"$feature/{flag_key}"] = variant

        if team_id:
            properties["team_id"] = team_id

        capture_kwargs: dict[str, Any] = {
            "distinct_id": distinct_id,
            "event": "$ai_generation",
            "properties": properties,
        }
        if team_id:
            capture_kwargs["groups"] = {"project": team_id}

        logger.debug(
            "PostHog capturing error event",
            distinct_id=distinct_id,
            posthog_event="$ai_generation",
            properties=properties,
            groups=capture_kwargs.get("groups"),
        )
        self._capture_fire_and_forget(**capture_kwargs)

    def _capture_fire_and_forget(self, **capture_kwargs: Any) -> None:
        """
        Initializes a separate client for the capture operation to avoid payload bloat.
        Fires in background thread to avoid blocking the main thread.
        """
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, partial(self._capture_sync, **capture_kwargs))

    def _capture_sync(self, **capture_kwargs: Any) -> None:
        client = Posthog(
            self._api_key,
            host=self._host,
            sync_mode=True,
            enable_local_evaluation=False,
        )
        try:
            client.capture(**capture_kwargs)
        except Exception as e:
            client.capture_exception(e, **capture_kwargs)
            logger.exception("posthog_capture_failed", error=str(e))
        finally:
            client.shutdown()

    def _extract_metadata(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        litellm_params = kwargs.get("litellm_params", {}) or {}
        return litellm_params.get("metadata", {}) or {}
