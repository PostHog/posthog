import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import (
    RAMP_ENDPOINTS,
    TOKEN_SCOPES,
    RampEndpointConfig,
)

RAMP_HOSTS = {
    "production": "https://api.ramp.com",
    "sandbox": "https://demo-api.ramp.com",
}
# Ramp list pages cap at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# ~100 req/min per token; 429s back off.
MAX_RETRY_ATTEMPTS = 5


class RampRetryableError(Exception):
    pass


@dataclasses.dataclass
class RampResumeConfig:
    # Ramp paginates via the self-contained page.next URL.
    next_url: str


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _base_url(environment: str) -> str:
    host = RAMP_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Ramp environment: {environment}")
    return host


def _assert_trusted_url(url: str, environment: str) -> str:
    """Pin a pagination/resume URL to the configured Ramp host before forwarding the bearer token.

    Both the API-derived ``page.next`` value and the Redis-persisted resume URL are
    attacker-influenceable, so we refuse to send credentials anywhere other than the
    environment's own scheme + host."""
    base = urlsplit(_base_url(environment))
    target = urlsplit(url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"Refusing to send Ramp credentials to untrusted URL host: {target.netloc or url!r}")
    return url


def _mint_token(session: requests.Session, environment: str, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a bearer token (~10 day lifetime)."""
    response = session.post(
        f"{_base_url(environment)}/developer/v1/token",
        data={"grant_type": "client_credentials", "scope": TOKEN_SCOPES},
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for Ramp's from_date filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _build_initial_url(
    environment: str,
    config: RampEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if (
        config.incremental_param is not None
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[config.incremental_param] = _format_timestamp(db_incremental_field_last_value)
    return f"{_base_url(environment)}/developer/v1{config.path}?{urlencode(params)}"


def validate_credentials(environment: str, client_id: str, client_secret: str) -> tuple[bool, str | None]:
    """Confirm the developer app credentials are valid by minting a token.

    Distinguishes a genuine credential rejection (4xx) from a transient connectivity problem so the
    user sees an actionable message instead of a blanket "invalid credentials"."""
    try:
        _mint_token(_get_session(client_secret), environment, client_id, client_secret)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403):
            return (
                False,
                "Ramp rejected the credentials. Check the client ID and secret, and that the developer "
                "app has the required scopes.",
            )
        return False, f"Unexpected response from Ramp (status {status})."
    except requests.RequestException as e:
        return False, f"Could not reach Ramp ({e}). Please check your network and selected environment, then retry."
    return True, None


def get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RampResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = RAMP_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    token = _mint_token(session, environment, client_id, client_secret)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = _assert_trusted_url(resume_config.next_url, environment)
        logger.debug(f"Ramp: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(environment, config, should_use_incremental_field, db_incremental_field_last_value)

    @retry(
        retry=retry_if_exception_type((RampRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        nonlocal token
        response = session.get(page_url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last ~10 days; re-mint once defensively if one ever expires
        # mid-sync.
        if response.status_code == 401:
            token = _mint_token(session, environment, client_id, client_secret)
            response = session.get(
                page_url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise RampRetryableError(f"Ramp API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Ramp API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get("data", []) or []

        if items:
            yield items

        next_url = (data.get("page") or {}).get("next")
        if not next_url or not items:
            break

        next_url = _assert_trusted_url(next_url, environment)
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(RampResumeConfig(next_url=next_url))
        url = next_url


def ramp_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RampResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RAMP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Result ordering within a from_date window is not documented, so the
        # pipeline defers incremental watermark commits until a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
    )
