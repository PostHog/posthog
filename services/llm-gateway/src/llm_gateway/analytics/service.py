from typing import Any
from uuid import uuid4

import posthoganalytics
import structlog

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

_analytics_service: "LLMAnalyticsService | None" = None


def init_analytics_service() -> "LLMAnalyticsService | None":
    """Initialize the analytics service on startup."""
    global _analytics_service
    settings = get_settings()
    api_key = settings.posthog_project_token

    if not api_key:
        logger.info("LLM analytics disabled - to enable, set LLM_GATEWAY_POSTHOG_PROJECT_TOKEN in mprocs.yaml")
        return None
    _analytics_service = LLMAnalyticsService(
        api_key=api_key,
        host=settings.posthog_host,
    )
    logger.info("LLM analytics service initialized")
    return _analytics_service


def get_analytics_service() -> "LLMAnalyticsService | None":
    """Get the analytics service instance."""
    return _analytics_service


def shutdown_analytics_service() -> None:
    """Flush pending events and shutdown."""
    global _analytics_service
    if _analytics_service is not None:
        _analytics_service.shutdown()
        _analytics_service = None


class LLMAnalyticsService:
    """Captures LLM generation events to PostHog."""

    def __init__(self, api_key: str, host: str):
        self._api_key = api_key
        self._host = host
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            posthoganalytics.api_key = self._api_key
            posthoganalytics.host = self._host
            # posthoganalytics handles batching automatically:
            # - Events are queued and flushed every ~0.5s or when queue reaches ~100 events
            # - shutdown() flushes remaining events on exit
            self._client = posthoganalytics
        return self._client

    def capture(
        self,
        user: AuthenticatedUser,
        model: str,
        provider: str,
        input_messages: list[dict[str, Any]],
        latency_seconds: float,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
        is_streaming: bool = False,
        input_tokens_field: str = "input_tokens",
        output_tokens_field: str = "output_tokens",
        trace_id: str | None = None,
    ) -> None:
        """Capture an LLM generation event."""
        try:
            client = self._get_client()
            span_id = str(uuid4())
            resolved_trace_id = trace_id or str(uuid4())

            input_tokens = 0
            output_tokens = 0
            output_choices: list[dict[str, Any]] = []
            resolved_model = model

            if response:
                usage = response.get("usage", {})
                input_tokens = usage.get(input_tokens_field, 0)
                output_tokens = usage.get(output_tokens_field, 0)
                output_choices = self._extract_output_choices(response, provider)
                resolved_model = response.get("model", model)

            http_status = 200
            if error:
                http_status = getattr(error, "status_code", 500)

            properties: dict[str, Any] = {
                "$ai_model": resolved_model,
                "$ai_provider": provider,
                "$ai_input": input_messages,
                "$ai_latency": latency_seconds,
                "$ai_trace_id": resolved_trace_id,
                "$ai_span_id": span_id,
                "$ai_http_status": http_status,
                "$ai_input_tokens": input_tokens,
                "$ai_output_tokens": output_tokens,
                "$ai_is_streaming": is_streaming,
                "team_id": user.team_id,
                "ai_product": "llm_gateway",
            }

            if output_choices:
                properties["$ai_output_choices"] = output_choices

            if error:
                properties["$ai_is_error"] = True
                properties["$ai_error"] = getattr(error, "message", str(error))

            client.capture(
                distinct_id=str(user.user_id),
                event="$ai_generation",
                properties=properties,
                groups={"project": str(user.team_id)},
            )
        except Exception as e:
            logger.warning("Failed to capture LLM generation event", error=str(e))

    def _extract_output_choices(self, response: dict[str, Any], provider: str) -> list[dict[str, Any]]:
        if provider == "anthropic":
            content = response.get("content", [])
            role = response.get("role", "assistant")
            return [
                {
                    "role": role,
                    "content": (block.get("text", str(block)) if isinstance(block, dict) else str(block)),
                }
                for block in content
            ]
        else:
            choices = response.get("choices", [])
            return [
                {
                    "role": choice.get("message", {}).get("role", "assistant"),
                    "content": choice.get("message", {}).get("content", ""),
                }
                for choice in choices
            ]

    def shutdown(self) -> None:
        """Flush pending events and shutdown."""
        try:
            if self._client is not None:
                self._client.flush()
                logger.info("LLM analytics service shutdown")
        except Exception as e:
            logger.warning("Failed to flush analytics events", error=str(e))
