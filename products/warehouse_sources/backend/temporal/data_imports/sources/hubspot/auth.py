from django.conf import settings

import requests
import structlog
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

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
def hubspot_refresh_access_token(refresh_token: str, source_id: str | None = None) -> str:
    res = make_tracked_session().post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
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
        raise Exception(err_message)

    access_token = res.json()["access_token"]

    if source_id:
        _update_source_job_inputs(source_id, access_token)

    return access_token


def hubspot_access_token_is_valid(access_token: str) -> bool:
    res = make_tracked_session().get(
        "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token,
    )
    return res.status_code == 200


def _update_source_job_inputs(source_id: str, access_token: str) -> None:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

    try:
        source = ExternalDataSource.objects.get(id=source_id)
        job_inputs = source.job_inputs or {}

        # Only persist for legacy sources that store credentials directly in job_inputs
        if "hubspot_integration_id" in job_inputs:
            return

        job_inputs["hubspot_secret_key"] = access_token
        source.job_inputs = job_inputs
        source.save(update_fields=["job_inputs"])
    except Exception:
        logger.exception("Failed to update job_inputs after HubSpot token refresh", source_id=source_id)


def get_hubspot_access_token_from_code(code: str, redirect_uri: str) -> tuple[str, str]:
    res = make_tracked_session().post(
        "https://api.hubapi.com/oauth/v1/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.HUBSPOT_APP_CLIENT_ID,
            "client_secret": settings.HUBSPOT_APP_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    if res.status_code != 200:
        err_message = res.json()["message"]
        raise Exception(err_message)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
