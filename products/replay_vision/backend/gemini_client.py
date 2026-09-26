"""Replay Vision's Gemini client: the AI gateway when it is configured, else Google directly with our own key."""

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from google.genai import types

from posthog.llm.gateway_client import ai_gateway_headers, build_gemini_client

AI_PRODUCT = "replay_vision"

_DirectClientT = TypeVar("_DirectClientT")


class _GatewayModels:
    """A plain SDK `models` surface that accepts the analytics wrapper's per-call `posthog_*` kwargs.

    The gateway captures the generation, so those kwargs become request headers. Groups have no gateway header.
    """

    def __init__(self, models: Any, base_properties: Mapping[str, Any]) -> None:
        self._models = models
        self._base_properties = base_properties

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: types.GenerateContentConfig | None = None,
        posthog_distinct_id: str | None = None,
        posthog_trace_id: str | None = None,
        posthog_properties: Mapping[str, Any] | None = None,
        posthog_privacy_mode: bool | None = None,
        posthog_groups: Mapping[str, Any] | None = None,
    ) -> Any:
        # Returns the SDK's result as is, so the same code serves `models` (sync) and `aio.models` (a coroutine).
        headers = ai_gateway_headers(
            ai_product=AI_PRODUCT,
            trace_id=posthog_trace_id,
            properties=_gateway_labels({**self._base_properties, **(posthog_properties or {})}),
            distinct_id=posthog_distinct_id,
        )
        return self._models.generate_content(model=model, contents=contents, config=_with_headers(config, headers))


class _GatewayAio:
    def __init__(self, models: _GatewayModels) -> None:
        self.models = models


class GatewayGeminiClient:
    """The gateway client with the analytics wrapper's call shape, so call sites stay the same in both modes."""

    def __init__(self, client: Any, base_properties: Mapping[str, Any]) -> None:
        self.models = _GatewayModels(client.models, base_properties)
        self.aio = _GatewayAio(_GatewayModels(client.aio.models, base_properties))


def _gateway_labels(properties: Mapping[str, Any]) -> dict[str, str]:
    # The gateway strips `$`-prefixed keys as reserved, so the scanner's span name travels unprefixed.
    labels = {key: str(value) for key, value in properties.items() if not key.startswith("$") and value is not None}
    span_name = properties.get("$ai_span_name")
    if span_name:
        labels["span_name"] = str(span_name)
    return labels


def _with_headers(
    config: types.GenerateContentConfig | None, headers: dict[str, str] | None
) -> types.GenerateContentConfig | None:
    if not headers:
        return config
    config = config or types.GenerateContentConfig()
    existing = config.http_options.headers if config.http_options and config.http_options.headers else {}
    return config.model_copy(update={"http_options": types.HttpOptions(headers={**existing, **headers})})


def replay_gemini_client(
    direct: Callable[[], _DirectClientT],
    *,
    properties: Mapping[str, Any] | None = None,
    distinct_id: str | None = None,
    timeout_ms: int | None = None,
) -> _DirectClientT | GatewayGeminiClient:
    """The gateway client when `AI_GATEWAY_URL`/`AI_GATEWAY_API_KEY` are set, else `direct()`.

    `direct` runs only in direct mode. Per-call `posthog_*` kwargs override `properties` and `distinct_id` in both
    modes. Every Replay Vision call runs in privacy mode.
    """
    base_properties = dict(properties or {})
    client = build_gemini_client(
        ai_product=AI_PRODUCT,
        properties=_gateway_labels(base_properties),
        distinct_id=distinct_id,
        privacy_mode=True,
        timeout_ms=timeout_ms,
    )
    if client is None:
        return direct()
    return GatewayGeminiClient(client, base_properties)
