"""Scoped ai-gateway tokens that stamphog mints with the worker's ``phs_`` for one LLM job.

Each caller owns its cap, TTL and model pin, because those bound what a leaked token can spend.
The review sandbox and the reviewer routing step both mint here.
"""

from __future__ import annotations

import time
import random
from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from prometheus_client import Counter

from posthog.llm.gateway_client import AIGatewayConfig
from posthog.models import User

# aio_ continues the series the Action-era runs emitted; the engine blob carries the same word.
STAMPHOG_AI_PRODUCT = "aio_stamphog"
MINT_ATTEMPTS = 4
_MINT_TIMEOUT_SECONDS = 3
# Waits of about 1s, 2s and 4s before the retries, plus jitter so a fleet of workers refused at
# once does not come back in step. A Retry-After the gateway sends wins, clamped to the same
# ceiling: the whole mint must stay short against the review activity's start-to-close timeout.
_MINT_BACKOFF_SECONDS = 1.0
_MINT_MAX_BACKOFF_SECONDS = 10.0

AI_GATEWAY_TOKEN_MINTS = Counter(
    "stamphog_ai_gateway_token_mints_total",
    "Scoped-token mint attempts for hosted stamphog reviews",
    labelnames=["result"],
)


class GatewayTokenError(RuntimeError):
    """The gateway minted no usable token."""


def active_user(user_id: int | None) -> User | None:
    """The user a token is minted under, or None when there is no id or the user is missing or inactive."""
    if user_id is None:
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


def gateway_root(gateway: AIGatewayConfig) -> str:
    # The config URL carries the OpenAI /v1 base; the token routes hang off the gateway root.
    return gateway.url.rstrip("/").removesuffix("/v1")


def is_legacy_stamphog_route(url: str) -> bool:
    # The legacy Python gateway resolves the product from the path, so its route ends in the slug.
    return urlparse(url).path.rstrip("/").endswith("/stamphog/v1")


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Seconds the gateway asked the caller to wait, from either Retry-After form; None if unusable."""
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return max(0.0, float(header.strip()))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _mint_backoff_seconds(attempt: int, retry_after: float | None) -> float:
    """What to wait before the next mint attempt: the gateway's own answer, else exponential backoff."""
    if retry_after is not None:
        return min(retry_after, _MINT_MAX_BACKOFF_SECONDS)
    delay = min(_MINT_BACKOFF_SECONDS * 2**attempt, _MINT_MAX_BACKOFF_SECONDS)
    return delay + random.uniform(0, delay / 4)


def revoke_scoped_token(gateway: AIGatewayConfig, token: str) -> str:
    """Best-effort revoke. Returns "ok", or why the revoke did not take; the token then expires."""
    try:
        response = requests.post(
            f"{gateway_root(gateway)}/v1/tokens/revoke",
            json={"token": token},
            headers={"Authorization": f"Bearer {gateway.api_key}"},
            timeout=_MINT_TIMEOUT_SECONDS,
        )
        if not 200 <= response.status_code < 300:
            return f"HTTP {response.status_code}"
        # The gateway answers 200 with revoked=false when no token matched.
        return "ok" if response.json().get("revoked", True) else "no such token"
    except Exception as e:  # noqa: BLE001 — a revoke failure must never mask the caller's outcome
        return type(e).__name__


def mint_scoped_token(
    gateway: AIGatewayConfig,
    *,
    team_id: int,
    user: User,
    cap_usd: str,
    ttl_seconds: int,
    allowed_models: Sequence[str],
) -> str:
    """A ``phe_`` pinned to stamphog's product and the team, acting as ``user``.

    Retries with growing backoff on 429, 5xx and network errors; any other refusal is final. A token
    minted without a requested model pin is revoked and raises. Raises ``GatewayTokenError``.
    """
    body: dict[str, object] = {
        "cap_usd": cap_usd,
        "ttl_seconds": ttl_seconds,
        "product": STAMPHOG_AI_PRODUCT,
        "obo": str(team_id),
    }
    if user.distinct_id:
        body["user"] = user.distinct_id
    if allowed_models:
        body["allowed_models"] = list(allowed_models)
    mint_url = f"{gateway_root(gateway)}/v1/tokens"
    last_error = ""
    for attempt in range(MINT_ATTEMPTS):
        retry_after: float | None = None
        try:
            response = requests.post(
                mint_url,
                json=body,
                headers={"Authorization": f"Bearer {gateway.api_key}"},
                timeout=_MINT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            last_error = type(e).__name__
        else:
            if 200 <= response.status_code < 300:
                try:
                    payload = response.json()
                    token = payload["token"]
                except (ValueError, TypeError, KeyError):
                    payload, token = {}, None
                if token:
                    if allowed_models and not payload.get("allowed_models"):
                        # A gateway that predates the pin field ignores it and mints an unpinned token.
                        revoke_scoped_token(gateway, token)
                        AI_GATEWAY_TOKEN_MINTS.labels(result="unpinned").inc()
                        raise GatewayTokenError(
                            "The gateway minted the token without the required model pin; "
                            "the gateway must support allowed_models before a model list is set"
                        )
                    AI_GATEWAY_TOKEN_MINTS.labels(result="ok").inc()
                    return token
                last_error = "mint response carried no token"
                break
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                retry_after = _retry_after_seconds(response)
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                break
        if attempt < MINT_ATTEMPTS - 1:
            time.sleep(_mint_backoff_seconds(attempt, retry_after))
    AI_GATEWAY_TOKEN_MINTS.labels(result="error").inc()
    raise GatewayTokenError(f"Could not mint the scoped gateway token ({last_error})")
