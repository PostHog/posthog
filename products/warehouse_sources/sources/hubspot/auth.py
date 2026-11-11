from collections.abc import Mapping
from dataclasses import field
from http import HTTPStatus
from typing import cast

from django.db import transaction

import requests
import structlog
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ExternalDataSource,
    LegacyOAuthGrantUnusable,
    credentials_service,
    frozen,
    make_tracked_session,
    redact_request_urls,
)
from products.warehouse_sources.sources.sdk.internals import SourceInputsStore

logger = structlog.get_logger(__name__)

# Cap how long a single Retry-After can stall the token refresh, so a misbehaving
# header can't pin the activity open.
MAX_RETRY_AFTER_SECONDS = 60
# Stateless backoff used when a 429 carries no Retry-After hint (or for 5xx).
_FALLBACK_WAIT = wait_exponential_jitter(initial=1, max=30)


class HubspotRetryableError(Exception):
    """Transient HubSpot API failure (429 rate limit, 5xx, or portal migration) that should be retried with backoff."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        # Seconds HubSpot asked us to wait (from a 429 Retry-After), if any.
        self.retry_after = retry_after


class HubspotTokenRefreshError(Exception):
    """HubSpot rejected the token refresh."""

    def __init__(self, message: str, grant_rejected: bool = False) -> None:
        super().__init__(message)
        # HubSpot said the refresh token itself is invalid, expired or revoked. Any other refusal, such as one
        # of PostHog's app credentials, says nothing about the grant.
        self.grant_rejected = grant_rejected


def _is_retryable_status(status_code: int) -> bool:
    """Transient HubSpot statuses that warrant a backoff-and-retry rather than failing the sync.

    408, 429 and 5xx are the usual transient signals. Unrecognised 4xx codes (e.g. the
    non-standard 477 HubSpot's edge has been observed returning during brief incidents) aren't
    actionable client errors, so treat any unknown 4xx as transient too instead of crashing the
    import on it.
    """
    if status_code in (408, 429) or status_code >= 500:
        return True
    if 400 <= status_code < 500:
        try:
            HTTPStatus(status_code)
        except ValueError:
            return True
    return False


@frozen
class HubspotLegacyGrant:
    external_id: str
    config: Mapping[str, object]
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


def _parse_retry_after(res: requests.Response) -> float | None:
    """HubSpot sends Retry-After as delta-seconds on 429s; ignore other (non-numeric) forms."""
    raw = res.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Honor a 429's Retry-After when present, else fall back to jittered backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, HubspotRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _FALLBACK_WAIT(retry_state)


def _error_message_from_response(res: requests.Response) -> str:
    """Best-effort extraction of HubSpot's error message, tolerant of non-JSON or message-less bodies."""
    try:
        return res.json()["message"]
    except Exception:
        return res.text


def _is_grant_rejection(res: requests.Response) -> bool:
    """HubSpot's OAuth error body names a rejected refresh token with `invalid_grant` (RFC 6749), or with its own
    older `BAD_REFRESH_TOKEN` status. `BAD_HUB` (with `access_denied`) means the portal of the grant was deleted or
    disconnected, which `posthog/models/integration/refresh_tracking.py` also treats as a dead grant."""
    try:
        body = res.json()
    except Exception:
        return False
    if not isinstance(body, Mapping):
        return False
    return body.get("error") == "invalid_grant" or body.get("status") in ("BAD_REFRESH_TOKEN", "BAD_HUB")


def _hubspot_app_credentials() -> dict[str, str]:
    """PostHog's own HubSpot app id and secret, as the token endpoint wants them named."""
    resolved = credentials_service.get_secrets(["HUBSPOT_APP_CLIENT_ID", "HUBSPOT_APP_CLIENT_SECRET"])
    return {
        "client_id": resolved["HUBSPOT_APP_CLIENT_ID"],
        "client_secret": resolved["HUBSPOT_APP_CLIENT_SECRET"],
    }


@retry(
    # A 429/5xx from HubSpot's OAuth token endpoint is transient. The data-fetch paths already
    # back off and retry on HubspotRetryableError; this refresh is also reached at source-setup
    # time (and from helpers.fetch_data), where no surrounding retry exists — so back off here too
    # instead of failing the whole sync on a momentary rate limit.
    retry=retry_if_exception_type((HubspotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=_wait_strategy,
    reraise=True,
)
def _hubspot_refresh_token_payload(refresh_token: str) -> Mapping[str, object]:
    res = make_tracked_session().post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "refresh_token",
            **_hubspot_app_credentials(),
            "refresh_token": refresh_token,
        },
    )

    if res.status_code != 200:
        err_message = _error_message_from_response(res)
        # A 429 (rate limit) or 5xx from the OAuth token endpoint is transient. Surface it as a
        # retryable error so the calling fetch loop backs off and retries instead of failing the
        # whole sync on a momentary rate limit.
        if res.status_code == 429 or res.status_code >= 500:
            retry_after = _parse_retry_after(res) if res.status_code == 429 else None
            raise HubspotRetryableError(err_message, retry_after=retry_after)
        # HubSpot briefly returns this (on a non-5xx) while a portal is migrated between data
        # centers; the portal becomes reachable again once the migration finishes, so back off
        # and retry rather than failing the sync (and disabling the schema) on a transient state.
        if "migration in progress" in err_message.lower():
            raise HubspotRetryableError(err_message)
        raise HubspotTokenRefreshError(err_message, grant_rejected=_is_grant_rejection(res))

    payload = res.json()
    if not isinstance(payload, Mapping):
        raise HubspotTokenRefreshError("HubSpot returned an invalid token response")
    return payload


def hubspot_refresh_access_token(refresh_token: str, source_id: str | None = None) -> str:
    access_token = cast(str, _hubspot_refresh_token_payload(refresh_token)["access_token"])

    if source_id:
        _update_source_job_inputs(source_id, access_token)

    return access_token


def hubspot_exchange_legacy_grant(refresh_token: str) -> HubspotLegacyGrant:
    if not refresh_token:
        raise LegacyOAuthGrantUnusable("The legacy refresh token is missing")
    try:
        payload = _hubspot_refresh_token_payload(refresh_token)
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise LegacyOAuthGrantUnusable("HubSpot returned no access token")
        rotated_refresh_token = payload.get("refresh_token") or refresh_token
        if not isinstance(rotated_refresh_token, str):
            raise LegacyOAuthGrantUnusable("HubSpot returned an invalid refresh token")
        # The token is part of the URL, so transport logs must hide it.
        with redact_request_urls():
            res = make_tracked_session().get(
                "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token,
            )
        if _is_retryable_status(res.status_code):
            raise HubspotRetryableError("HubSpot could not return token information")
        if res.status_code != 200:
            raise LegacyOAuthGrantUnusable("HubSpot rejected the token information request")
        token_info = res.json()
        if not isinstance(token_info, Mapping):
            raise HubspotRetryableError("HubSpot returned invalid token information")
        hub_id = token_info.get("hub_id")
        if isinstance(hub_id, bool) or not isinstance(hub_id, (int, str)) or not hub_id:
            raise LegacyOAuthGrantUnusable("HubSpot returned no hub id")
        config = {
            key: value for key, value in payload.items() if key not in {"access_token", "refresh_token", "id_token"}
        }
        config.update({key: token_info.get(key) for key in ("hub_id", "hub_domain", "user", "user_id", "scopes")})
        return HubspotLegacyGrant(
            external_id=str(hub_id),
            config=config,
            access_token=access_token,
            refresh_token=rotated_refresh_token,
        )
    except HubspotTokenRefreshError as e:
        # Only a confirmed rejection of the refresh token lets the cleanup clear the tokens. A timeout, a malformed
        # body or a refusal of PostHog's app credentials says nothing about the grant.
        if not e.grant_rejected:
            raise HubspotRetryableError("The legacy HubSpot grant could not be checked") from None
        raise LegacyOAuthGrantUnusable("The legacy HubSpot grant could not be exchanged") from None
    except (HubspotRetryableError, requests.RequestException, ValueError):
        raise HubspotRetryableError("The legacy HubSpot grant could not be checked") from None


def hubspot_access_token_is_valid(access_token: str) -> bool:
    res = make_tracked_session().get(
        "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token,
    )
    return res.status_code == 200


def _update_source_job_inputs(source_id: str, access_token: str) -> None:
    try:
        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team -- pre-existing, file moved out of temporal/; source_id comes from the sync job, not a request
            source = ExternalDataSource.objects.select_related(None).select_for_update(of=("self",)).get(id=source_id)
            job_inputs = SourceInputsStore.load_stored(source)

            # Only persist for legacy sources that store credentials directly in job_inputs
            if "hubspot_integration_id" in job_inputs:
                return

            # Not `save`: a token refresh never changes the row that the source uses, so it leaves the reference column alone.
            SourceInputsStore.update_oauth_inputs(source, {"hubspot_secret_key": access_token}, extra_update_fields=())
    except Exception:
        logger.exception("Failed to update job_inputs after HubSpot token refresh", source_id=source_id)


def get_hubspot_access_token_from_code(code: str, redirect_uri: str) -> tuple[str, str]:
    res = make_tracked_session().post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "authorization_code",
            **_hubspot_app_credentials(),
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["message"]
        raise Exception(err_message)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
