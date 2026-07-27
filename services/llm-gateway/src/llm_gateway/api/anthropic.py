import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import litellm
import structlog
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import (
    ANTHROPIC_CONFIG,
    BEDROCK_CONFIG,
    ProviderError,
    _sanitize_request_data,
    handle_llm_request,
    normalize_litellm_model_name,
)
from llm_gateway.bedrock import (
    count_tokens_with_bedrock,
    count_tokens_with_bedrock_mantle,
    ensure_bedrock_configured,
    map_to_bedrock_model,
    supports_bedrock_runtime_count_tokens,
)
from llm_gateway.circuit_breaker import AnthropicCircuitBreaker
from llm_gateway.cloudflare import (
    cloudflare_litellm_model,
    ensure_cloudflare_model_allowed,
    is_cloudflare_model,
)
from llm_gateway.config import get_settings
from llm_gateway.dependencies import AnthropicCircuitBreakerDep, RateLimitedUser
from llm_gateway.glm_routing import send_glm_anthropic_messages
from llm_gateway.metrics.prometheus import (
    ANTHROPIC_CIRCUIT_BREAKER_BYPASSED,
    BEDROCK_COUNT_TOKENS_ERRORS,
    BEDROCK_FALLBACK_FAILURE,
    BEDROCK_FALLBACK_SUCCESS,
    BEDROCK_FALLBACK_TRIGGERED,
    BEDROCK_PARAM_STRIPPED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from llm_gateway.models.anthropic import GATEWAY_ONLY_FIELDS, AnthropicCountTokensRequest, AnthropicMessagesRequest
from llm_gateway.products.config import validate_product
from llm_gateway.request_context import (
    apply_posthog_context_from_headers,
    extract_posthog_provider_from_headers,
    extract_posthog_use_bedrock_fallback_from_headers,
)

logger = structlog.get_logger(__name__)

anthropic_router = APIRouter()

ANTHROPIC_COUNT_TOKENS_URL = "https://api.anthropic.com/v1/messages/count_tokens"
ANTHROPIC_API_VERSION = "2023-06-01"
COUNT_TOKENS_ENDPOINT_NAME = "anthropic_count_tokens"
BEDROCK_COUNT_TOKENS_ENDPOINT_NAME = "bedrock_count_tokens"


def _invalid_header_exception(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": {"message": message, "type": "invalid_request_error"}})


def _get_provider_from_headers(request: Request) -> str:
    try:
        return extract_posthog_provider_from_headers(request) or "anthropic"
    except ValueError as exc:
        raise _invalid_header_exception(str(exc)) from exc


def _get_use_bedrock_fallback_from_headers(request: Request) -> bool:
    try:
        return extract_posthog_use_bedrock_fallback_from_headers(request) or False
    except ValueError as exc:
        raise _invalid_header_exception(str(exc)) from exc


# Params that are safe to forward on the Bedrock path. This is an allowlist on purpose:
# litellm forwards request params to Bedrock verbatim (the anthropic_messages request type is a
# TypedDict, so unknown keys pass straight through), and Bedrock hard-rejects unknown top-level
# fields with a 400 ("Extra inputs are not permitted"). Anything outside this set is dropped, not
# forwarded, so new Anthropic-only params (context_management, inference_geo, speed, mcp_servers,
# …) degrade gracefully on the fallback path instead of breaking it. The BEDROCK_PARAM_STRIPPED
# metric is the early-warning signal: extend this set when a dropped param turns out to be
# Bedrock-supported. Cross-checked against litellm's bedrock anthropic_messages transform.
BEDROCK_SUPPORTED_PARAMS: frozenset[str] = frozenset(
    {
        # Routing / protocol — consumed or rewritten by litellm before it hits Bedrock.
        "model",
        "stream",
        "anthropic_version",
        "anthropic_beta",
        # Anthropic Messages body params that Bedrock-hosted Claude accepts natively.
        "messages",
        "system",
        "max_tokens",
        "stop_sequences",
        "temperature",
        "top_p",
        "top_k",
        "tools",
        "tool_choice",
        "thinking",
        "metadata",
        # Structured outputs. Kept at the top level, but note Bedrock-hosted Claude rejects the
        # nested output_config.format schema with a 400 ("output_config.format: Extra inputs are
        # not permitted"), so that sub-key is stripped separately (strip_structured_output_format);
        # the rest of output_config (e.g. {"effort": ...}) is accepted and forwarded.
        "output_format",
        "output_config",
    }
)

# Sub-keys of output_config that Bedrock-hosted Claude rejects even though it accepts output_config
# itself. Bedrock's error names the nested path (output_config.format), so the whole object can't be
# dropped without losing supported sub-keys like effort — these are stripped individually instead.
BEDROCK_UNSUPPORTED_OUTPUT_CONFIG_KEYS: frozenset[str] = frozenset({"format"})


# Cap how much of a provider error message we copy into structured logs — provider 5xx bodies can be
# multi-KB HTML error pages (e.g. Cloudflare 520s), and we only need enough to identify the failure.
_MAX_LOGGED_ERROR_MESSAGE_CHARS = 2048


def _exception_log_fields(exc: BaseException, *, prefix: str) -> dict[str, Any]:
    """Pull the queryable bits out of an exception for structured logging.

    `logger.exception` attaches the traceback via exc_info, but that text doesn't land in the
    rendered JSON body — so the actual provider error (status + message) is invisible when grepping
    logs. This surfaces it as explicit fields. For HTTPException we prefer the structured
    `detail["error"]["message"]` (the real upstream message) over `str(exc)`.
    """
    status = getattr(exc, "status_code", None)
    message = str(exc)
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"])
    return {
        f"{prefix}_status": status,
        f"{prefix}_error_type": type(exc).__name__,
        f"{prefix}_error_message": message[:_MAX_LOGGED_ERROR_MESSAGE_CHARS],
    }


def _bedrock_runtime_exception_log_fields(exc: BaseException) -> dict[str, Any]:
    fields = _exception_log_fields(exc, prefix="runtime")
    if not isinstance(exc, ClientError):
        return fields

    error = exc.response.get("Error", {})
    metadata = exc.response.get("ResponseMetadata", {})
    status = metadata.get("HTTPStatusCode")
    if status is not None:
        fields["runtime_status"] = status

    error_code = error.get("Code")
    if error_code:
        fields["runtime_error_code"] = str(error_code)

    message = error.get("Message")
    if message:
        fields["runtime_error_message"] = str(message)[:_MAX_LOGGED_ERROR_MESSAGE_CHARS]

    return fields


def sanitize_for_bedrock(data: dict[str, Any], *, model: str, product: str) -> dict[str, Any]:
    """Adapt an Anthropic Messages request for the Bedrock path.

    Returns a new dict containing only Bedrock-supported top-level params; unsupported params are
    dropped (with a warning + metric) so they can't 400 the request. Unsupported output_config
    sub-keys, server-side tool definitions, and any references to them left in the message history
    or tool_choice are stripped too — Bedrock 400s on all of these.
    """
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if key in BEDROCK_SUPPORTED_PARAMS:
            sanitized[key] = value
            continue
        logger.warning("Stripping unsupported param for Bedrock", param=key, model=model, product=product)
        BEDROCK_PARAM_STRIPPED.labels(param=key, product=product).inc()

    strip_structured_output_format(sanitized, model=model, product=product)
    strip_server_side_tools(sanitized, model=model, product=product)
    strip_server_side_tool_uses_from_messages(sanitized, model=model, product=product)
    reconcile_tool_choice(sanitized, model=model, product=product)
    return sanitized


def strip_structured_output_format(data: dict[str, Any], *, model: str, product: str) -> None:
    """Drop output_config sub-keys Bedrock rejects (e.g. format), keeping the rest of output_config.

    Bedrock-hosted Claude 400s on output_config.format ("Extra inputs are not permitted") but
    accepts output_config itself, so we prune just the unsupported sub-keys rather than dropping the
    whole object — that keeps supported sub-keys like effort working on the fallback.
    """
    output_config = data.get("output_config")
    if not isinstance(output_config, dict):
        return
    unsupported = [key for key in output_config if key in BEDROCK_UNSUPPORTED_OUTPUT_CONFIG_KEYS]
    if not unsupported:
        return

    cleaned = {key: value for key, value in output_config.items() if key not in BEDROCK_UNSUPPORTED_OUTPUT_CONFIG_KEYS}
    if cleaned:
        data["output_config"] = cleaned
    else:
        del data["output_config"]
    for key in unsupported:
        logger.warning("Stripping unsupported output_config key for Bedrock", key=key, model=model, product=product)
        BEDROCK_PARAM_STRIPPED.labels(param=f"output_config.{key}", product=product).inc()


def strip_server_side_tools(data: dict[str, Any], *, model: str, product: str) -> None:
    """Remove Anthropic server-side tools (e.g. web_search) that Bedrock doesn't support.

    Server-side tools have a non-standard type (like web_search_20250305), while regular tools use custom or function (or omit type entirely, defaulting to custom).
    """
    if "tools" not in data:
        return

    supported: list[dict[str, Any]] = []
    for tool in data["tools"]:
        if tool.get("type", "custom") in ("custom", "function"):
            supported.append(tool)
        else:
            logger.warning(
                "Stripping unsupported tool for Bedrock",
                tool_name=tool.get("name"),
                tool_type=tool.get("type"),
                model=model,
                product=product,
            )

    if supported:
        data["tools"] = supported
    else:
        del data["tools"]


def strip_server_side_tool_uses_from_messages(data: dict[str, Any], *, model: str, product: str) -> None:
    """Remove server-side tool_use / tool_result blocks left in the message history.

    Stripping the server-side tool *definitions* isn't enough: a prior turn's server_tool_use block
    (or its matching *_tool_result block, e.g. web_search_tool_result) still references a tool no
    longer in the request, and Bedrock 400s with "Tool '<name>' not found in provided tools". Client
    tool_use / tool_result blocks (type == "tool_result") are kept — only server-side ones are dropped.
    A message whose content becomes empty as a result is dropped, then any turns left adjacent by the
    drop are coalesced so the sequence keeps alternating roles (Bedrock 400s on non-alternating roles).
    """
    messages = data.get("messages")
    if not isinstance(messages, list):
        return

    new_messages: list[Any] = []
    stripped = False
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            new_messages.append(message)
            continue

        kept_blocks = [block for block in content if not _is_server_side_tool_block(block)]
        if len(kept_blocks) == len(content):
            new_messages.append(message)
            continue

        stripped = True
        if kept_blocks:
            new_messages.append({**message, "content": kept_blocks})
        # else: content emptied by the strip — drop the message; _coalesce_adjacent_roles below merges
        # any same-role turns the drop left back-to-back so we don't emit an invalid message sequence.

    if stripped:
        data["messages"] = _coalesce_adjacent_roles(new_messages)
        logger.warning("Stripping server-side tool blocks from messages for Bedrock", model=model, product=product)
        BEDROCK_PARAM_STRIPPED.labels(param="messages.server_tool_blocks", product=product).inc()


def _coalesce_adjacent_roles(messages: list[Any]) -> list[Any]:
    """Merge consecutive same-role messages into one, concatenating their content.

    Dropping an emptied tool-only turn can leave two same-role messages back to back, which Bedrock
    rejects. A valid input already alternates roles, so this only merges turns made adjacent by a drop.
    """
    merged: list[Any] = []
    for message in messages:
        prev = merged[-1] if merged else None
        if isinstance(message, dict) and isinstance(prev, dict) and message.get("role") == prev.get("role"):
            merged[-1] = {
                **prev,
                "content": _content_as_blocks(prev.get("content")) + _content_as_blocks(message.get("content")),
            }
        else:
            merged.append(message)
    return merged


def _content_as_blocks(content: Any) -> list[Any]:
    """Normalize message content to a block list so two turns can be concatenated."""
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [content]


def _is_server_side_tool_block(block: Any) -> bool:
    """A block Anthropic produces for a server-side tool run, which Bedrock can't validate."""
    if not isinstance(block, dict):
        return False
    block_type = block.get("type")
    if not isinstance(block_type, str):
        return False
    # server_tool_use / mcp_tool_use are the calls; "<tool>_tool_result" are their results. A plain
    # client "tool_result" (exact match) is kept — only the server-side, type-prefixed ones go.
    return block_type in ("server_tool_use", "mcp_tool_use") or (
        block_type.endswith("_tool_result") and block_type != "tool_result"
    )


def reconcile_tool_choice(data: dict[str, Any], *, model: str, product: str) -> None:
    """Drop a tool_choice that can no longer be satisfied after server-side tools were stripped.

    Bedrock 400s on a tool_choice that names a tool absent from the tools list. When stripping left
    no tools at all, tool_choice is dropped regardless of type: "any"/"tool" force tool use that
    can't happen, and even "auto"/"none" are no-ops without tools yet still risk rejection as a
    tool_choice with nothing to choose from.
    """
    tool_choice = data.get("tool_choice")
    if not isinstance(tool_choice, dict):
        return

    tools = data.get("tools")
    tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)} if isinstance(tools, list) else set()

    if tool_names:
        drop = tool_choice.get("type") == "tool" and tool_choice.get("name") not in tool_names
    else:
        drop = True

    if drop:
        del data["tool_choice"]
        logger.warning(
            "Dropping unsatisfiable tool_choice for Bedrock", tool_choice=tool_choice, model=model, product=product
        )
        BEDROCK_PARAM_STRIPPED.labels(param="tool_choice", product=product).inc()


async def _send_bedrock_messages(
    request_data: dict[str, Any],
    user: RateLimitedUser,
    request: Request,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    settings = get_settings()
    bedrock_region_name = ensure_bedrock_configured(settings)

    data = dict(request_data)
    bedrock_model = map_to_bedrock_model(data["model"], region_name=bedrock_region_name)
    # litellm can't infer the bedrock provider from regional inference profile
    # ids like "us.anthropic.claude-opus-4-7", so prefix explicitly.
    data["model"] = f"bedrock/{bedrock_model}"

    anthropic_beta = request.headers.get("anthropic-beta")
    if anthropic_beta:
        data["anthropic_beta"] = [h.strip() for h in anthropic_beta.split(",") if h.strip()]

    data = sanitize_for_bedrock(data, model=bedrock_model, product=product)

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=bedrock_model,
        is_streaming=is_streaming,
        provider_config=BEDROCK_CONFIG,
        llm_call=litellm.anthropic_messages,
        product=product,
    )


async def _maybe_bypass_anthropic(
    breaker: AnthropicCircuitBreaker | None,
    model: str,
    product: str,
    *,
    use_bedrock_fallback: bool,
) -> bool:
    """Bypass requires the caller to have opted in via `use_bedrock_fallback`; without that
    we never silently change the upstream provider, even if Anthropic looks unhealthy.
    """
    if breaker is None or not use_bedrock_fallback:
        return False

    decision = await breaker.evaluate()
    if decision.bypass:
        ANTHROPIC_CIRCUIT_BREAKER_BYPASSED.labels(model=model, product=product).inc()
    return decision.bypass


# Substrings that identify Anthropic's billing / spend-limit refusals within a 400 error message.
# Anthropic returns these as HTTP 400 invalid_request_error — the same status+type as a genuinely
# malformed request — so the status code can't tell them apart and the message is the only signal.
# Matched case-insensitively. Keep this a tight allowlist: broadening it to all 400s would fail
# real bad requests (prompt-too-long, bad image, role ordering) over to Bedrock, which rejects them
# identically and just adds a wasted round-trip.
_ANTHROPIC_BILLING_SIGNATURES: tuple[str, ...] = (
    "credit balance",  # "Your credit balance is too low to access the Anthropic API"
    "usage limit",  # "You have reached your specified workspace API usage limits"
    "regain access",  # "...You will regain access on <date>"
    "plans & billing",  # "...go to Plans & Billing to upgrade or purchase credits"
)


def _is_anthropic_billing_block(exc: HTTPException) -> bool:
    """True when Anthropic refused the request for billing / spend-limit reasons.

    These surface as HTTP 400 invalid_request_error (e.g. a workspace usage-limit block or an
    exhausted prepaid balance), not 5xx/429 — so they are genuinely provider-down but look like a
    caller error. We match the upstream message carried in `detail["error"]["message"]`.

    Gated on `ProviderError` so it only ever fires on a genuine upstream-provider failure: a
    gateway-local 400 (e.g. unsupported model) echoes the caller's model name into the message, and
    without this guard a crafted name like "gemini/credit balance is too low" would be misread as a
    billing block and poison the shared circuit breaker.
    """
    if not isinstance(exc, ProviderError):
        return False
    if exc.status_code != 400:
        return False
    detail = exc.detail
    if not isinstance(detail, dict):
        return False
    error = detail.get("error")
    if not isinstance(error, dict):
        return False
    message = str(error.get("message", "")).lower()
    return any(signature in message for signature in _ANTHROPIC_BILLING_SIGNATURES)


def _anthropic_error_type(exc: HTTPException) -> str:
    """The provider error type from an Anthropic-style HTTPException detail, or "unknown"."""
    detail = exc.detail
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict):
            return str(error.get("type", "unknown"))
    return "unknown"


def _is_breaker_success(status_code: int) -> bool:
    """4xx are caller-side errors and don't reflect Anthropic health, except 429 — that's
    Anthropic-side throttling and is exactly the kind of degradation the breaker exists for.
    """
    if status_code == 429:
        return False
    return status_code < 500


async def _record_anthropic_outcome(breaker: AnthropicCircuitBreaker | None, success: bool) -> None:
    if breaker is None:
        return
    await breaker.record_outcome(success=success)


def _wrap_stream_with_breaker(
    response: StreamingResponse,
    breaker: AnthropicCircuitBreaker | None,
) -> StreamingResponse:
    """Record the breaker outcome from inside the stream generator's lifecycle so mid-stream
    Anthropic failures aren't misrecorded as successes — the connection-level success that
    `handle_llm_request` returns isn't a reliable signal for streaming traffic.
    """
    if breaker is None:
        return response

    inner = response.body_iterator

    async def wrapped() -> AsyncIterator[str | bytes | memoryview]:
        success = True
        try:
            async for chunk in inner:
                # body_iterator types loosely as str|bytes|memoryview; our upstream only emits bytes.
                yield cast(bytes, chunk)
        except asyncio.CancelledError:
            # Client disconnect — neither success nor failure of Anthropic.
            raise
        except Exception:
            success = False
            raise
        finally:
            try:
                await breaker.record_outcome(success=success)
            except Exception as exc:
                logger.exception(
                    "circuit_breaker_stream_record_failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

    response.body_iterator = wrapped()
    return response


async def _handle_anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
    breaker: AnthropicCircuitBreaker | None,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    data = body.model_dump(exclude_none=True, exclude=GATEWAY_ONLY_FIELDS)
    provider = _get_provider_from_headers(request)
    use_bedrock_fallback = _get_use_bedrock_fallback_from_headers(request)

    # `@cf/` models are served by the GLM routing layer (Cloudflare, or Modal during the ramp), so
    # route them by model id — the same way the chat/completions and responses handlers do. The
    # agent harness derives the provider header from the runtime (`claude`->anthropic,
    # `codex`->openai) and never sends "cloudflare", so a claude-runtime scout on a CF-served model
    # (e.g. GLM) arrives here as provider="anthropic". Without the id check it would fall through to
    # the real Anthropic API and 404. Unlike the Responses path, this route serves tools fine:
    # litellm's Anthropic->chat/completions adapter translates Anthropic tools into OpenAI function
    # tools that both backends' OpenAI-compatible endpoints accept.
    if provider == "cloudflare" or is_cloudflare_model(body.model):
        return await send_glm_anthropic_messages(data, user, body.stream or False, product)

    if provider == "bedrock":
        return await _send_bedrock_messages(data, user, request, body.stream or False, product)

    if await _maybe_bypass_anthropic(breaker, body.model, product, use_bedrock_fallback=use_bedrock_fallback):
        return await _send_bedrock_messages(data, user, request, body.stream or False, product)

    litellm_data = {**data, "model": normalize_litellm_model_name(body.model, ANTHROPIC_CONFIG.name)}

    try:
        result = await handle_llm_request(
            request_data=litellm_data,
            user=user,
            model=body.model,
            is_streaming=body.stream or False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=litellm.anthropic_messages,
            product=product,
        )
    except HTTPException as exc:
        # Provider-attributable failures we fail over for: 5xx, 429 throttling, and billing/spend-limit
        # blocks (which arrive as 400 invalid_request_error). All three are recorded as breaker
        # failures so the breaker can open; ordinary caller-side 4xx stay a breaker success.
        billing_block = _is_anthropic_billing_block(exc)
        fallback_eligible = billing_block or not _is_breaker_success(exc.status_code)
        await _record_anthropic_outcome(breaker, success=not fallback_eligible)
        if not use_bedrock_fallback or not fallback_eligible:
            raise

        error_type = "billing_block" if billing_block else _anthropic_error_type(exc)
        logger.warning(
            "Anthropic request failed, attempting Bedrock fallback",
            model=body.model,
            product=product,
            original_status=exc.status_code,
            original_error_type=error_type,
        )
        BEDROCK_FALLBACK_TRIGGERED.labels(model=body.model, product=product, original_error_type=error_type).inc()

        try:
            result = await _send_bedrock_messages(data, user, request, body.stream or False, product)
            BEDROCK_FALLBACK_SUCCESS.labels(model=body.model, product=product).inc()
            return result
        except Exception as bedrock_exc:
            BEDROCK_FALLBACK_FAILURE.labels(model=body.model, product=product).inc()
            logger.exception(
                "Bedrock fallback also failed",
                model=body.model,
                product=product,
                original_status=exc.status_code,
                original_error_type=error_type,
                **_exception_log_fields(bedrock_exc, prefix="bedrock"),
            )
            raise exc from None
    else:
        if isinstance(result, StreamingResponse):
            # Outcome recorded from inside the stream generator (see _wrap_stream_with_breaker).
            return _wrap_stream_with_breaker(result, breaker)
        await _record_anthropic_outcome(breaker, success=True)
        return result


async def _handle_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    request: Request,
    breaker: AnthropicCircuitBreaker | None,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    data = _sanitize_request_data(body.model_dump(exclude_none=True, exclude=GATEWAY_ONLY_FIELDS))
    provider = _get_provider_from_headers(request)
    use_bedrock_fallback = _get_use_bedrock_fallback_from_headers(request)

    # Route `@cf/` models by model id (see `_handle_anthropic_messages`): a claude-runtime scout on a
    # CF model counts tokens here with provider="anthropic", and CF has no count_tokens endpoint, so
    # approximate locally rather than POST a CF model id to the real Anthropic count_tokens API.
    if provider == "cloudflare" or is_cloudflare_model(body.model):
        ensure_cloudflare_model_allowed(body.model)
        # CF Workers AI has no count_tokens endpoint. Approximate via litellm's tokenizer on the
        # serialised payload — callers use this for context-window budgeting, where over-counting
        # just trims and only under-counting would overflow.
        aliased_model = cloudflare_litellm_model(body.model)
        try:
            count = await asyncio.to_thread(litellm.token_counter, model=aliased_model, text=json.dumps(data))
        except Exception as exc:
            logger.exception("cloudflare_count_tokens_failed", model=body.model)
            raise HTTPException(
                status_code=502,
                detail={"error": {"message": "Failed to count tokens", "type": "internal_error"}},
            ) from exc
        return {"input_tokens": count}

    if provider == "bedrock":
        return await _bedrock_count_tokens_impl(data, body.model, user, product)

    if await _maybe_bypass_anthropic(breaker, body.model, product, use_bedrock_fallback=use_bedrock_fallback):
        return await _bedrock_count_tokens_impl(data, body.model, user, product)

    try:
        result = await _anthropic_count_tokens_impl(data, body.model, user, product)
    except HTTPException as exc:
        await _record_anthropic_outcome(breaker, success=_is_breaker_success(exc.status_code))
        if not use_bedrock_fallback or _is_breaker_success(exc.status_code):
            raise

        error_type = _anthropic_error_type(exc)
        logger.warning(
            "Anthropic count_tokens failed, attempting Bedrock fallback",
            model=body.model,
            product=product,
            original_status=exc.status_code,
            original_error_type=error_type,
        )
        BEDROCK_FALLBACK_TRIGGERED.labels(model=body.model, product=product, original_error_type=error_type).inc()

        try:
            result = await _bedrock_count_tokens_impl(data, body.model, user, product)
            BEDROCK_FALLBACK_SUCCESS.labels(model=body.model, product=product).inc()
            return result
        except Exception as bedrock_exc:
            BEDROCK_FALLBACK_FAILURE.labels(model=body.model, product=product).inc()
            logger.exception(
                "Bedrock count_tokens fallback also failed",
                model=body.model,
                product=product,
                original_status=exc.status_code,
                original_error_type=error_type,
                **_exception_log_fields(bedrock_exc, prefix="bedrock"),
            )
            raise exc from None
    else:
        await _record_anthropic_outcome(breaker, success=True)
        return result


async def _anthropic_count_tokens_impl(
    data: dict[str, Any],
    model: str,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any]:
    settings = get_settings()
    start_time = time.monotonic()
    status_code = "200"

    api_key = settings.anthropic_api_key
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Anthropic API key not configured", "type": "configuration_error"}},
        )

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.post(
                ANTHROPIC_COUNT_TOKENS_URL,
                json=data,
                headers=headers,
            )

        if response.status_code != 200:
            status_code = str(response.status_code)
            try:
                error_body = response.json()
            except Exception:
                error_body = {"error": {"message": response.text, "type": "api_error"}}
            raise HTTPException(status_code=response.status_code, detail=error_body)

        return response.json()

    except HTTPException:
        raise
    except Exception as e:
        status_code = "502"
        logger.exception(
            "count_tokens_proxy_failed",
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail={"error": {"message": "Failed to proxy request to Anthropic", "type": "proxy_error"}},
        ) from e
    finally:
        REQUEST_COUNT.labels(
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            provider="anthropic",
            model=model,
            status_code=status_code,
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            provider="anthropic",
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)


async def _bedrock_count_tokens_impl(
    data: dict[str, Any],
    model: str,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any]:
    settings = get_settings()
    bedrock_region_name = ensure_bedrock_configured(settings)

    bedrock_model = map_to_bedrock_model(model, region_name=bedrock_region_name)
    data = sanitize_for_bedrock(data, model=bedrock_model, product=product)
    start_time = time.monotonic()
    status_code = "200"

    try:
        # bedrock-runtime CountTokens rejects some models outright ("The provided model doesn't
        # support counting tokens."); for those, skip the doomed runtime call and go straight to
        # AWS's recommended path — Anthropic's count_tokens API on the bedrock-mantle endpoint.
        runtime_exception: Exception | None = None
        if supports_bedrock_runtime_count_tokens(bedrock_model):
            try:
                input_tokens = await count_tokens_with_bedrock(
                    data,
                    bedrock_model,
                    bedrock_region_name,
                    settings.request_timeout,
                    product=product,
                )
                return {"input_tokens": input_tokens}
            except Exception as e:
                # Unexpected runtime failure — try the mantle endpoint before giving up.
                runtime_exception = e
                logger.exception(
                    "Bedrock CountTokens failed",
                    model=bedrock_model,
                    product=product,
                    **_bedrock_runtime_exception_log_fields(e),
                )
                BEDROCK_COUNT_TOKENS_ERRORS.labels(
                    transport="runtime",
                    error_type=type(e).__name__,
                    product=product,
                ).inc()
                logger.info("Attempting bedrock-mantle count_tokens fallback", model=bedrock_model, product=product)

        try:
            input_tokens = await count_tokens_with_bedrock_mantle(
                data,
                bedrock_model,
                bedrock_region_name,
                settings.request_timeout,
                product=product,
            )
            return {"input_tokens": input_tokens}
        except Exception as mantle_exc:
            status_code = "502"
            error_type_name = type(mantle_exc).__name__
            runtime_log_fields = (
                _bedrock_runtime_exception_log_fields(runtime_exception) if runtime_exception is not None else {}
            )
            logger.exception(
                "Error proxying bedrock-mantle count_tokens request",
                model=bedrock_model,
                product=product,
                **_exception_log_fields(mantle_exc, prefix="mantle"),
                **runtime_log_fields,
            )
            BEDROCK_COUNT_TOKENS_ERRORS.labels(
                transport="mantle",
                error_type=error_type_name,
                product=product,
            ).inc()
            raise HTTPException(
                status_code=502,
                detail={
                    "error": {
                        "message": f"Failed to count tokens via Bedrock ({error_type_name})",
                        "type": "proxy_error",
                    }
                },
            ) from mantle_exc
    finally:
        REQUEST_COUNT.labels(
            endpoint=BEDROCK_COUNT_TOKENS_ENDPOINT_NAME,
            provider="bedrock",
            model=bedrock_model,
            status_code=status_code,
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=BEDROCK_COUNT_TOKENS_ENDPOINT_NAME,
            provider="bedrock",
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)


@anthropic_router.post("/v1/messages/count_tokens", response_model=None)
async def anthropic_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    request: Request,
    breaker: AnthropicCircuitBreakerDep,
) -> dict[str, Any]:
    return await _handle_count_tokens(body, user, request, breaker)


@anthropic_router.post("/{product}/v1/messages/count_tokens", response_model=None)
async def anthropic_count_tokens_with_product(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
    breaker: AnthropicCircuitBreakerDep,
) -> dict[str, Any]:
    validate_product(product)
    return await _handle_count_tokens(body, user, request, breaker, product=product)


@anthropic_router.post("/v1/messages", response_model=None)
async def anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
    breaker: AnthropicCircuitBreakerDep,
) -> dict[str, Any] | StreamingResponse:
    apply_posthog_context_from_headers(request)
    return await _handle_anthropic_messages(body, user, request, breaker)


@anthropic_router.post("/{product}/v1/messages", response_model=None)
async def anthropic_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
    breaker: AnthropicCircuitBreakerDep,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    apply_posthog_context_from_headers(request)
    return await _handle_anthropic_messages(body, user, request, breaker, product=product)
