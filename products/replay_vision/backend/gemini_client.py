"""Replay Vision's Gemini client: the AI gateway when it is enabled for the team, else Google directly with our own key."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from google.genai import errors, types

from posthog.llm.gateway_client import (
    ai_gateway_headers,
    build_gemini_client,
    resolve_ai_gateway_config,
    team_distinct_id,
)
from posthog.ph_client import feature_enabled_or_false

AI_PRODUCT = "replay_vision"
# Per-team switch for the gateway route, on top of the AI_GATEWAY_URL/AI_GATEWAY_API_KEY pair.
GATEWAY_FLAG = "replay-vision-ai-gateway"

_DirectClientT = TypeVar("_DirectClientT")


def replay_gateway_enabled(team_id: int) -> bool:
    """Whether the team's Gemini calls go through the gateway: the env pair is set and the flag is on."""
    if resolve_ai_gateway_config() is None:
        return False
    # Local evaluation only: a scan makes many calls, and a flag outage must leave calls direct, not slow them.
    return feature_enabled_or_false(
        GATEWAY_FLAG,
        team_distinct_id(team_id),
        groups={"project": str(team_id)},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


class _GatewayModelsBase:
    """A plain SDK `models` surface that accepts the analytics wrapper's per-call `posthog_*` kwargs.

    The gateway captures the generation, so those kwargs become request headers. Groups have no gateway header.
    Calls stream, because the gateway cuts a buffered call off at 290s and long scans run past that. The chunks are
    assembled into the one response a buffered call returns.
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
        headers = ai_gateway_headers(
            ai_product=AI_PRODUCT,
            trace_id=posthog_trace_id,
            properties=_gateway_labels({**self._base_properties, **(posthog_properties or {})}),
            distinct_id=posthog_distinct_id,
        )
        return _with_headers(config, headers)


class _GatewayModels(_GatewayModelsBase):
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
    ) -> types.GenerateContentResponse:
        stream = self._models.generate_content_stream(
            model=model,
            contents=contents,
            config=self._config(config, posthog_distinct_id, posthog_trace_id, posthog_properties),
        )
        return assemble_stream(list(stream))


class _AsyncGatewayModels(_GatewayModelsBase):
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
        return assemble_stream([chunk async for chunk in stream])


class _GatewayAio:
    def __init__(self, models: _AsyncGatewayModels) -> None:
        self.models = models


class GatewayGeminiClient:
    """The gateway client with the analytics wrapper's call shape, so call sites stay the same in both modes."""

    def __init__(self, client: Any, base_properties: Mapping[str, Any]) -> None:
        self.models = _GatewayModels(client.models, base_properties)
        self.aio = _GatewayAio(_AsyncGatewayModels(client.aio.models, base_properties))


def assemble_stream(chunks: list[types.GenerateContentResponse]) -> types.GenerateContentResponse:
    """Fold streamed chunks into the response a buffered call returns.

    Parts keep their order, so thought signatures and function calls reach the next turn unchanged. The finish
    reason and usage come from the last chunk that carries them.

    Raises a 503 `ServerError` when the stream ends with no finish reason and no prompt block: the SDK drops the
    gateway's in-band error frame, so a cut stream would otherwise pass as a short answer.
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
            "content": types.Content(role=role, parts=_merge_text_parts(parts)),
            "finish_reason": finish_reason,
        }
    )
    return final.model_copy(
        update={"candidates": [candidate], "usage_metadata": usage, "prompt_feedback": prompt_feedback}
    )


def _merge_text_parts(parts: Iterable[types.Part]) -> list[types.Part]:
    # Joins the text deltas of one run so the next turn carries one part per run, not one per chunk. A part with a
    # thought signature is never merged, because the signature belongs to that exact part.
    merged: list[types.Part] = []
    for part in parts:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and _plain_text(previous)
            and _plain_text(part)
            and bool(previous.thought) == bool(part.thought)
        ):
            merged[-1] = previous.model_copy(update={"text": (previous.text or "") + (part.text or "")})
        else:
            merged.append(part)
    return merged


def _plain_text(part: types.Part) -> bool:
    # Any other field set (a thought signature, a function call, inline data) makes the part more than text.
    return part.text is not None and part.model_fields_set <= {"text", "thought"}


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
    team_id: int,
    properties: Mapping[str, Any] | None = None,
    distinct_id: str | None = None,
    timeout_ms: int | None = None,
) -> _DirectClientT | GatewayGeminiClient:
    """The gateway client when `replay_gateway_enabled(team_id)`, else `direct()`.

    `direct` runs only in direct mode. Per-call `posthog_*` kwargs override `properties` and `distinct_id` in both
    modes. Every Replay Vision call runs in privacy mode.
    """
    if not replay_gateway_enabled(team_id):
        return direct()
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
