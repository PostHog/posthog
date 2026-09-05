from collections.abc import Iterator
from typing import Any, Optional, cast
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.settings import OUTREACH_ENDPOINTS

OUTREACH_API_ORIGIN = "https://api.outreach.io"
OUTREACH_BASE_URL = f"{OUTREACH_API_ORIGIN}/api/v2"
OUTREACH_TOKEN_URL = f"{OUTREACH_API_ORIGIN}/oauth/token"
# Outreach's max page[size]/page[limit] across both its cursor and (deprecated) offset pagination
# modes is 1000; 500 keeps individual response bodies modest.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

JSON_API_HEADERS = {"Content-Type": "application/vnd.api+json", "Accept": "application/vnd.api+json"}


class OutreachRetryableError(Exception):
    pass


def _assert_same_origin(url: str) -> str:
    """Reject pagination URLs that point anywhere but the Outreach API host.

    Every request carries the OAuth access token in an `Authorization` header. `links.next` comes
    off the response body, and the resumed URL is whatever we persisted from a previous run, so a
    poisoned value pointing at an attacker-controlled host would hand them the token. Pin both to
    the exact `https://api.outreach.io` origin before following or storing them.
    """
    parsed = urlparse(url)
    if f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" != OUTREACH_API_ORIGIN:
        raise ValueError(f"Refusing to follow off-origin Outreach pagination URL: {url}")

    return url


@frozen
class OutreachResumeConfig:
    next_url: Optional[str] = None


def _get_session(client_secret: str, refresh_token: str) -> requests.Session:
    # capture=False keeps requests metered and logged but excludes their bodies from HTTP sample
    # capture. Outreach is a CRM: rows carry prospect names, emails, phone numbers, employer and
    # job-title fields, mailing subjects/bodies, and arbitrary tenant-defined custom attributes that
    # the name-based scrubbers can't reliably recognise. Those bodies must not land in the shared
    # sample store, which sits outside the warehouse's own access controls. The same session runs
    # the OAuth token exchange, so the refresh-token/client-secret payloads are excluded too.
    return make_tracked_session(headers=JSON_API_HEADERS, redact_values=(client_secret, refresh_token), capture=False)


def _mint_token(session: requests.Session, client_id: str, client_secret: str, refresh_token: str) -> str:
    response = session.post(
        OUTREACH_TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return cast(str, response.json()["access_token"])


def validate_credentials(client_id: str, client_secret: str, refresh_token: str) -> bool:
    """Confirm the OAuth app credentials are valid by minting a token and probing a cheap endpoint."""
    try:
        session = _get_session(client_secret, refresh_token)
        token = _mint_token(session, client_id, client_secret, refresh_token)
        response = session.get(
            f"{OUTREACH_BASE_URL}/users",
            headers={"Authorization": f"Bearer {token}"},
            params={"page[size]": "1", "count": "false"},
            timeout=15,
        )
        # A 403 still proves the token is genuine; the app may just lack the users scope.
        return response.status_code in (200, 403)
    except Exception:
        return False


def _format_datetime(value: Any) -> str:
    """Render an incremental cursor value as the millisecond-precision ISO 8601 instant Outreach expects."""
    utc_dt = coerce_datetime_to_utc(value)
    if utc_dt is None:
        return str(value)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten one JSON:API resource object into a single flat row.

    `attributes` is merged into the root. Each to-one `relationships` entry (its `data` is a
    single `{type, id}` resource identifier) becomes a `<relationship>Id` column, e.g. a prospect's
    `account` relationship becomes `accountId`. To-many relationships (`data` is a list, e.g. a
    prospect's `calls`) carry no useful scalar value here and are dropped, since the row on the
    other side of that relationship already references this one.
    """
    row = dict(item)
    attributes = row.pop("attributes", None) or {}
    row.update(attributes)

    relationships = row.pop("relationships", None) or {}
    for relationship_name, relationship in relationships.items():
        data = relationship.get("data") if isinstance(relationship, dict) else None
        if isinstance(data, dict) and "id" in data:
            row[f"{relationship_name}Id"] = data["id"]

    row.pop("links", None)
    return row


def get_rows(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OutreachResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = OUTREACH_ENDPOINTS[endpoint]
    session = _get_session(client_secret, refresh_token)
    token = _mint_token(session, client_id, client_secret, refresh_token)

    @retry(
        retry=retry_if_exception_type((OutreachRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def fetch(url: str, params: Optional[dict[str, Any]]) -> dict[str, Any]:
        nonlocal token
        headers = {**JSON_API_HEADERS, "Authorization": f"Bearer {token}"}
        response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        # Access tokens last ~2h; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret, refresh_token)
            headers = {**JSON_API_HEADERS, "Authorization": f"Bearer {token}"}
            response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OutreachRetryableError(f"Outreach API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Outreach API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return cast(dict[str, Any], response.json())

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.next_url:
        url = _assert_same_origin(resume.next_url)
        params: Optional[dict[str, Any]] = None
        logger.debug(f"Outreach: resuming {endpoint} from {url}")
    else:
        url = f"{OUTREACH_BASE_URL}{config.path}"
        # Sort ascending on the same field the incremental cursor tracks, so pagination order
        # matches SourceResponse.sort_mode="asc" and the watermark advances correctly.
        params = {"page[size]": PAGE_SIZE, "count": "false", "sort": "updatedAt"}
        if should_use_incremental_field and db_incremental_field_last_value:
            # `newFilterSyntax=true` is required by Outreach to use the [gte]/[lte] bracket
            # operators; without it the API falls back to its legacy dot-range filter syntax.
            params["newFilterSyntax"] = "true"
            params["filter[updatedAt][gte]"] = _format_datetime(db_incremental_field_last_value)

    while True:
        data = fetch(url, params)
        params = None  # links.next is an absolute URL that already embeds every original param

        items = data.get("data") or []
        if items:
            yield [_flatten_item(item) for item in items]

        next_url = data.get("links", {}).get("next")
        if not next_url:
            break

        next_url = _assert_same_origin(next_url)
        # Save after yielding, not before, so a crash re-yields (and merge-dedupes) the last
        # page instead of skipping it.
        resumable_source_manager.save_state(OutreachResumeConfig(next_url=next_url))
        url = next_url

    resumable_source_manager.clear_state()


def outreach_source(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OutreachResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OUTREACH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )
