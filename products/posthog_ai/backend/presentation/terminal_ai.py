import json
from collections.abc import Iterator
from enum import StrEnum
from typing import Literal, cast
from uuid import uuid4

from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse

import httpx
import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from pydantic_core import PydanticSerializationError
from rest_framework.exceptions import (
    APIException,
    PermissionDenied,
    ValidationError as RequestValidationError,
)
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import sse_streaming_response
from posthog.auth import SessionAuthentication
from posthog.exceptions import QuotaLimitExceeded
from posthog.llm.gateway_client import ai_gateway_headers, resolve_ai_gateway_config
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited
from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

logger = structlog.get_logger(__name__)


class TerminalAIMessage(BaseModel):
    role: Literal["user", "assistant"] = Field(description="Author of this conversation message.")
    content: str | list[dict[str, JsonValue]] = Field(description="Anthropic text, image, or tool content blocks.")


class TerminalAITool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=128, description="Name of a tool executed inside the terminal.")
    description: str = Field(default="", max_length=20000, description="What the tool does.")
    input_schema: dict[str, JsonValue] = Field(description="JSON schema for the tool's arguments.")
    cache_control: dict[str, str] | None = Field(default=None, description="Provider prompt cache settings.")
    eager_input_streaming: bool | None = Field(default=None, description="Stream tool arguments as they are generated.")


class TerminalAIModel(StrEnum):
    OPUS_5 = "claude-opus-5"
    SONNET_5 = "claude-sonnet-5"
    SONNET_4_6 = "claude-sonnet-4-6"
    HAIKU_4_5 = "claude-haiku-4-5"


class TerminalAIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: TerminalAIModel = Field(description="Model served by the PostHog provider.")
    messages: list[TerminalAIMessage] = Field(
        min_length=1, max_length=1000, description="Conversation and tool results."
    )
    max_tokens: int = Field(ge=1, le=8192, description="Maximum output tokens for this generation.")
    stream: Literal[True] = Field(default=True, description="Always stream the model response.")
    system: str | list[dict[str, JsonValue]] | None = Field(default=None, description="Agent instructions.")
    tools: list[TerminalAITool] = Field(default_factory=list, max_length=100, description="Tools executed by pi.")
    temperature: float | None = Field(default=None, ge=0, le=1, description="Sampling temperature.")


class TerminalAIUnavailable(APIException):
    status_code = 503
    default_detail = (
        "PostHog AI is not configured for this terminal. Ask your administrator to configure the AI gateway."
    )


def _stream_generation(url: str, headers: dict[str, str], body: str) -> Iterator[bytes]:
    try:
        with httpx.Client(trust_env=False, timeout=httpx.Timeout(120, connect=10)) as client:
            with client.stream("POST", url, headers=headers, content=body) as response:
                if response.is_success:
                    yield from response.iter_bytes()
                    return
                message = {
                    400: "The model rejected the conversation. Start a new pi session or shorten the prompt.",
                    402: "PostHog AI has reached its spending limit. Check your billing settings.",
                    429: "PostHog AI is busy. Wait a moment and try again.",
                }.get(response.status_code, "PostHog AI could not complete the request. Try again in a moment.")
                logger.warning("terminal_ai_gateway_request_failed", status=response.status_code)
    except httpx.HTTPError as exc:
        # The exception class, not its text: an httpx message can carry the gateway URL.
        logger.warning("terminal_ai_gateway_transport_failed", error=type(exc).__name__)
        message = "The connection to PostHog AI failed. Try again in a moment."
    error = {"type": "error", "error": {"type": "api_error", "message": message}}
    yield f"event: error\ndata: {json.dumps(error)}\n\n".encode()


class TerminalAIViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "conversation"
    authentication_classes = [SessionAuthentication]
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    @extend_schema(
        request=TerminalAIRequest,
        responses={(200, "text/event-stream"): OpenApiTypes.STR},
        description=(
            "Stream a terminal model response through PostHog AI. Requires organization approval for AI data processing. "
            "SDK consumers must use getTerminalAiCreateUrl() with streaming fetch. "
            "The generated JSON client buffers the response and cannot parse SSE."
        ),
    )
    def create(self, request: Request, **kwargs: object) -> HttpResponse | StreamingHttpResponse:
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            raise PermissionDenied("Sign in to use PostHog AI in the terminal.")
        if self.team.organization.is_ai_data_processing_approved is not True:
            raise PermissionDenied(
                "Enable AI data processing in organization settings to use PostHog AI in the terminal."
            )
        user = cast(User, request.user)
        if not feature_enabled_or_false(
            "posthog-terminal",
            str(user.distinct_id),
            groups={"organization": str(self.team.organization_id)},
        ):
            raise PermissionDenied("The terminal is not enabled for this account.")
        if is_team_limited(self.team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise QuotaLimitExceeded("Your organization reached its AI credit limit. Check your billing settings.")
        gateway = resolve_ai_gateway_config()
        if gateway is None:
            raise TerminalAIUnavailable()
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            raise RequestValidationError("Invalid request size. Start a new pi session.")
        if content_length > 1024 * 1024:
            raise RequestValidationError("The conversation exceeds 1 MiB. Start a new pi session.")
        try:
            if len(json.dumps(request.data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 1024 * 1024:
                raise RequestValidationError("The conversation exceeds 1 MiB. Start a new pi session.")
            body = TerminalAIRequest.model_validate(request.data).model_dump_json(exclude_none=True)
        except (ValidationError, UnicodeEncodeError, PydanticSerializationError):
            raise RequestValidationError("Invalid model request. Use pi's PostHog provider.")
        # Keep the gateway credential server-side; derive attribution and policy headers from the authenticated session.
        headers = (
            ai_gateway_headers(
                ai_product="posthog_ai",
                distinct_id=user.distinct_id,
                trace_id=str(uuid4()),
                properties={"team_id": str(self.team_id), "ai_stage": "terminal"},
            )
            or {}
        )
        headers.update(
            {"x-api-key": gateway.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        )
        if is_impersonated_session(request):
            headers["X-PostHog-Billable"] = "false"
        if is_privacy_mode_enabled(self.team):
            headers["X-PostHog-Privacy-Mode"] = "true"
        stream = _stream_generation(f"{gateway.url.rstrip('/')}/messages", headers, body)
        return sse_streaming_response(
            SyncIterableToAsync(stream) if settings.SERVER_GATEWAY_INTERFACE == "ASGI" else stream,
            endpoint="terminal_ai",
        )
