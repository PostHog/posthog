import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.settings import COUPA_ENDPOINTS, PAGE_SIZE

REQUEST_TIMEOUT_SECONDS = 60
# Instance-level limits are unpublished (~25 req/s commonly cited) and Coupa
# sends no Retry-After header; back off on 429/503.
MAX_RETRY_ATTEMPTS = 5


class CoupaRetryableError(Exception):
    pass


@dataclasses.dataclass
class CoupaResumeConfig:
    # Offset of the next unfetched page within the current sync.
    next_offset: int


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't HTTPS.

    Credentials travel as HTTP Basic auth, so plaintext http:// is rejected to
    keep them off the wire in the clear. Bare hosts default to https.
    """
    host = host.strip()
    if not host:
        raise ValueError("Coupa instance URL is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Invalid Coupa instance URL (must be https): {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _get_session(client_secret: str) -> requests.Session:
    # No-redirect session is an SSRF boundary: a user-supplied instance_url must
    # not be able to bounce token/API calls to an internal host via a 3xx.
    return make_tracked_session(
        redact_values=(client_secret,), headers={"Accept": "application/json"}, allow_redirects=False
    )


def _is_scope_error(response: requests.Response) -> bool:
    try:
        return response.json().get("error") == "invalid_scope"
    except Exception:
        return False


def _mint_token(
    session: requests.Session, instance_url: str, client_id: str, client_secret: str, scope: Optional[str]
) -> str:
    """Exchange client credentials for a bearer token (~24h lifetime).

    Falls back to a scope-less request when the instance rejects the
    endpoint-specific scope, in which case the token carries every scope the
    admin granted the OIDC client.
    """
    data: dict[str, str] = {"grant_type": "client_credentials"}
    if scope:
        data["scope"] = scope

    response = session.post(
        f"{normalize_host(instance_url)}/oauth2/token",
        data=data,
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if scope and response.status_code == 400 and _is_scope_error(response):
        return _mint_token(session, instance_url, client_id, client_secret, None)
    response.raise_for_status()
    return response.json()["access_token"]


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _normalize_keys(row: dict[str, Any]) -> dict[str, Any]:
    # Coupa serializes keys with hyphens in some responses (e.g. updated-at);
    # normalize the top level so the updated_at cursor is always present.
    return {key.replace("-", "_"): value for key, value in row.items()}


def validate_credentials(instance_url: str, client_id: str, client_secret: str) -> bool:
    """Confirm the OIDC client credentials are valid by minting a token."""
    try:
        _mint_token(_get_session(client_secret), instance_url, client_id, client_secret, None)
        return True
    except Exception:
        return False


def get_rows(
    instance_url: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoupaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = COUPA_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    base_url = normalize_host(instance_url)
    token = _mint_token(session, instance_url, client_id, client_secret, config.scope)

    @retry(
        retry=retry_if_exception_type((CoupaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(url: str) -> Any:
        nonlocal token
        response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last ~24h; re-mint once if one expires mid-sync.
        if response.status_code == 401:
            token = _mint_token(session, instance_url, client_id, client_secret, config.scope)
            response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code in (429, 503) or response.status_code >= 500:
            raise CoupaRetryableError(f"Coupa API error (retryable): status={response.status_code}, url={url}")

        # The session never follows redirects (SSRF boundary); a 3xx means the
        # instance is pointing us elsewhere, so treat it as a hard upstream error.
        if 300 <= response.status_code < 400:
            raise ValueError(f"Coupa API returned an unexpected redirect: status={response.status_code}, url={url}")

        if not response.ok:
            logger.error("Coupa API error", status=response.status_code, body=response.text[:500], url=url)
            response.raise_for_status()

        return response.json()

    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["updated_at[gt]"] = _format_timestamp(db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.next_offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug("Coupa: resuming from offset", endpoint=endpoint, offset=offset)

    while True:
        url = f"{base_url}/api{config.path}?{urlencode({**params, 'offset': offset})}"
        body = fetch(url)
        rows = [_normalize_keys(row) for row in body if isinstance(row, dict)] if isinstance(body, list) else []

        if rows:
            yield rows

        # Coupa hard-caps pages at 50; a short page means we're done.
        if len(rows) < PAGE_SIZE:
            return

        offset += len(rows)
        # Save state AFTER yielding so a crash re-yields the in-flight page
        # (merge dedupes on primary key).
        resumable_source_manager.save_state(CoupaResumeConfig(next_offset=offset))


def coupa_source(
    instance_url: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoupaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            instance_url=instance_url,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        # Result ordering within an updated_at[gt] window is undocumented, so
        # the pipeline defers incremental watermark commits until a run completes.
        sort_mode="desc",
    )
