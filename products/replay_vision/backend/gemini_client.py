"""Replay Vision's Gemini client: the AI gateway when enabled for the team, else Google directly with our key."""

from collections.abc import Mapping
from typing import Any

from django.conf import settings

from google.genai import (
    Client as RawGenAIClient,
    errors,
    types,
)
from posthoganalytics.ai.gemini import genai

from posthog.llm.gateway_client import (
    ai_gateway_headers,
    build_gemini_client,
    resolve_ai_gateway_config,
    team_distinct_id,
)
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.replay_vision.backend.temporal.gemini import gemini_api_key

AI_PRODUCT = "replay_vision"
GATEWAY_FLAG = "replay-vision-ai-gateway"


async def replay_gemini_client(team_id: int, *, properties: Mapping[str, Any] | None = None) -> "ReplayGemini":
    base_properties = dict(properties or {})
    if await _gateway_enabled(team_id) and (
        client := build_gemini_client(
            ai_product=AI_PRODUCT, properties=_gateway_labels(base_properties), privacy_mode=True
        )
    ):
        return ReplayGemini(client, _AsyncGatewayModels(client.aio.models, base_properties))
    # Privacy mode keeps recording content out of the internal project, where it can't be deleted with the recording.
    direct = genai.AsyncClient(api_key=gemini_api_key(), posthog_privacy_mode=True, posthog_properties=base_properties)
    return ReplayGemini(RawGenAIClient(api_key=gemini_api_key()), direct.models)


async def _gateway_enabled(team_id: int) -> bool:
    # Cleanup and the sweep delete files with the direct key, so gateway mode also needs Replay Vision's own key.
    if not settings.REPLAY_VISION_GEMINI_API_KEY or resolve_ai_gateway_config() is None:
        return False
    organization_id = str(await Team.objects.values_list("organization_id", flat=True).aget(id=team_id))
    # Local evaluation only, so a flag outage leaves a scan's many calls direct and fast; conditions must use the
    # org or project id.
    return feature_enabled_or_false(
        GATEWAY_FLAG,
        team_distinct_id(team_id),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


class ReplayGemini:
    """One client for both routes: `models` takes the analytics wrapper's `posthog_*` kwargs; `raw` serves files and
    caches."""

    def __init__(self, raw: RawGenAIClient, models: Any) -> None:
        self.raw = raw
        self.models = models

    async def aclose(self) -> None:
        """Close both SDK transports; the sync one carries `files`, the async one `aio`."""
        self.raw.close()
        await self.raw.aio.aclose()


class _AsyncGatewayModels:
    """Takes the analytics wrapper's `posthog_*` kwargs as gateway headers; groups have none, so they drop. Streams
    every call: the gateway cuts a buffered call at 290s and long scans run past that."""

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
