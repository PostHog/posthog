from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Protocol

import structlog
from posthoganalytics import Posthog

from llm_gateway.auth.models import resolve_distinct_id
from llm_gateway.rate_limiting.throttles import ThrottleContext, ThrottleResult

logger = structlog.get_logger(__name__)

DENIAL_EVENT_NAME = "llm_gateway_rate_limit_denied"


class DenialCapturer(Protocol):
    def __call__(self, context: ThrottleContext, result: ThrottleResult, scope: str, /) -> None: ...


class PosthogDenialCapturer:
    def __init__(self, api_key: str, host: str) -> None:
        self._api_key = api_key
        self._host = host

    def __call__(self, context: ThrottleContext, result: ThrottleResult, scope: str) -> None:
        auth_user = context.user
        distinct_id = resolve_distinct_id(auth_user, context.end_user_id)

        properties: dict[str, Any] = {
            "product": context.product,
            "scope": scope,
            "status_code": result.status_code,
            "detail": result.detail,
            "retry_after_seconds": result.retry_after,
            "used_usd": result.used_usd,
            "limit_usd": result.limit_usd,
            "auth_method": auth_user.auth_method,
            "application_id": auth_user.application_id,
            "gateway_user_id": auth_user.user_id,
        }
        if auth_user.team_id is not None:
            properties["team_id"] = auth_user.team_id

        capture_kwargs: dict[str, Any] = {
            "distinct_id": distinct_id,
            "event": DENIAL_EVENT_NAME,
            "properties": properties,
        }
        if auth_user.team_id is not None:
            capture_kwargs["groups"] = {"project": auth_user.team_id}

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. called from sync test); fire inline.
            self._capture_sync(**capture_kwargs)
            return
        loop.run_in_executor(None, partial(self._capture_sync, **capture_kwargs))

    def _capture_sync(self, **capture_kwargs: Any) -> None:
        client: Any | None = None
        try:
            client = Posthog(
                self._api_key,
                host=self._host,
                sync_mode=True,
                enable_local_evaluation=False,
            )
            client.capture(**capture_kwargs)
        except Exception:
            logger.exception("denial_event_capture_failed")
        finally:
            if client is not None:
                client.shutdown()
