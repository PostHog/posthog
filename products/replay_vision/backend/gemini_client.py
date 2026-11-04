"""Replay Vision's Gemini client. Every call goes through the AI gateway; there is no direct route to Google."""

from collections.abc import Mapping
from typing import Any

from google.genai import (
    Client as RawGenAIClient,
    errors,
    types,
)

from posthog.llm.gateway_client import GatewayNotConfiguredError, ai_gateway_headers, build_gemini_client

AI_PRODUCT = "replay_vision"


def replay_gemini_client(*, properties: Mapping[str, Any] | None = None) -> "ReplayGemini":
    base_properties = dict(properties or {})
    client = _gateway_client(properties=_gateway_labels(base_properties), privacy_mode=True)
    return ReplayGemini(client, _AsyncGatewayModels(client.aio.models, base_properties))


def gemini_text_models(*, timeout_ms: int) -> "_SyncGatewayModels":
    """Sync `models` for text-only calls; takes the analytics wrapper's `posthog_*` kwargs as gateway headers."""
    return _SyncGatewayModels(_gateway_client(privacy_mode=True, timeout_ms=timeout_ms))


def gemini_files_client() -> RawGenAIClient:
    """Deletes uploaded files, which carry no content, so it needs no privacy mode or labels."""
    return _gateway_client()


def _gateway_client(
    *, properties: Mapping[str, str] | None = None, privacy_mode: bool = False, timeout_ms: int | None = None
) -> RawGenAIClient:
    # Privacy mode keeps customer content out of the internal project, where it could not be deleted on request.
    client = build_gemini_client(
        ai_product=AI_PRODUCT, properties=properties, privacy_mode=privacy_mode, timeout_ms=timeout_ms
    )
    if client is None:
        raise GatewayNotConfiguredError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")
    return client


class ReplayGemini:
    """`models` takes the analytics wrapper's `posthog_*` kwargs; `raw` serves files and caches."""

    def __init__(self, raw: RawGenAIClient, models: "_AsyncGatewayModels") -> None:
        self.raw = raw
        self.models = models

    async def aclose(self) -> None:
        """Close both SDK transports; the sync one carries `files`, the async one `aio`."""
        self.raw.close()
        await self.raw.aio.aclose()


def _gateway_config(
    config: types.GenerateContentConfig | None,
    posthog_distinct_id: str | None,
    posthog_trace_id: str | None,
    posthog_properties: Mapping[str, Any] | None,
    base_properties: Mapping[str, Any] | None = None,
) -> types.GenerateContentConfig | None:
    """Turn the analytics wrapper's `posthog_*` kwargs into gateway headers."""
    # The client's default headers carry the product, privacy mode and base labels; a call adds its own.
    labels = (
        _gateway_labels({**(base_properties or {}), **posthog_properties, "ai_product": AI_PRODUCT})
        if posthog_properties
        else None
    )
    headers = ai_gateway_headers(trace_id=posthog_trace_id, properties=labels, distinct_id=posthog_distinct_id) or {}
    # The gateway sets `$ai_span_name` only from this header; it strips `$` keys from the properties.
    if posthog_properties and (span_name := posthog_properties.get("$ai_span_name")):
        headers["X-PostHog-Span-Name"] = str(span_name)
    return _with_headers(config, headers)


class _SyncGatewayModels:
    """Buffered, unlike the async path: text calls finish far inside the gateway's 290s cut."""

    def __init__(self, client: RawGenAIClient) -> None:
        # Holds the client, not just `models`: a collected client closes the transport `models` sends on.
        self._client = client

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: types.GenerateContentConfig | None = None,
        posthog_distinct_id: str | None = None,
        posthog_trace_id: str | None = None,
        posthog_properties: Mapping[str, Any] | None = None,
    ) -> types.GenerateContentResponse:
        return self._client.models.generate_content(
            model=model,
            contents=contents,
            config=_gateway_config(config, posthog_distinct_id, posthog_trace_id, posthog_properties),
        )


class _AsyncGatewayModels:
    """Streams every call: the gateway cuts a buffered call at 290s and long scans run past that."""

    def __init__(self, models: Any, base_properties: Mapping[str, Any]) -> None:
        self._models = models
        self._base_properties = base_properties

    async def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: types.GenerateContentConfig | None = None,
        posthog_distinct_id: str | None = None,
        posthog_trace_id: str | None = None,
        posthog_properties: Mapping[str, Any] | None = None,
    ) -> types.GenerateContentResponse:
        stream = await self._models.generate_content_stream(
            model=model,
            contents=contents,
            config=_gateway_config(
                config, posthog_distinct_id, posthog_trace_id, posthog_properties, self._base_properties
            ),
        )
        chunks = [chunk async for chunk in stream]
        return assemble_stream(chunks)


def assemble_stream(chunks: list[types.GenerateContentResponse]) -> types.GenerateContentResponse:
    """Fold streamed chunks into the response a buffered call returns, parts in arrival order."""
    parts: list[types.Part] = []
    last_candidate: types.Candidate | None = None
    finish_reason: types.FinishReason | None = None
    for chunk in chunks:
        for candidate in chunk.candidates or []:
            if candidate.index not in (None, 0):
                continue
            last_candidate = candidate
            if candidate.content and candidate.content.parts:
                parts.extend(candidate.content.parts)
            if candidate.finish_reason is not None:
                finish_reason = candidate.finish_reason
    usage = next((chunk.usage_metadata for chunk in reversed(chunks) if chunk.usage_metadata), None)
    prompt_feedback = next((chunk.prompt_feedback for chunk in chunks if chunk.prompt_feedback), None)
    if not chunks:
        raise errors.ServerError(503, {"error": {"code": 503, "message": "Gemini stream ended with no chunks"}})
    final = chunks[-1]
    if last_candidate is None:
        # A blocked prompt streams no candidate; the feedback says why.
        return final.model_copy(update={"usage_metadata": usage, "prompt_feedback": prompt_feedback})
    role = last_candidate.content.role if last_candidate.content and last_candidate.content.role else "model"
    candidate = last_candidate.model_copy(
        update={
            "content": types.Content(role=role, parts=parts),
            "finish_reason": finish_reason,
        }
    )
    return final.model_copy(
        update={"candidates": [candidate], "usage_metadata": usage, "prompt_feedback": prompt_feedback}
    )


def _gateway_labels(properties: Mapping[str, Any]) -> dict[str, str]:
    # The gateway strips `$`-prefixed keys as reserved.
    return {key: str(value) for key, value in properties.items() if not key.startswith("$") and value is not None}


def _with_headers(
    config: types.GenerateContentConfig | None, headers: dict[str, str] | None
) -> types.GenerateContentConfig | None:
    if not headers:
        return config
    config = config or types.GenerateContentConfig()
    options = config.http_options or types.HttpOptions()
    merged = options.model_copy(update={"headers": {**(options.headers or {}), **headers}})
    return config.model_copy(update={"http_options": merged})
