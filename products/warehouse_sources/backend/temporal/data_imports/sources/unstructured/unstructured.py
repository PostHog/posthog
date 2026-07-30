"""Transport for the Unstructured Platform API (https://docs.unstructured.io).

The Platform API is plain REST/JSON authenticated with a single `unstructured-api-key` header. Four
list endpoints are synced: `/api/v1/workflows/`, `/api/v1/jobs/`, `/api/v1/sources/`, and
`/api/v1/destinations/`. Each returns a bare JSON array of objects (no envelope). Only `/workflows/`
is paginated (page / page_size); the rest return their whole list in one response.

Incremental sync is intentionally not offered. Only `/workflows/` exposes a server-side timestamp
filter (`created_since`), and even there the resource is mutable config (status / schedule / updated_at
change over time), so filtering on `created_at` would freeze already-synced rows and miss updates. The
jobs / sources / destinations endpoints expose no server-side time filter at all, so a "since" sync
would re-page the full list anyway. These are all low-volume inventory tables, so every stream ships as
a full refresh, which reflects the correct current state each sync. The `created_since` filter and
per-endpoint behavior were verified against the live Platform API OpenAPI spec (version 3.1.1); they
were not smoke-tested against a real key, so a future implementer enabling incremental should confirm
`created_since` actually filters before relying on it. The workflows `sort_by=created_at` below is
similarly taken from the spec (sort_by is a free-form string defaulting to `id`) but unverified against
a live key; if the API rejects it, drop the sort params and fall back to the default `id` ordering.
"""

import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.settings import (
    UNSTRUCTURED_ENDPOINTS,
    UnstructuredEndpointConfig,
)

DEFAULT_BASE_URL = "https://platform.unstructuredapp.io"
# /workflows/ default page_size is 20; pull larger pages to cut round-trips on busy accounts.
WORKFLOWS_PAGE_SIZE = 100
REQUEST_TIMEOUT = 60
HOST_NOT_ALLOWED_ERROR = "This API host is not allowed"


class UnstructuredRetryableError(Exception):
    pass


@dataclasses.dataclass
class UnstructuredResumeConfig:
    # 1-based index of the next /workflows/ page to fetch. Only workflows paginate, so this is the
    # sole piece of resumable state.
    next_page: int


def normalize_base_url(base_url: str | None) -> str:
    """Return the API origin as `https://<host>` with no trailing slash, defaulting to the platform host.

    Accounts can be provisioned with a custom API host, so the origin is user-configurable. The scheme
    is forced to https so a customer-entered `http://` host can't downgrade the key to plaintext.
    Endpoint paths already carry their own leading segment (`/api/v1/...`), so we only need the origin.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        return DEFAULT_BASE_URL
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE).rstrip("/")
    return f"https://{cleaned}" if cleaned else DEFAULT_BASE_URL


def _host_from_base_url(base_url: str | None) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


# Authority chars that let `urlparse` and the HTTP client disagree on where the host ends. A userinfo
# separator or a (raw or percent-encoded) backslash in `https://169.254.169.254\@example.com` makes
# `urlparse` report `example.com` while requests/urllib3 may connect to the internal IP — an SSRF
# bypass of the host check. No legitimate API origin carries these, so reject them outright.
_UNSAFE_URL_CHARS = re.compile(r"[\\@]|%5c|%40", re.IGNORECASE)


def _check_host(base_url: str | None, team_id: int) -> tuple[bool, str | None]:
    raw = (base_url or "").strip()
    if raw and _UNSAFE_URL_CHARS.search(raw):
        return False, HOST_NOT_ALLOWED_ERROR
    return _is_host_safe(_host_from_base_url(base_url), team_id)


def _headers(api_key: str) -> dict[str, str]:
    return {"unstructured-api-key": api_key, "Accept": "application/json"}


def _drop_sensitive_fields(rows: list[dict[str, Any]], drop_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    # Strip credential-bearing fields (e.g. the connector `config` object) before rows are persisted,
    # so secrets never land in a warehouse table readable by anyone with query access.
    if not drop_fields:
        return rows
    return [{k: v for k, v in row.items() if k not in drop_fields} for row in rows]


@retry(
    retry=retry_if_exception_type(
        (
            UnstructuredRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    # The session never follows redirects (SSRF hardening); surface a 30x as an error rather than
    # parsing the redirect body, so a customer-controlled host can't quietly point the sync elsewhere.
    if response.is_redirect or response.is_permanent_redirect:
        logger.error(f"Unstructured API returned an unexpected redirect: status={response.status_code}, url={url}")
        raise requests.HTTPError(
            f"Unexpected redirect from Unstructured API (status={response.status_code})", response=response
        )

    if response.status_code == 429 or response.status_code >= 500:
        raise UnstructuredRetryableError(
            f"Unstructured API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Unstructured API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every list endpoint returns a bare array; guard against an unexpected envelope so a shape change
    # surfaces as an empty sync rather than a crash deep in the pipeline.
    if not isinstance(data, list):
        logger.warning(f"Unstructured API returned a non-list body for {url}; got {type(data).__name__}")
        return []
    return data


def get_rows(
    base_url: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnstructuredResumeConfig],
    team_id: int,
) -> Iterator[list[dict[str, Any]]]:
    # The API host is customer-controlled, so block hosts resolving to private/internal addresses
    # (SSRF) before sending the key. Only enforced on cloud — see `_is_host_safe`.
    host_ok, host_err = _check_host(base_url, team_id)
    if not host_ok:
        raise ValueError(host_err or HOST_NOT_ALLOWED_ERROR)

    config = UNSTRUCTURED_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    url = f"{normalize_base_url(base_url)}{config.path}"
    # One session reused across pages so urllib3 keeps the connection alive between requests.
    # `allow_redirects=False` keeps the credentialed request pinned to the validated host so a
    # customer-controlled host can't 30x the `unstructured-api-key` header off-origin (SSRF). The
    # key is also registered for value-based redaction so it never lands in a captured HTTP sample.
    # HTTP sample capture is disabled for endpoints with drop_fields (sources / destinations): the
    # adapter records the raw response body before `_drop_sensitive_fields` runs, so capturing it
    # would persist the connector `config` secrets into the sample bucket that stripping removes.
    session = make_tracked_session(
        redact_values=(api_key,), allow_redirects=False, capture=not bool(config.drop_fields)
    )

    if not config.paginated:
        rows = _drop_sensitive_fields(_fetch(session, url, headers, None, logger), config.drop_fields)
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume is not None:
        logger.debug(f"Unstructured: resuming {endpoint} from page {page}")

    while True:
        params = {
            "page": page,
            "page_size": WORKFLOWS_PAGE_SIZE,
            # Sort by the stable creation timestamp ascending so rows added mid-sync land on the last
            # page instead of shifting earlier rows across a page boundary (skip/duplicate risk).
            "sort_by": "created_at",
            "sort_direction": "asc",
        }
        rows = _fetch(session, url, headers, params, logger)
        if not rows:
            break

        yield _drop_sensitive_fields(rows, config.drop_fields)

        # A short page is the last page — the API has no explicit "has more" flag, so there is
        # nothing left to resume to and we skip the checkpoint.
        if len(rows) < WORKFLOWS_PAGE_SIZE:
            break

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it; merge/replace dedupes the re-pulled rows on the primary key.
        page += 1
        resumable_source_manager.save_state(UnstructuredResumeConfig(next_page=page))


def unstructured_source(
    base_url: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnstructuredResumeConfig],
    team_id: int,
) -> SourceResponse:
    config: UnstructuredEndpointConfig = UNSTRUCTURED_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(base_url: str | None, api_key: str, team_id: int) -> tuple[bool, str | None]:
    """Cheap probe: list a single workflow. 200 means the key is genuine (an empty account returns []).

    Only checks reachability + auth, not per-endpoint scope; the Platform API key is account-wide, so a
    valid key reaches every list endpoint. Blocks internal/private hosts (SSRF) before sending the key.
    """
    host_ok, host_err = _check_host(base_url, team_id)
    if not host_ok:
        return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{normalize_base_url(base_url)}/api/v1/workflows/"
    try:
        # `allow_redirects=False` stops a validated-but-hostile host from 30x-ing the probe (and the
        # `unstructured-api-key` header) to another origin; a redirect then fails the status check
        # below. The key is registered for value-based redaction so it never lands in a captured sample.
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            url,
            headers=_headers(api_key),
            params={"page": 1, "page_size": 1},
            timeout=REQUEST_TIMEOUT,
        )
        return response.status_code == 200, None if response.status_code == 200 else "Invalid Unstructured API key"
    except Exception:
        return False, "Invalid Unstructured API key"
