"""Netlify transport layer.

Netlify's REST API (https://open-api.netlify.com/) is a clean JSON surface behind a personal
access token sent as a Bearer header. Lists use 1-based `page`/`per_page` (max 100) pagination with
RFC-5988 `Link` headers (rel="next") for traversal.

No list endpoint accepts a server-side timestamp filter, so every table is full refresh — there is
no reliable server-side cursor to sync incrementally on. The source is still resumable: top-level
lists checkpoint the next page URL, and fan-out tables checkpoint the current parent page so a
resumed run re-fans that page (merge dedupes on the primary key).

Site-scoped tables (deploys, builds, forms, submissions) and account-scoped tables (members) are
fan-outs: we walk the parent list and call the child endpoint once per parent, injecting the parent
identifier onto each child row so the composite primary key stays unique table-wide.
"""

import re
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import (
    NETLIFY_ENDPOINTS,
    NetlifyEndpointConfig,
)

NETLIFY_BASE_URL = "https://api.netlify.com/api/v1"
_NETLIFY_PARSED_BASE = urlparse(NETLIFY_BASE_URL)


@dataclasses.dataclass
class NetlifyResumeConfig:
    # Next URL to fetch. For top-level tables it's the next page URL; for fan-out tables it's the
    # current parent page URL (resume re-fans that page, merge dedupes on the primary key).
    next_url: str | None = None


class NetlifyRetryableError(Exception):
    pass


class NetlifyUntrustedURLError(Exception):
    """Raised when a next-page/resume URL points off the Netlify API host. We attach the account
    token to every request, so following an off-host URL would leak it; refuse instead."""


class NetlifyPageCapExceededError(Exception):
    """Raised when a fan-out parent exceeds the per-parent page cap. Failing loudly beats silently
    writing an incomplete full-refresh table that later runs would keep re-truncating."""


def _validate_netlify_url(url: str) -> str:
    """Reject a URL whose scheme or host differs from NETLIFY_BASE_URL.

    The next-page URL comes from a remote `Link` header (and from persisted resume state), and we
    send the account token with it. Pinning the scheme and host stops a tampered link from
    forwarding the token to an attacker-controlled server.
    """
    parsed = urlparse(url)
    if parsed.scheme != _NETLIFY_PARSED_BASE.scheme or parsed.netloc != _NETLIFY_PARSED_BASE.netloc:
        raise NetlifyUntrustedURLError(f"Netlify: refusing to follow off-host URL: {url}")
    return url


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
        "User-Agent": "PostHog",
    }


def _parse_next_url(link_header: str, base_url: str = NETLIFY_BASE_URL) -> str | None:
    """Return the URL with rel="next" from Netlify's RFC-5988 Link header, if any.

    Relative links are resolved against the request URL, and the result is pinned to the Netlify
    host so a tampered link can't redirect the token off-host.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return _validate_netlify_url(urljoin(base_url, match.group(1)))
    return None


@retry(
    retry=retry_if_exception_type(
        (
            NetlifyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            # A chunked response the server truncates mid-body surfaces as ChunkedEncodingError
            # (a direct RequestException subclass); it's transient, so a fresh GET re-fetches the page.
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # Netlify rate-limits at 500 req/min and returns 429; transient 5xx are retryable too. We don't
    # have a token to confirm the exact Retry-After header shape, so fall back to exponential backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise NetlifyRetryableError(f"Netlify API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Netlify API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _build_url(path: str, page_size: int | None) -> str:
    url = f"{NETLIFY_BASE_URL}{path}"
    if page_size is not None:
        return f"{url}?{urlencode({'per_page': page_size})}"
    return url


def _iter_pages(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    max_pages: int | None = None,
    page_cap_context: dict[str, Any] | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str]]:
    """Yield (items, page_url) for each page of a Netlify list, following the Link header.

    Netlify list responses are top-level JSON arrays. When `max_pages` is set and there are still
    more pages, it raises rather than truncating: a silently short full-refresh table would stay
    incomplete on every later run, so we surface the cap as a hard failure instead.
    """
    page_count = 0
    while True:
        response = _fetch_page(session, url, headers, logger)
        data = response.json()
        if not isinstance(data, list) or not data:
            return
        next_url = _parse_next_url(response.headers.get("Link", ""), url)
        yield data, url
        page_count += 1
        if not next_url:
            return
        if max_pages is not None and page_count >= max_pages:
            logger.error(
                "Netlify: per-parent page cap reached; failing to avoid an incomplete table",
                max_pages=max_pages,
                **(page_cap_context or {}),
            )
            raise NetlifyPageCapExceededError(
                f"Netlify: per-parent page cap of {max_pages} reached with more pages remaining; "
                f"raise max_pages_per_parent to sync this parent fully. context={page_cap_context or {}}"
            )
        url = next_url


def _redact_key(row: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    """Return `row` with a possibly-nested field removed. `"password"` drops a top-level field;
    `"default_hooks_data.access_token"` walks into `default_hooks_data` and drops its `access_token`.
    Only the nodes on the path are copied, so the upstream item is left unmodified; a missing or
    non-dict node is a no-op."""
    head, _, rest = dotted_key.partition(".")
    if head not in row:
        return row
    if not rest:
        return {key: value for key, value in row.items() if key != head}
    nested = row[head]
    if not isinstance(nested, dict):
        return row
    return {**row, head: _redact_key(nested, rest)}


def _redact_rows(rows: list[dict[str, Any]], redact_keys: list[str]) -> list[dict[str, Any]]:
    """Drop each configured (possibly-nested) credential field from every row before it's persisted,
    so account secrets in the API response never land in a queryable warehouse table."""
    if not redact_keys:
        return rows
    redacted: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            for key in redact_keys:
                row = _redact_key(row, key)
        redacted.append(row)
    return redacted


def _make_parent_field_injector(
    parent: dict[str, Any], field_map: dict[str, str]
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Copy the mapped parent fields onto each child row (e.g. the site id onto a build).

    Direct access on the parent fields: the injected columns feed the child's composite primary key,
    so a parent missing one is a broken response that must fail loudly, not corrupt the key with None.
    """
    injected = {child_column: parent[parent_field] for parent_field, child_column in field_map.items()}

    def inject(item: dict[str, Any]) -> dict[str, Any]:
        return {**item, **injected}

    return inject


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
    config: NetlifyEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the parent list and emit every child row per parent, checkpointing the parent page URL.

    On resume we re-fan the current parent page from the saved URL and merge dedupes on the composite
    primary key. Full refresh means there's no watermark to advance — we just walk every parent.
    """
    assert config.fan_out_parent is not None and config.fan_out_path_param is not None
    parent_config = NETLIFY_ENDPOINTS[config.fan_out_parent]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        parent_url = _validate_netlify_url(resume.next_url)
        logger.debug(f"Netlify: resuming {config.name} fan-out from parent URL: {parent_url}")
    else:
        parent_url = _build_url(parent_config.path, parent_config.page_size)

    for parents, parent_page_url in _iter_pages(session, parent_url, headers, logger):
        for parent in parents:
            parent_value = parent[config.fan_out_parent_field]
            inject = (
                _make_parent_field_injector(parent, config.fan_out_include_parent_fields)
                if config.fan_out_include_parent_fields
                else None
            )
            child_path = config.path.format(**{config.fan_out_path_param: parent_value})
            child_url = _build_url(child_path, config.page_size)
            for child_items, _child_page_url in _iter_pages(
                session,
                child_url,
                headers,
                logger,
                max_pages=config.max_pages_per_parent,
                page_cap_context={config.fan_out_path_param: parent_value},
            ):
                rows = [inject(item) for item in child_items] if inject else child_items
                yield _redact_rows(rows, config.redact_keys)
        # Checkpoint after finishing a parent page so a crash re-fans this page rather than skipping
        # ahead. Save AFTER yielding this page's children; resume re-fans and merge dedupes.
        resumable_source_manager.save_state(NetlifyResumeConfig(next_url=parent_page_url))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = NETLIFY_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page (and, for fan-out, every parent) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. Redact the token so the tracked
    # adapter never persists it in logged URLs or captured request/response samples.
    session = make_tracked_session(redact_values=(api_token,))

    if config.fan_out_parent is not None:
        yield from _get_fan_out_rows(session, headers, logger, resumable_source_manager, config)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = _validate_netlify_url(resume.next_url)
        logger.debug(f"Netlify: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(config.path, config.page_size)

    while True:
        response = _fetch_page(session, url, headers, logger)
        data = response.json()
        if not isinstance(data, list) or not data:
            break
        next_url = _parse_next_url(response.headers.get("Link", ""), url)
        yield _redact_rows(data, config.redact_keys)
        if not next_url:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it (merge
        # dedupes on the primary key). next_url is the next page to fetch on resume.
        resumable_source_manager.save_state(NetlifyResumeConfig(next_url=next_url))
        url = next_url


def validate_credentials(api_token: str) -> bool:
    """Probe the token with a cheap single-row /sites request. Netlify personal access tokens have
    full account access (no granular scopes), so one authenticated call confirms the whole token."""
    url = _build_url("/sites", page_size=1)
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            url, headers=_get_headers(api_token), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def netlify_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
) -> SourceResponse:
    endpoint_config = NETLIFY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
