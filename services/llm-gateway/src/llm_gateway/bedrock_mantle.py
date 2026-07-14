from __future__ import annotations

import asyncio
import functools
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx
import litellm
import structlog
from fastapi import HTTPException

from llm_gateway.bedrock import (
    BEDROCK_ANTHROPIC_MODEL_PREFIXES,
    _sign_bedrock_mantle_request,
    get_bedrock_mantle_url,
)
from llm_gateway.callbacks.base import InstrumentedCallback
from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

BEDROCK_MANTLE_MESSAGES_PATH: Final[str] = "/anthropic/v1/messages"
# The OpenAI-compatible mantle surface selects a project with this header. Whether the
# anthropic-native /anthropic/v1/* surface expects the same name or an "anthropic-project"
# variant is unverified — confirm in dev and change this one constant if needed.
BEDROCK_MANTLE_PROJECT_HEADER: Final[str] = "OpenAI-Project"


def _short_model_name(model: str) -> str:
    """Drop any Bedrock provider/routing prefix: "us.anthropic.claude-fable-5" -> "claude-fable-5"."""
    for prefix in BEDROCK_ANTHROPIC_MODEL_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model


def to_mantle_model_id(model: str) -> str:
    """Mantle takes the bare foundation-model id ("anthropic.<model>"), never CRIS prefixes."""
    return f"anthropic.{_short_model_name(model)}"


def _configured_model_list(settings: object, field: str) -> list[str]:
    # Defensive on type: the field is env-parsed config, and several tests stub settings with a
    # bare MagicMock whose auto-created attributes must read as "feature off", not crash routing.
    values = getattr(settings, field, None)
    if not isinstance(values, list | tuple):
        return []
    return [value for value in values if isinstance(value, str)]


def matched_mantle_model(model: str, settings: object) -> str | None:
    """The configured short model name when `model` must be served via the mantle endpoint.

    Models whose Bedrock `allowed_modes` is provider_data_share only (e.g. claude-fable-5)
    reject every bedrock-runtime request, so the mantle endpoint with the dedicated project is
    the only working Bedrock path for them. Accepts short, CRIS ("us."/"eu."/"global."), and
    bare ("anthropic.") ids.
    """
    short = _short_model_name(model).lower()
    for configured in _configured_model_list(settings, "bedrock_mantle_models"):
        if configured.lower() == short:
            return configured
    return None


def is_bedrock_primary_model(model: str, settings: object) -> bool:
    """Whether this model should try Bedrock first when the caller expressed no provider."""
    return model in _configured_model_list(settings, "bedrock_primary_models")


def ensure_bedrock_mantle_project_configured(settings: object) -> str:
    project_id = getattr(settings, "bedrock_mantle_project_id", None)
    if isinstance(project_id, str) and project_id:
        return project_id

    logger.warning("Bedrock Mantle project not configured")
    raise HTTPException(
        status_code=503,
        detail={"error": {"message": "Bedrock Mantle project not configured", "type": "configuration_error"}},
    )


class MantleAPIError(Exception):
    """Anthropic-shaped provider error from the mantle endpoint.

    Exposes status_code/message/type/code because handle_llm_request's generic error mapping
    reads exactly those attributes when it re-raises the client-facing ProviderError — this is
    how the upstream status (e.g. the data-retention 400) survives to the caller and to the
    fallback logic that branches on it.
    """

    def __init__(self, status_code: int, body: bytes | str) -> None:
        message = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        error_type = "api_error"
        code: str | None = None
        try:
            error = json.loads(message).get("error") or {}
            message = str(error.get("message") or message)
            error_type = str(error.get("type") or error_type)
            code = error.get("code")
        except (json.JSONDecodeError, AttributeError):
            pass
        self.status_code = status_code
        self.message = message
        self.type = error_type
        self.code = code
        super().__init__(message)


class MantleStreamAccumulator:
    """Best-effort reconstruction of usage and content from a native Anthropic SSE stream.

    Analytics-only: a parse failure degrades to whatever was captured so far and never
    interrupts the byte passthrough to the client.
    """

    def __init__(self) -> None:
        self._buffer = b""
        self._blocks: dict[int, dict[str, Any]] = {}
        self._parse_failed = False
        self.message: dict[str, Any] = {}
        self.usage: dict[str, Any] = {}
        self.saw_message_start = False

    def feed(self, chunk: bytes) -> None:
        if self._parse_failed:
            return
        try:
            self._buffer += chunk
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                self._handle_line(line.strip())
        except Exception:
            self._parse_failed = True
            logger.warning("bedrock_mantle_stream_parse_failed", exc_info=True)

    def _handle_line(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        payload = line[len(b"data:") :].strip()
        if not payload or payload == b"[DONE]":
            return
        event = json.loads(payload)
        event_type = event.get("type")

        if event_type == "message_start":
            self.saw_message_start = True
            message = event.get("message") or {}
            self.message = {key: message.get(key) for key in ("id", "type", "role", "model", "stop_reason")}
            self.usage.update(message.get("usage") or {})
        elif event_type == "content_block_start":
            block = dict(event.get("content_block") or {})
            block.setdefault("type", "text")
            if block["type"] == "tool_use":
                block["_partial_json"] = ""
            self._blocks[int(event.get("index", 0))] = block
        elif event_type == "content_block_delta":
            block = self._blocks.get(int(event.get("index", 0)))
            if block is None:
                return
            delta = event.get("delta") or {}
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                block["text"] = block.get("text", "") + delta.get("text", "")
            elif delta_type == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
            elif delta_type == "input_json_delta":
                block["_partial_json"] = block.get("_partial_json", "") + delta.get("partial_json", "")
            elif delta_type == "signature_delta":
                block["signature"] = block.get("signature", "") + delta.get("signature", "")
        elif event_type == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason") is not None:
                self.message["stop_reason"] = delta["stop_reason"]
            # usage carries running totals (output_tokens grows monotonically), so
            # last-seen values are correct even when the stream is cut short.
            self.usage.update(event.get("usage") or {})

    def response_message(self) -> dict[str, Any] | None:
        if not self.saw_message_start:
            return None
        content: list[dict[str, Any]] = []
        for index in sorted(self._blocks):
            block = dict(self._blocks[index])
            partial_json = block.pop("_partial_json", None)
            if partial_json is not None:
                try:
                    block["input"] = json.loads(partial_json) if partial_json else {}
                except json.JSONDecodeError:
                    block["input"] = {}
            content.append(block)
        return {**self.message, "content": content, "usage": dict(self.usage)}


def compute_mantle_cost(model: str, usage: dict[str, Any]) -> tuple[float | None, dict[str, float]]:
    """Per-side cost from litellm's cost map (fable is guaranteed present via MODEL_COST_OVERRIDES).

    Returns (None, {}) when the core rates are missing so the rate-limit callback's
    token-estimation/fallback path engages instead of recording a silent zero.
    """
    rates = litellm.model_cost.get(model) or {}
    if rates.get("input_cost_per_token") is None or rates.get("output_cost_per_token") is None:
        return None, {}

    breakdown: dict[str, float] = {}
    total = 0.0
    for usage_key, rate_key, breakdown_key in (
        ("input_tokens", "input_cost_per_token", "input_cost"),
        ("output_tokens", "output_cost_per_token", "output_cost"),
        ("cache_read_input_tokens", "cache_read_input_token_cost", "cache_read_cost"),
        ("cache_creation_input_tokens", "cache_creation_input_token_cost", "cache_creation_cost"),
    ):
        rate = rates.get(rate_key)
        if rate is None:
            continue
        cost = int(usage.get(usage_key) or 0) * float(rate)
        breakdown[breakdown_key] = cost
        total += cost
    return total, breakdown


def build_mantle_callback_kwargs(
    *,
    model: str,
    request_data: dict[str, Any],
    usage: dict[str, Any],
    response_message: dict[str, Any] | None,
    response_time: float,
    is_streaming: bool,
) -> dict[str, Any]:
    """A litellm-mimicking callback payload for a hand-rolled mantle call.

    The registered InstrumentedCallback subclasses (PostHog, rate limiting, Prometheus) read a
    narrow field set from litellm's standard_logging_object; this synthesizes exactly those
    fields with litellm's conventions (prompt_tokens is the cache-inclusive total, cache tokens
    ride in metadata.usage_object, trace id in litellm_params.metadata).
    """
    input_tokens = int(usage.get("input_tokens") or 0)
    cache_read = usage.get("cache_read_input_tokens")
    cache_creation = usage.get("cache_creation_input_tokens")

    usage_object: dict[str, Any] = {}
    if cache_read is not None:
        usage_object["cache_read_input_tokens"] = cache_read
    if cache_creation is not None:
        usage_object["cache_creation_input_tokens"] = cache_creation

    response_cost, cost_breakdown = compute_mantle_cost(model, usage)

    standard_logging_object: dict[str, Any] = {
        "model": model,
        "custom_llm_provider": "bedrock",
        "messages": request_data.get("messages"),
        "prompt_tokens": input_tokens + int(cache_read or 0) + int(cache_creation or 0),
        "completion_tokens": int(usage.get("output_tokens") or 0),
        "response_time": response_time,
        "stream": is_streaming,
        "metadata": {"usage_object": usage_object},
    }
    if response_cost is not None:
        standard_logging_object["response_cost"] = response_cost
        standard_logging_object["cost_breakdown"] = cost_breakdown
    if response_message is not None:
        standard_logging_object["response"] = response_message

    return {
        "standard_logging_object": standard_logging_object,
        "litellm_params": {"metadata": request_data.get("metadata") or {}},
    }


async def _emit_callbacks(kwargs: dict[str, Any], *, success: bool, start_time: float, end_time: float) -> None:
    # InstrumentedCallback swallows its own exceptions, so attribution can never fail a request.
    for callback in litellm.callbacks:
        if not isinstance(callback, InstrumentedCallback):
            continue
        if success:
            await callback.async_log_success_event(kwargs, None, start_time, end_time)
        else:
            await callback.async_log_failure_event(kwargs, None, start_time, end_time)


@functools.lru_cache
def get_mantle_http_client() -> httpx.AsyncClient:
    """Shared pooled client — a fresh TLS handshake per request would show up in TTFT."""
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.request_timeout, write=30.0, pool=10.0),
    )


class BedrockMantleMessages:
    """Anthropic-native Messages calls against the bedrock-mantle endpoint.

    Fits handle_llm_request's llm_call contract: awaiting acreate(**request_data) returns a
    parsed message dict (non-streaming) or an async iterator of raw SSE bytes (streaming —
    mantle speaks native Anthropic SSE, so format_sse_stream's passthrough branch re-emits the
    bytes unmodified). Because the call bypasses litellm, PostHog/cost/token attribution is
    emitted explicitly via the registered callbacks.
    """

    def __init__(self, *, region_name: str, project_id: str, attribution_model: str) -> None:
        self._region_name = region_name
        self._project_id = project_id
        # The user-facing model name ("claude-fable-5"): keys the cost map and keeps
        # $ai_model consistent with the same model's first-party events.
        self._attribution_model = attribution_model

    async def acreate(self, **request_data: Any) -> Any:
        data = dict(request_data)
        extra_headers: dict[str, str] = {BEDROCK_MANTLE_PROJECT_HEADER: self._project_id}
        anthropic_beta = data.pop("anthropic_beta", None)
        if anthropic_beta:
            extra_headers["anthropic-beta"] = (
                ",".join(anthropic_beta) if isinstance(anthropic_beta, list) else str(anthropic_beta)
            )
        # The native surface takes the version as a header; the signer sets the public one.
        data.pop("anthropic_version", None)

        is_streaming = bool(data.get("stream"))
        payload = json.dumps(data).encode("utf-8")
        url = get_bedrock_mantle_url(self._region_name, BEDROCK_MANTLE_MESSAGES_PATH)
        # Credential resolution can touch the network (e.g. role refresh), so sign off the event loop.
        signed_headers = await asyncio.to_thread(
            _sign_bedrock_mantle_request, url, payload, self._region_name, extra_headers=extra_headers
        )

        start_time = time.monotonic()
        client = get_mantle_http_client()
        http_request = client.build_request("POST", url, content=payload, headers=signed_headers)
        response = await client.send(http_request, stream=True)

        if response.status_code != 200:
            body = await response.aread()
            await response.aclose()
            error = MantleAPIError(response.status_code, body)
            await self._emit_failure(data, error, is_streaming)
            raise error

        if not is_streaming:
            body = await response.aread()
            await response.aclose()
            parsed: dict[str, Any] = json.loads(body)
            await self._emit_success(
                data,
                usage=parsed.get("usage") or {},
                response_message=parsed,
                response_time=time.monotonic() - start_time,
                is_streaming=False,
            )
            return parsed

        return self._stream(response, data, start_time)

    async def _stream(
        self, response: httpx.Response, request_data: dict[str, Any], start_time: float
    ) -> AsyncIterator[bytes]:
        accumulator = MantleStreamAccumulator()
        error: Exception | None = None
        try:
            async for chunk in response.aiter_bytes():
                accumulator.feed(chunk)
                yield chunk
        except asyncio.CancelledError:
            # Client disconnect — already-streamed tokens are still billed upstream, so the
            # usage captured so far must be recorded (finally below).
            raise
        except Exception as exc:
            error = exc
            raise
        finally:
            await response.aclose()
            response_time = time.monotonic() - start_time
            try:
                if accumulator.saw_message_start:
                    await self._emit_success(
                        request_data,
                        usage=accumulator.usage,
                        response_message=accumulator.response_message(),
                        response_time=response_time,
                        is_streaming=True,
                    )
                elif error is not None:
                    await self._emit_failure(request_data, error, True)
            except Exception:
                logger.exception("bedrock_mantle_attribution_failed", model=self._attribution_model)

    async def _emit_success(
        self,
        request_data: dict[str, Any],
        *,
        usage: dict[str, Any],
        response_message: dict[str, Any] | None,
        response_time: float,
        is_streaming: bool,
    ) -> None:
        kwargs = build_mantle_callback_kwargs(
            model=self._attribution_model,
            request_data=request_data,
            usage=usage,
            response_message=response_message,
            response_time=response_time,
            is_streaming=is_streaming,
        )
        end_time = time.time()
        await _emit_callbacks(kwargs, success=True, start_time=end_time - response_time, end_time=end_time)

    async def _emit_failure(self, request_data: dict[str, Any], error: Exception, is_streaming: bool) -> None:
        kwargs = {
            "standard_logging_object": {
                "model": self._attribution_model,
                "custom_llm_provider": "bedrock",
                "stream": is_streaming,
                "error_str": str(error),
            },
            "litellm_params": {"metadata": request_data.get("metadata") or {}},
        }
        now = time.time()
        await _emit_callbacks(kwargs, success=False, start_time=now, end_time=now)
