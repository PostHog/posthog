from typing import Any

import structlog
from litellm.integrations.custom_logger import CustomLogger

from llm_gateway.metrics.prometheus import CALLBACK_ERRORS, CALLBACK_SUCCESS
from llm_gateway.observability import capture_exception

logger = structlog.get_logger(__name__)


class InstrumentedCallback(CustomLogger):
    """Base callback with automatic metrics and error handling."""

    callback_name: str = "unknown"

    async def async_log_success_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float
    ) -> None:
        try:
            await self._on_success(kwargs, response_obj, start_time, end_time)
            CALLBACK_SUCCESS.labels(callback=self.callback_name).inc()
        except Exception as e:
            CALLBACK_ERRORS.labels(callback=self.callback_name, error_type=type(e).__name__).inc()
            capture_exception(e, {"callback": self.callback_name, "event": "success"})
            logger.warning("callback_error", callback=self.callback_name, event_type="success", error=str(e))

    async def async_log_failure_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float
    ) -> None:
        try:
            await self._on_failure(kwargs, response_obj, start_time, end_time)
            CALLBACK_SUCCESS.labels(callback=self.callback_name).inc()
        except Exception as e:
            CALLBACK_ERRORS.labels(callback=self.callback_name, error_type=type(e).__name__).inc()
            capture_exception(e, {"callback": self.callback_name, "event": "failure"})
            logger.warning("callback_error", callback=self.callback_name, event_type="failure", error=str(e))

    async def _on_success(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        """Override in subclass to handle success events."""
        pass

    async def _on_failure(self, kwargs: dict[str, Any], response_obj: Any, start_time: float, end_time: float) -> None:
        """Override in subclass to handle failure events."""
        pass
