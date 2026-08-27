from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, cast

import structlog

from llm_gateway.config import get_settings

if TYPE_CHECKING:
    import httpx
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

DESKTOP_ACCESS_CACHE_PREFIX = "desktop_access"
DesktopAccessReason = Literal["startup_plan", "prepaid_credits"]
DesktopAccessStatus = Literal["allowed", "blocked", "unavailable"]


class _CredentialRejectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesktopAccessDecision:
    status: DesktopAccessStatus
    reason: DesktopAccessReason | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"

    @property
    def resolution_failed(self) -> bool:
        return self.status == "unavailable"


def _redis_key(user_id: int, team_id: int, auth_header: str) -> str:
    credential_fingerprint = hashlib.sha256(auth_header.encode()).hexdigest()
    return f"{DESKTOP_ACCESS_CACHE_PREFIX}:{user_id}:{team_id}:{credential_fingerprint}"


class DesktopAccessResolver:
    def __init__(
        self,
        redis: Redis[bytes] | None,
        http_client: httpx.AsyncClient,
    ):
        self._redis = redis
        self._http = http_client

    async def resolve_access(self, user_id: int, team_id: int, auth_header: str) -> DesktopAccessDecision:
        cached = await self._get_cached(user_id, team_id, auth_header)
        if cached is not None:
            return cached

        return await self._resolve_uncached(user_id, team_id, auth_header)

    async def _resolve_uncached(self, user_id: int, team_id: int, auth_header: str) -> DesktopAccessDecision:
        try:
            decision = await self._fetch_access(team_id, auth_header)
        except _CredentialRejectedError:
            logger.warning("desktop_access_credential_rejected", user_id=user_id, team_id=team_id)
            decision = DesktopAccessDecision(status="blocked")
            await self._set_cached(
                user_id,
                team_id,
                auth_header,
                decision,
                get_settings().desktop_access_denied_cache_ttl,
            )
            return decision
        except Exception:
            logger.warning("desktop_access_fetch_failed", user_id=user_id, team_id=team_id, exc_info=True)
            return DesktopAccessDecision(status="unavailable")

        settings = get_settings()
        ttl = settings.desktop_access_cache_ttl if decision.allowed else settings.desktop_access_denied_cache_ttl
        await self._set_cached(user_id, team_id, auth_header, decision, ttl)
        return decision

    async def _get_cached(self, user_id: int, team_id: int, auth_header: str) -> DesktopAccessDecision | None:
        if not self._redis:
            return None
        try:
            value = await self._redis.get(_redis_key(user_id, team_id, auth_header))
            if value is not None:
                return self._parse_cached_decision(json.loads(value.decode()))
        except Exception:
            logger.debug("desktop_access_cache_read_failed", user_id=user_id, team_id=team_id)
        return None

    async def _set_cached(
        self,
        user_id: int,
        team_id: int,
        auth_header: str,
        decision: DesktopAccessDecision,
        ttl: int,
    ) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(
                _redis_key(user_id, team_id, auth_header),
                json.dumps(asdict(decision)),
                ex=ttl,
            )
        except Exception:
            logger.debug("desktop_access_cache_write_failed", user_id=user_id, team_id=team_id)

    async def _fetch_access(self, team_id: int, auth_header: str) -> DesktopAccessDecision:
        settings = get_settings()
        if not settings.posthog_api_base_url:
            raise RuntimeError("PostHog API base URL is not configured")

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/projects/{team_id}/desktop/access/"
        response = await self._http.get(
            url,
            headers={"Authorization": auth_header},
            timeout=settings.desktop_access_request_timeout,
        )
        if response.status_code in (401, 403):
            raise _CredentialRejectedError(f"Desktop access check returned {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"Desktop access check returned {response.status_code}")

        return self._parse_api_decision(response.json())

    @staticmethod
    def _parse_api_decision(data: object) -> DesktopAccessDecision:
        if not isinstance(data, dict):
            raise ValueError("Desktop access response must be an object")

        allowed = data.get("allowed")
        if not isinstance(allowed, bool) or "reason" not in data:
            raise ValueError("Desktop access response has invalid state")
        status: DesktopAccessStatus = "allowed" if allowed else "blocked"
        return DesktopAccessResolver._validate_decision(status, data["reason"])

    @staticmethod
    def _parse_cached_decision(data: object) -> DesktopAccessDecision:
        if not isinstance(data, dict):
            raise ValueError("Cached Desktop access decision must be an object")
        return DesktopAccessResolver._validate_decision(data.get("status"), data.get("reason"))

    @staticmethod
    def _validate_decision(status: object, reason: object) -> DesktopAccessDecision:
        if status not in ("allowed", "blocked", "unavailable"):
            raise ValueError("Desktop access decision has invalid state")
        if reason not in (None, "startup_plan", "prepaid_credits"):
            raise ValueError("Desktop access decision has an invalid reason")
        if status != "blocked" and reason is not None:
            raise ValueError("Only blocked Desktop access decisions can include a reason")
        return DesktopAccessDecision(
            status=cast(DesktopAccessStatus, status),
            reason=cast(DesktopAccessReason | None, reason),
        )
