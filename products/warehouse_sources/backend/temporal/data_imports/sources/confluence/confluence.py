import re
import base64
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import CONFLUENCE_ENDPOINTS

# Confluence Cloud sites always live under <subdomain>.atlassian.net. Building
# the host ourselves from a validated subdomain (rather than accepting an
# arbitrary host) keeps the API token from being sent anywhere off-Atlassian.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")

REQUEST_TIMEOUT_SECONDS = 60


class ConfluenceRetryableError(Exception):
    pass


@dataclasses.dataclass
class ConfluenceResumeConfig:
    next_url: str


def _site_origin(subdomain: str) -> str:
    return f"https://{subdomain}.atlassian.net"


def _base_url(subdomain: str) -> str:
    return f"{_site_origin(subdomain)}/wiki/api/v2"


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(subdomain) and _SUBDOMAIN_RE.match(subdomain) is not None


def _get_headers(email: str, api_token: str) -> dict[str, str]:
    token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def _build_initial_url(subdomain: str, path: str, limit: int) -> str:
    return f"{_base_url(subdomain)}{path}?{urlencode({'limit': limit})}"


def _resolve_next_url(subdomain: str, data: dict[str, Any]) -> str | None:
    """Confluence v2 returns the next page as a site-relative path in
    ``_links.next`` (e.g. ``/wiki/api/v2/pages?cursor=...``). Absence of the key
    signals the last page."""
    links = data.get("_links") or {}
    next_path = links.get("next")
    if not next_path:
        return None
    if next_path.startswith("http://") or next_path.startswith("https://"):
        return next_path
    return f"{_site_origin(subdomain)}{next_path}"


def validate_credentials(
    subdomain: str, email: str, api_token: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the Confluence API to confirm the credentials are genuine.

    A 403 at source-create (``schema_name is None``) is accepted: the token may
    be valid but lack access to the probed resource. Once a specific schema is
    being validated we surface the 403.
    """
    if not is_valid_subdomain(subdomain):
        return (
            False,
            "Invalid Confluence subdomain. Use just the site name, e.g. 'your-domain' for your-domain.atlassian.net.",
        )

    url = _build_initial_url(subdomain, CONFLUENCE_ENDPOINTS["spaces"].path, limit=1)
    try:
        response = make_tracked_session().get(url, headers=_get_headers(email, api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Confluence credentials. Check your email and API token."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Confluence account does not have permission to access this resource."

    return False, f"Confluence API returned status {response.status_code}: {response.text}"


def get_rows(
    subdomain: str,
    email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluenceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CONFLUENCE_ENDPOINTS[endpoint]
    headers = _get_headers(email, api_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Confluence: resuming from URL: {url}")
    else:
        url = _build_initial_url(subdomain, config.path, config.limit)

    @retry(
        retry=retry_if_exception_type((ConfluenceRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise ConfluenceRetryableError(
                f"Confluence API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Confluence API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        results = data.get("results", [])
        next_url = _resolve_next_url(subdomain, data)

        if results:
            yield results

        # Save state AFTER yielding so a crash re-fetches the page we just
        # emitted (merge dedupes on primary key) rather than skipping it.
        if not next_url:
            break

        resumable_source_manager.save_state(ConfluenceResumeConfig(next_url=next_url))
        url = next_url


def confluence_source(
    subdomain: str,
    email: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluenceResumeConfig],
) -> SourceResponse:
    endpoint_config = CONFLUENCE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            email=email,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
