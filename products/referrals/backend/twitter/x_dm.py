"""Send 1:1 DMs to Twitter/X users via OAuth 2.0.

Credentials come from env vars (``X_CLIENT_ID``, ``X_CLIENT_SECRET``, ``X_REFRESH_TOKEN``).
The refresh token rotates on every refresh; we cache the latest value in Django cache
and fall back to the env var if the cache is empty. Manual recovery: regenerate a refresh
token via the ``.scratch/x_oauth2_x`` interactive helper and update the env var.

Module is async-only and stateless — designed to be invoked from inside the Temporal
activity in ``products/referrals/backend/temporal/activities.py``.
"""

from __future__ import annotations

import os
import base64
import logging
from dataclasses import dataclass

from django.core.cache import cache

import httpx

logger = logging.getLogger(__name__)

_X_API_BASE = "https://api.twitter.com"
_REFRESH_TOKEN_CACHE_KEY = "referrals:x_dm:refresh_token"
# Refresh tokens are valid for ~6 months on X; bound the cache TTL well inside that.
_REFRESH_TOKEN_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


@dataclass(frozen=True)
class XDmCredentials:
    client_id: str
    client_secret: str
    refresh_token: str


def _read_credentials() -> tuple[XDmCredentials, str]:
    """Load X OAuth credentials; prefer the cached refresh_token over the env var.

    Returns (credentials, source) where source is "cache" or "env" so callers can
    diagnose stale-cache surprises.
    """
    client_id = os.environ.get("X_CLIENT_ID", "").strip()
    client_secret = os.environ.get("X_CLIENT_SECRET", "").strip()
    env_refresh_token = os.environ.get("X_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not env_refresh_token:
        raise ValueError(
            "X DM credentials missing — set X_CLIENT_ID, X_CLIENT_SECRET, and X_REFRESH_TOKEN in the worker environment"
        )
    cached = cache.get(_REFRESH_TOKEN_CACHE_KEY)
    if isinstance(cached, str) and cached.strip():
        refresh_token = cached.strip()
        source = "cache"
    else:
        refresh_token = env_refresh_token
        source = "env"
    return XDmCredentials(client_id=client_id, client_secret=client_secret, refresh_token=refresh_token), source


def reset_refresh_token_cache() -> None:
    """Clear the cached rotated refresh token; the next run will use the env var."""
    cache.delete(_REFRESH_TOKEN_CACHE_KEY)


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    return f"Basic {token}"


async def _refresh_access_token(client: httpx.AsyncClient, creds: XDmCredentials) -> str:
    """Exchange refresh_token for a fresh access_token; persist the rotated refresh_token."""
    res = await client.post(
        f"{_X_API_BASE}/2/oauth2/token",
        headers={
            "Authorization": _basic_auth_header(creds.client_id, creds.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": creds.refresh_token},
    )
    if res.status_code != 200:
        body_excerpt = res.text[:500]
        logger.warning("x_dm: refresh failed status=%d body=%s", res.status_code, body_excerpt)
        raise RuntimeError(f"x_dm: refresh_token exchange failed status={res.status_code} body={body_excerpt}")
    body = res.json()
    access_token = body.get("access_token")
    new_refresh_token = body.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"x_dm: refresh response missing access_token: {body!r}")
    if isinstance(new_refresh_token, str) and new_refresh_token and new_refresh_token != creds.refresh_token:
        # Rotation: persist for the next hourly run. Lost on cache eviction → env var is the recovery.
        cache.set(_REFRESH_TOKEN_CACHE_KEY, new_refresh_token, timeout=_REFRESH_TOKEN_CACHE_TTL_SECONDS)
        logger.info("x_dm: refresh_token rotated and cached")
    return access_token


async def _lookup_user_id_by_username(client: httpx.AsyncClient, access_token: str, username: str) -> str | None:
    """Resolve a handle to a numeric user id. Returns None on 404."""
    res = await client.get(
        f"{_X_API_BASE}/2/users/by/username/{username}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if res.status_code == 404:
        return None
    if res.status_code != 200:
        logger.warning(
            "x_dm: user lookup failed username=%s status=%d body=%s",
            username,
            res.status_code,
            res.text[:200],
        )
        res.raise_for_status()
    data = res.json().get("data") or {}
    user_id = data.get("id")
    return user_id if isinstance(user_id, str) and user_id else None


async def _send_dm(client: httpx.AsyncClient, access_token: str, recipient_user_id: str, text: str) -> tuple[bool, str]:
    """POST a 1:1 DM. Returns (ok, status_detail)."""
    res = await client.post(
        f"{_X_API_BASE}/2/dm_conversations/with/{recipient_user_id}/messages",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"text": text},
    )
    if res.status_code in (200, 201):
        return True, f"ok status={res.status_code}"
    return False, f"status={res.status_code} body={res.text[:200]}"


@dataclass(frozen=True)
class DmDispatchSummary:
    sent: int
    failed_lookup: int
    failed_send: int


async def send_referral_dms(handle_to_text: list[tuple[str, str]]) -> DmDispatchSummary:
    """Send one DM per (handle, text) pair.

    Refreshes the access token once up front, then loops the candidates. Per-recipient
    failures are caught and logged so a single bad handle does not skip the rest. If the
    token refresh itself fails, the exception bubbles up — at that point no DMs have been
    sent yet so retrying the activity is safe.
    """
    if not handle_to_text:
        return DmDispatchSummary(sent=0, failed_lookup=0, failed_send=0)

    creds, source = _read_credentials()
    logger.info("x_dm: using refresh_token from %s (len=%d)", source, len(creds.refresh_token))
    sent = 0
    failed_lookup = 0
    failed_send = 0
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        access_token = await _refresh_access_token(client, creds)
        for handle, text in handle_to_text:
            try:
                user_id = await _lookup_user_id_by_username(client, access_token, handle)
                if user_id is None:
                    logger.warning("x_dm: handle not found, skipping handle=%s", handle)
                    failed_lookup += 1
                    continue
                ok, detail = await _send_dm(client, access_token, user_id, text)
                if ok:
                    sent += 1
                    logger.info("x_dm: dm sent handle=%s user_id=%s", handle, user_id)
                else:
                    failed_send += 1
                    logger.warning(
                        "x_dm: dm send failed handle=%s user_id=%s detail=%s",
                        handle,
                        user_id,
                        detail,
                    )
            except Exception:
                failed_send += 1
                logger.exception("x_dm: unexpected error sending dm handle=%s", handle)
    return DmDispatchSummary(sent=sent, failed_lookup=failed_lookup, failed_send=failed_send)
