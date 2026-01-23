from typing import Any

import structlog
from litellm.integrations.custom_logger import CustomLogger

from llm_gateway.metrics.prometheus import CALLBACK_ERRORS, CALLBACK_SUCCESS
from llm_gateway.observability import capture_exception
from llm_gateway.request_context import get_auth_user

logger = structlog.get_logger(__name__)


class InstrumentedCallback(CustomLogger):
    """Base callback with automatic metrics and error handling."""

    callback_name: str = "unknown"

    def _extract_end_user_id(self, kwargs: dict[str, Any]) -> str | None:
        """Extract end_user_id from request data.

        - OAuth: returns user_id (token holder)
        - Personal API key: returns 'user' param from request (end_user)
        - Anthropic: falls back to metadata.user_id
        """
        auth_user = get_auth_user()
        if auth_user and auth_user.auth_method == "oauth_access_token":
            return str(auth_user.user_id)

        standard_logging_object = kwargs.get("standard_logging_object", {})
        if end_user := standard_logging_object.get("end_user"):
            return end_user

        litellm_params = kwargs.get("litellm_params") or {}
        metadata = litellm_params.get("metadata") or {}
        if user_id := metadata.get("user_id"):
            return user_id

        return None

    async def async_log_success_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float
    ) -> None:
        try:
            end_user_id = self._extract_end_user_id(kwargs)
            await self._on_success(kwargs, response_obj, start_time, end_time, end_user_id)
            CALLBACK_SUCCESS.labels(callback=self.callback_name).inc()
        except Exception as e:
            CALLBACK_ERRORS.labels(callback=self.callback_name, error_type=type(e).__name__).inc()
            capture_exception(e, {"callback": self.callback_name, "event": "success"})
            logger.warning("callback_error", callback=self.callback_name, event_type="success", error=str(e))

    async def async_log_failure_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float
    ) -> None:
        try:
            end_user_id = self._extract_end_user_id(kwargs)
            await self._on_failure(kwargs, response_obj, start_time, end_time, end_user_id)
            CALLBACK_SUCCESS.labels(callback=self.callback_name).inc()
        except Exception as e:
            CALLBACK_ERRORS.labels(callback=self.callback_name, error_type=type(e).__name__).inc()
            capture_exception(e, {"callback": self.callback_name, "event": "failure"})
            logger.warning("callback_error", callback=self.callback_name, event_type="failure", error=str(e))

    async def _on_success(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        """Override in subclass to handle success events."""
        pass

    async def _on_failure(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float, end_user_id: str | None
    ) -> None:
        """Override in subclass to handle failure events."""
        pass
