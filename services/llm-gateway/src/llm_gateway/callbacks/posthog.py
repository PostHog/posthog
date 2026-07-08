import ast
import asyncio
import json
from functools import partial
from typing import Any
from uuid import UUID, uuid4, uuid5

import structlog
from posthoganalytics import Posthog

from llm_gateway.auth.models import resolve_distinct_id
from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.products.config import get_product_config
from llm_gateway.rate_limiting.cost_refresh import normalize_metric_labels
from llm_gateway.request_context import (
    get_auth_user,
    get_effort,
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


# Capture rejects events whose Kafka message exceeds message.max.bytes (~1 MB,
# the librdkafka default) with a 413, and the posthoganalytics client drops
# events over its own ~900 KB ceiling. $ai_generation events carry the full
# prompt/completion via $ai_input / $ai_output_choices, so they routinely cross
# that line. Truncate well below 1 MB to leave headroom for the event envelope
# (distinct_id, event name, other properties) and JSON re-escaping on the wire.
_MAX_CAPTURE_SIZE = 800 * 1024
_MIN_FIELD_SIZE_TO_TRUNCATE = 10 * 1024
_TRUNCATION_MARKER = "[truncated: content too large for capture]"
_TRUNCATABLE_FIELDS = ("$ai_output_choices", "$ai_input")


def _is_product_billable(product: str) -> bool:
    """Look up the product's billable flag in the central registry. False for
    unknown products so we never accidentally bill calls we can't attribute.
    """
    config = get_product_config(product)
    return bool(config and config.billable)


def _apply_owned_event_properties(properties: dict[str, Any], product: str, team_id: int | None) -> None:
    """Enforce gateway-owned event properties, run after caller `x-posthog-property-*` headers are merged.

    `ai_product`, `$ai_billable`, and `$ai_effort` are gateway-derived (effort via
    `ProviderConfig.extract_effort`) and must not be spoofable via headers, so we re-assert them
    here and drop `$ai_effort` when the gateway found none. `team_id`, in contrast, is a
    deliberate caller override (e.g. a shared-key caller attributing to a customer team); we only
    fall back to the key owner's team when no override was supplied.
    """
    properties["ai_product"] = product
    properties["$ai_billable"] = _is_product_billable(product)
    effort = get_effort()
    if effort is not None:
        properties["$ai_effort"] = effort
    else:
        properties.pop("$ai_effort", None)
    if team_id is not None:
        properties.setdefault("team_id", team_id)
    # A header-supplied team_id arrives as a string ("42"); store it as an int so the captured
    # property matches the rest of the platform (the usage reporter reads it via JSONExtractInt)
    # rather than relying on ClickHouse string coercion.
    raw_team_id = properties.get("team_id")
    if raw_team_id is not None:
        try:
            properties["team_id"] = int(raw_team_id)
        except (TypeError, ValueError):
            if team_id is not None:
                properties["team_id"] = team_id
            else:
                properties.pop("team_id", None)


# Stable namespace for hashing non-UUID trace identifiers (e.g. Claude Code's
# JSON-encoded session blobs sent via Anthropic's metadata.user_id) into a
# deterministic UUID. Generated once and frozen so the same input always maps
# to the same trace UUID across runs and processes.
_TRACE_ID_NAMESPACE = UUID("8d4f6b7e-6a3e-4f3a-9f3b-3b6f4d2e8a1a")


def _normalize_trace_id(raw: Any) -> str:
    """Normalize an incoming trace identifier into a UUID string.

    AI observability renders trace links as `/ai-observability/traces/<id>`, so
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
    """Custom PostHog callback for AI observability."""

    callback_name = "posthog"

    def __init__(
        self,
        api_key: str,
        host: str,
        region_url: str = "https://us.posthog.com",
        secondary_api_key: str | None = None,
        secondary_host: str | None = None,
    ):
        super().__init__()
        self._api_key = api_key
        self._host = host
        # Customer-origin region URL stamped on every captured event via the
        # `instance` group. The PHAI usage report filters on $group_<N> where
        # N is the destination project's `instance` group_type_index, so the
        # value must be the customer's region URL — not the capture host's.
        # That keeps EU events tagged as EU even when the secondary capture
        # mirrors them to the US instance for engineer visibility.
        self._region_url = region_url
        # Optional second capture target. When set, each captured event is
        # mirrored to this host with the same payload, mirroring the
        # `ee/hogai/core/runner.py:201-206` pattern that lets EU traffic also
        # surface on the US dashboard. Set on the EU gateway deployment only.
        self._secondary_api_key = secondary_api_key
        self._secondary_host = secondary_host

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
        if auth_user is None:
            distinct_id = end_user_id or str(uuid4())
        else:
            distinct_id = resolve_distinct_id(auth_user, end_user_id)
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
        usage_object = (standard_logging_object.get("metadata") or {}).get("usage_object") or {}

        ai_provider, ai_model = normalize_metric_labels(
            standard_logging_object.get("model", ""),
            standard_logging_object.get("custom_llm_provider", ""),
        )

        properties: dict[str, Any] = {
            "$ai_model": ai_model,
            "$ai_provider": ai_provider,
            "$ai_input": _replace_binary_content(standard_logging_object.get("messages")),
            "$ai_input_tokens": standard_logging_object.get("prompt_tokens", 0),
            "$ai_output_tokens": standard_logging_object.get("completion_tokens", 0),
            "$ai_latency": standard_logging_object.get("response_time", 0.0),
            "$ai_stream": is_streaming,
            "$ai_trace_id": trace_id,
            "$ai_span_id": str(uuid4()),
            # Stamped explicitly to bypass the SDK's group_type_index lookup.
            # The AI usage report hardcodes `$group_1` (posthog/tasks/usage_report.py)
            # so the gateway must guarantee that slot regardless of how the
            # destination team's group types are registered.
            "$group_1": self._region_url,
        }

        # Cache and reasoning token breakdowns are reported by LiteLLM in the
        # response usage object for providers that support them (Anthropic for
        # cache, OpenAI o-series for reasoning). Emit the fields only when
        # present so providers that don't report them don't pollute events with
        # zeros, matching the schema in posthog/models/ai_events/sql.py and the
        # parity established by posthoganalytics' langchain CallbackHandler.
        cache_read_input_tokens = usage_object.get("cache_read_input_tokens")
        if cache_read_input_tokens is not None:
            properties["$ai_cache_read_input_tokens"] = cache_read_input_tokens
        cache_creation_input_tokens = usage_object.get("cache_creation_input_tokens")
        if cache_creation_input_tokens is not None:
            properties["$ai_cache_creation_input_tokens"] = cache_creation_input_tokens
        completion_tokens_details = usage_object.get("completion_tokens_details") or {}
        reasoning_tokens = completion_tokens_details.get("reasoning_tokens")
        if reasoning_tokens is not None:
            properties["$ai_reasoning_tokens"] = reasoning_tokens

        posthog_properties = get_posthog_properties() or {}
        if isinstance(posthog_properties, dict):
            for key, value in posthog_properties.items():
                properties[key] = value

        posthog_flags = get_posthog_flags() or {}
        if isinstance(posthog_flags, dict):
            for flag_key, variant in posthog_flags.items():
                properties[f"$feature/{flag_key}"] = variant

        _apply_owned_event_properties(properties, product, team_id)

        response_cost = standard_logging_object.get("response_cost")
        if response_cost is not None:
            properties["$ai_total_cost_usd"] = response_cost

        # Forward LiteLLM's cost_breakdown so ingestion passes the per-side
        # numbers through instead of rederiving them and mispricing cache.
        cost_breakdown = standard_logging_object.get("cost_breakdown") or {}
        for breakdown_key, property_key in (
            ("input_cost", "$ai_input_cost_usd"),
            ("output_cost", "$ai_output_cost_usd"),
            ("cache_read_cost", "$ai_cache_read_cost_usd"),
            ("cache_creation_cost", "$ai_cache_creation_cost_usd"),
        ):
            cost_value = cost_breakdown.get(breakdown_key)
            if cost_value is not None:
                properties[property_key] = cost_value

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
            "groups": self._build_groups(team_id),
        }

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
        if auth_user is None:
            distinct_id = end_user_id or str(uuid4())
        else:
            distinct_id = resolve_distinct_id(auth_user, end_user_id)
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
            "$group_1": self._region_url,
        }

        posthog_properties = get_posthog_properties() or {}
        if isinstance(posthog_properties, dict):
            for key, value in posthog_properties.items():
                properties[key] = value

        posthog_flags = get_posthog_flags() or {}
        if isinstance(posthog_flags, dict):
            for flag_key, variant in posthog_flags.items():
                properties[f"$feature/{flag_key}"] = variant

        _apply_owned_event_properties(properties, product, team_id)

        capture_kwargs: dict[str, Any] = {
            "distinct_id": distinct_id,
            "event": "$ai_generation",
            "properties": properties,
            "groups": self._build_groups(team_id),
        }

        logger.debug(
            "PostHog capturing error event",
            distinct_id=distinct_id,
            posthog_event="$ai_generation",
            properties=properties,
            groups=capture_kwargs.get("groups"),
        )
        self._capture_fire_and_forget(**capture_kwargs)

    def _build_groups(self, team_id: int | None) -> dict[str, Any]:
        """Build the `groups` dict for a captured event.

        Billing region attribution comes from the hardcoded `$group_1`
        property; the `instance` group here keeps LLM Analytics group
        breakdowns working naturally. `project` is included when an
        authenticated team is known.
        """
        groups: dict[str, Any] = {"instance": self._region_url}
        if team_id:
            groups["project"] = team_id
        return groups

    def _capture_fire_and_forget(self, **capture_kwargs: Any) -> None:
        """
        Initializes a separate client for the capture operation to avoid payload bloat.
        Fires in background thread to avoid blocking the main thread.
        """
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, partial(self._capture_sync, **capture_kwargs))

    def _capture_sync(self, **capture_kwargs: Any) -> None:
        # No outer try/except: the destinations feed regional billing
        # aggregations, so we want them to succeed or fail together. If the
        # primary raises, the secondary intentionally does not run so the two
        # PostHog instances stay in sync rather than diverging on billing state.
        self._capture_to_destination(self._api_key, self._host, **capture_kwargs)
        if self._secondary_api_key and self._secondary_host:
            self._capture_to_destination(
                self._secondary_api_key,
                self._secondary_host,
                **capture_kwargs,
            )

    def _capture_to_destination(self, api_key: str, host: str, **capture_kwargs: Any) -> None:
        """Fire a single capture against one PostHog instance.

        Each call uses a fresh client so a slow shutdown on one destination
        doesn't pin a pooled client and to avoid cross-destination state
        bleed in the SDK. Mutable `properties` / `groups` dicts are
        shallow-copied per destination so an in-place mutation by the SDK
        (adding `$lib`, `$lib_version`, distinct-id resolution, etc.) on
        one capture cannot bleed into the other.
        """
        capture_kwargs = dict(capture_kwargs)
        if "properties" in capture_kwargs:
            capture_kwargs["properties"] = dict(capture_kwargs["properties"])
        if "groups" in capture_kwargs:
            capture_kwargs["groups"] = dict(capture_kwargs["groups"])
        client = Posthog(
            api_key,
            host=host,
            sync_mode=True,
            enable_local_evaluation=False,
        )
        try:
            client.capture(**capture_kwargs)
        except Exception as e:
            client.capture_exception(e, **capture_kwargs)
            logger.exception("posthog_capture_failed", host=host, error=str(e))
        finally:
            client.shutdown()

    def _extract_metadata(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        litellm_params = kwargs.get("litellm_params", {}) or {}
        return litellm_params.get("metadata", {}) or {}
