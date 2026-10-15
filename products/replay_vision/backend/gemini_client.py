"""Replay Vision's Gemini client: the AI gateway when enabled for the team, else Google directly with our key."""

from collections.abc import Mapping
from typing import Any

from django.conf import settings

import httpx
import structlog
from google.genai import errors, types

from posthog.llm.gateway_client import (
    AIGatewayConfig,
    ai_gateway_headers,
    anthropic_gateway_base_url,
    build_gemini_client,
    resolve_ai_gateway_config,
    team_distinct_id,
)
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

AI_PRODUCT = "replay_vision"
GATEWAY_FLAG = "replay-vision-ai-gateway"

logger = structlog.get_logger(__name__)


async def replay_gateway_client(
    team_id: int, *, properties: Mapping[str, Any] | None = None
) -> "GatewayGeminiClient | None":
    """The gateway client when gateway mode is on for the team's org, else None so the caller goes direct.

    Cleanup and the sweep delete files with the direct key, so gateway mode also needs Replay Vision's own direct key.
    """
    if not settings.REPLAY_VISION_GEMINI_API_KEY:
        return None
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        return None
    organization_id = str(await Team.objects.values_list("organization_id", flat=True).aget(id=team_id))
    # Local evaluation only, so a flag outage leaves a scan's many calls direct and fast; conditions must use the
    # org or project id.
    enabled = feature_enabled_or_false(
        GATEWAY_FLAG,
        team_distinct_id(team_id),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    if not enabled:
        return None
    base_properties = dict(properties or {})
    client = build_gemini_client(ai_product=AI_PRODUCT, properties=_gateway_labels(base_properties), privacy_mode=True)
    if client is None:
        return None
    return GatewayGeminiClient(client, base_properties, gateway)


class _AsyncGatewayModels:
    """A plain SDK `models` surface taking the analytics wrapper's per-call `posthog_*` kwargs as request headers,
    since the gateway captures the generation. Groups have no gateway header, so they are dropped. Streams each
    call, because the gateway cuts a buffered call off at 290s and long scans run past that.
    """

    def __init__(self, models: Any, base_properties: Mapping[str, Any]) -> None:
        self._models = models
        self._base_properties = base_properties

    def _config(
        self,
        config: types.GenerateContentConfig | None,
        posthog_distinct_id: str | None,
        posthog_trace_id: str | None,
        posthog_properties: Mapping[str, Any] | None,
    ) -> types.GenerateContentConfig | None:
        # The client's default headers carry the product, privacy mode and base labels; a call adds its own.
        labels = (
            _gateway_labels({**self._base_properties, **posthog_properties, "ai_product": AI_PRODUCT})
            if posthog_properties
            else None
        )
        headers = (
            ai_gateway_headers(trace_id=posthog_trace_id, properties=labels, distinct_id=posthog_distinct_id) or {}
        )
        # The gateway sets `$ai_span_name` only from this header; it strips `$` keys from the properties.
        if posthog_properties and (span_name := posthog_properties.get("$ai_span_name")):
            headers["X-PostHog-Span-Name"] = str(span_name)
        return _with_headers(config, headers)

    async def generate_content(
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
    ) -> types.GenerateContentResponse:
        stream = await self._models.generate_content_stream(
            model=model,
            contents=contents,
            config=self._config(config, posthog_distinct_id, posthog_trace_id, posthog_properties),
        )
        chunks = [chunk async for chunk in stream]
        return assemble_stream(chunks)


class _GatewayAio:
    def __init__(self, aio: Any, base_properties: Mapping[str, Any]) -> None:
        self.models = _AsyncGatewayModels(aio.models, base_properties)
        self.caches = aio.caches


_UPLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class GatewayGeminiClient:
    """The gateway client with the analytics wrapper's call shape, so call sites stay the same in both modes."""

    def __init__(self, client: Any, base_properties: Mapping[str, Any], gateway: AIGatewayConfig) -> None:
        self._client = client
        self.aio = _GatewayAio(client.aio, base_properties)
        self.files = client.files
        self._gateway = gateway

    def upload_file(self, data: bytes, *, mime_type: str, display_name: str) -> types.File:
        """Store `data` in Replay Vision's Files API; the gateway runs Google's resumable upload."""
        with httpx.Client(trust_env=False, timeout=_UPLOAD_TIMEOUT) as http:
            response = http.post(
                f"{anthropic_gateway_base_url(self._gateway.url)}/v1beta/files:upload",
                content=data,
                headers={
                    **(ai_gateway_headers(ai_product=AI_PRODUCT) or {}),
                    "x-goog-api-key": self._gateway.api_key,
                    "Content-Type": mime_type,
                    "X-Goog-Upload-Display-Name": display_name,
                },
            )
            errors.APIError.raise_for_response(response)
        return types.File.model_validate(response.json()["file"])

    async def aclose(self) -> None:
        """Close both SDK transports; the sync one carries `files`, the async one `aio`."""
        self._client.close()
        await self._client.aio.aclose()


def assemble_stream(chunks: list[types.GenerateContentResponse]) -> types.GenerateContentResponse:
    """Fold streamed chunks into the response a buffered call returns, parts in arrival order. Raises a 503
    `ServerError` when the stream ends with no finish reason and no prompt block: the SDK drops the gateway's in-band
    error frame, so a cut stream would otherwise pass as a short answer.
    """
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
    if finish_reason is None and not (prompt_feedback and prompt_feedback.block_reason):
        raise errors.ServerError(
            503,
            {
                "error": {
                    "code": 503,
                    "message": f"Gemini stream ended without a finish reason after {len(chunks)} chunks",
                    "status": "UNAVAILABLE",
                }
            },
        )
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
