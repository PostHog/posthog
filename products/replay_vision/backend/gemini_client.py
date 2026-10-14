"""Replay Vision's Gemini client: the AI gateway when enabled for the team, else Google directly with our key."""

import time
import inspect
import functools
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, TypeVar

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
from posthog.ph_client import feature_enabled_or_false

AI_PRODUCT = "replay_vision"
GATEWAY_FLAG = "replay-vision-ai-gateway"

logger = structlog.get_logger(__name__)

_DirectClientT = TypeVar("_DirectClientT")


def resolve_replay_gateway_config() -> AIGatewayConfig | None:
    """The gateway with Replay Vision's own key, whose team the gateway binds to Replay Vision's Google project.

    None while the key is unset, so Replay Vision stays direct without the shared key's misconfiguration warning.
    Also None without REPLAY_VISION_GEMINI_API_KEY: direct cleanup would then use the shared project's key and
    could not see the files the gateway stores in Replay Vision's project.
    """
    if not settings.REPLAY_VISION_AI_GATEWAY_API_KEY:
        return None
    if not settings.REPLAY_VISION_GEMINI_API_KEY:
        _warn_gateway_without_dedicated_key()
        return None
    return resolve_ai_gateway_config(api_key=settings.REPLAY_VISION_AI_GATEWAY_API_KEY)


@functools.cache
def _warn_gateway_without_dedicated_key() -> None:
    logger.warning(
        "replay_vision.gateway_disabled",
        reason="REPLAY_VISION_AI_GATEWAY_API_KEY is set but REPLAY_VISION_GEMINI_API_KEY is not",
    )


def replay_gateway_enabled(team_id: int) -> bool:
    """Whether the team's Gemini calls go through the gateway: Replay Vision's key is set and the flag is on."""
    if resolve_replay_gateway_config() is None:
        return False
    # Local evaluation only: a scan makes many calls, and a flag outage must leave them direct and fast.
    return feature_enabled_or_false(
        GATEWAY_FLAG,
        team_distinct_id(team_id),
        groups={"project": str(team_id)},
        group_properties={"project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


# The gateway's key and policy refusals are ours to fix and clear once we do, so they retry.
_GATEWAY_REFUSAL_CODES = frozenset({401, 403})
_GATEWAY_SPEND_LIMIT_CODE = 402
# The gateway marks its own errors with this ErrorInfo domain; Google's errors pass through without it.
_GATEWAY_ERROR_DOMAIN = "posthog.com"


def _gateway_wrote(error: errors.APIError) -> bool:
    body = error.details.get("error") if isinstance(error.details, dict) else None
    details = body.get("details") if isinstance(body, dict) else None
    return isinstance(details, list) and any(
        isinstance(detail, dict) and detail.get("domain") == _GATEWAY_ERROR_DOMAIN for detail in details
    )


class GatewaySpendLimitError(Exception):
    """The AI gateway refused the call because Replay Vision's spend limit is reached. Retrying won't clear it."""


@contextmanager
def _retry_gateway_refusals() -> Iterator[None]:
    try:
        yield
    except errors.ClientError as e:
        if e.code == _GATEWAY_SPEND_LIMIT_CODE:
            raise GatewaySpendLimitError("AI gateway returned HTTP 402") from e
        # Google's own 401/403 (a file gone, another project) keeps the class it has in direct mode.
        if e.code not in _GATEWAY_REFUSAL_CODES or not _gateway_wrote(e):
            raise
        raise errors.ServerError(
            503,
            {"error": {"code": 503, "message": f"AI gateway returned HTTP {e.code}", "status": "UNAVAILABLE"}},
        ) from e


class _GatewayModelsBase:
    """A plain SDK `models` surface that accepts the analytics wrapper's per-call `posthog_*` kwargs.

    The gateway captures the generation, so those kwargs become request headers. Groups have no gateway header.
    """

    def __init__(self, client: Any, base_properties: Mapping[str, Any]) -> None:
        # Holds the SDK client itself: collecting it closes the transport its `models` send through.
        self._client = client
        self._models = client.models
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
        with _retry_gateway_refusals():
            return self._models.generate_content(
                model=model,
                contents=contents,
                config=self._config(config, posthog_distinct_id, posthog_trace_id, posthog_properties),
            )


class _AsyncGatewayModels(_GatewayModelsBase):
    """Streams each call, because the gateway cuts a buffered call off at 290s and long scans run past that."""

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
        with _retry_gateway_refusals():
            stream = await self._models.generate_content_stream(
                model=model,
                contents=contents,
                config=self._config(config, posthog_distinct_id, posthog_trace_id, posthog_properties),
            )
            chunks = [chunk async for chunk in stream]
        return assemble_stream(chunks)


class _RefusalRemap:
    """An SDK surface whose calls raise the gateway's refusals the way generate calls do."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if inspect.iscoroutinefunction(attr):

            async def call_async(*args: Any, **kwargs: Any) -> Any:
                with _retry_gateway_refusals():
                    return await attr(*args, **kwargs)

            return call_async
        if callable(attr):

            def call(*args: Any, **kwargs: Any) -> Any:
                with _retry_gateway_refusals():
                    return attr(*args, **kwargs)

            return call
        return attr


class _GatewayAio:
    def __init__(self, client: Any, base_properties: Mapping[str, Any]) -> None:
        self._client = client
        self.models = _AsyncGatewayModels(client, base_properties)
        self.caches = _RefusalRemap(client.caches)
        self.files = _RefusalRemap(client.files)

    async def aclose(self) -> None:
        await self._client.aclose()


# The upload activity has 10 minutes and keeps 300s for Google's processing wait. A thread can't be
# cancelled, so the upload ends on its own within 280s: 10s connect, 150s send plus one 60s chunk, 60s reply.
_UPLOAD_SEND_DEADLINE_S = 150.0
_UPLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_UPLOAD_CHUNK_BYTES = 1 << 20


class GatewayGeminiClient:
    """The gateway client with the analytics wrapper's call shape, so call sites stay the same in both modes.

    Files and caches live in Replay Vision's own Google project: the gateway binds Replay Vision's key to it.
    """

    def __init__(self, client: Any, base_properties: Mapping[str, Any], gateway: AIGatewayConfig | None = None) -> None:
        self._client = client
        self.models = _GatewayModels(client, base_properties)
        self.aio = _GatewayAio(client.aio, base_properties)
        self.files = _RefusalRemap(client.files)
        self._gateway = gateway

    def upload_file(self, data: bytes, *, mime_type: str, display_name: str) -> types.File:
        """Store `data` in Replay Vision's Files API; the gateway runs Google's resumable upload."""
        if self._gateway is None:
            raise ValueError("upload_file needs the gateway config the client was built with")
        with _retry_gateway_refusals(), httpx.Client(trust_env=False, timeout=_UPLOAD_TIMEOUT) as http:
            response = http.post(
                f"{anthropic_gateway_base_url(self._gateway.url)}/v1beta/files:upload",
                content=_send_before(data, time.monotonic() + _UPLOAD_SEND_DEADLINE_S),
                headers={
                    "x-goog-api-key": self._gateway.api_key,
                    "Content-Type": mime_type,
                    "Content-Length": str(len(data)),
                    "X-Goog-Upload-Display-Name": display_name,
                },
            )
            errors.APIError.raise_for_response(response)
        return types.File.model_validate(response.json()["file"])

    async def aclose(self) -> None:
        """Close both SDK transports; the sync one carries `files` and `models`, the async one `aio`."""
        self._client.close()
        await self.aio.aclose()


def _send_before(data: bytes, deadline: float) -> Iterator[bytes]:
    view = memoryview(data)
    for start in range(0, len(data), _UPLOAD_CHUNK_BYTES):
        if time.monotonic() > deadline:
            raise httpx.WriteTimeout(f"upload passed its {_UPLOAD_SEND_DEADLINE_S:.0f}s send deadline")
        yield bytes(view[start : start + _UPLOAD_CHUNK_BYTES])


def assemble_stream(chunks: list[types.GenerateContentResponse]) -> types.GenerateContentResponse:
    """Fold streamed chunks into the response a buffered call returns.

    Parts keep their order, so thought signatures and function calls reach the next turn unchanged. Raises a 503
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
            "content": types.Content(role=role, parts=_merge_text_parts(parts)),
            "finish_reason": finish_reason,
        }
    )
    return final.model_copy(
        update={"candidates": [candidate], "usage_metadata": usage, "prompt_feedback": prompt_feedback}
    )


def _merge_text_parts(parts: Iterable[types.Part]) -> list[types.Part]:
    # Joins a run's text deltas so the next turn carries one part per run.
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
    # Any other field set makes the part more than text; a thought signature belongs to that exact part.
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
    gateway = replay_gateway_client(properties=properties, distinct_id=distinct_id, timeout_ms=timeout_ms)
    return gateway if gateway is not None else direct()


def replay_gateway_client(
    *,
    properties: Mapping[str, Any] | None = None,
    distinct_id: str | None = None,
    timeout_ms: int | None = None,
) -> GatewayGeminiClient | None:
    """The gateway client on Replay Vision's own key, or None while that key is unset. Skips the flag."""
    gateway = resolve_replay_gateway_config()
    if gateway is None:
        return None
    base_properties = dict(properties or {})
    client = build_gemini_client(
        ai_product=AI_PRODUCT,
        properties=_gateway_labels(base_properties),
        distinct_id=distinct_id,
        privacy_mode=True,
        timeout_ms=timeout_ms,
        gateway=gateway,
    )
    if client is None:
        return None
    return GatewayGeminiClient(client, base_properties, gateway)
