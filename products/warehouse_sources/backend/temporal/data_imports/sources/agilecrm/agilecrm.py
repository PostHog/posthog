import re
import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import (
    AGILECRM_ENDPOINTS,
    BASE_URL_TEMPLATE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# A valid Agile CRM subdomain is a single DNS label: letters, digits and hyphens only. Constraining
# the domain to this pattern stops a malicious value (e.g. `evil.com#`) from retargeting the basic-auth
# credentials at an attacker-controlled host once it's interpolated into the base URL.
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")

REQUEST_TIMEOUT_SECONDS = 60


class AgileCRMRetryableError(Exception):
    pass


@dataclasses.dataclass
class AgileCRMResumeConfig:
    # The cursor returned on the last item of the most recently yielded page. `None` starts at the
    # first page.
    cursor: str | None = None


def _validate_domain(domain: str) -> str:
    cleaned = (domain or "").strip()
    if not _DOMAIN_RE.match(cleaned):
        raise ValueError(f"Invalid Agile CRM domain: {domain!r}. Use just the subdomain, e.g. 'acme'.")
    return cleaned


def base_url(domain: str) -> str:
    return BASE_URL_TEMPLATE.format(domain=_validate_domain(domain))


def _make_session(email: str, api_key: str) -> requests.Session:
    # Agile CRM authenticates with HTTP Basic: account email as username, API key as password.
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,))
    session.auth = (email, api_key)
    return session


@retry(
    retry=retry_if_exception_type((AgileCRMRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise AgileCRMRetryableError(f"Agile CRM API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Agile CRM API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Known list endpoints return a bare JSON array. Tolerate an unexpected object by returning no rows
    # rather than crashing the sync.
    if isinstance(data, list):
        return data
    return []


def get_rows(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AgileCRMResumeConfig],
) -> Iterator[Any]:
    config = AGILECRM_ENDPOINTS[endpoint]
    url = f"{base_url(domain)}/{config.path}"
    session = _make_session(email, api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Agile CRM: resuming {endpoint} from cursor={cursor}")

    while True:
        params: dict[str, Any] = {"page_size": config.page_size}
        if cursor:
            params["cursor"] = cursor

        items = _fetch_page(session, url, params, logger)
        if not items:
            break

        # Agile CRM signals the next page via a `cursor` field on the *last* item of the current page.
        last_item = items[-1]
        next_cursor = last_item.get("cursor") if isinstance(last_item, dict) else None
        # The cursor is navigation metadata, not data. Strip it from the last item so it isn't written
        # to the warehouse as a sparse `cursor` column that only the final row of each page carries.
        if isinstance(last_item, dict) and "cursor" in last_item:
            items = [*items[:-1], {k: v for k, v in last_item.items() if k != "cursor"}]

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary
                # key) rather than skipping it. Only persist when another page follows.
                if next_cursor:
                    resumable_source_manager.save_state(AgileCRMResumeConfig(cursor=next_cursor))

        # No cursor, or a short page, means we've reached the end.
        if not next_cursor or len(items) < config.page_size:
            break

        cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def validate_credentials(domain: str, email: str, api_key: str) -> bool:
    try:
        url = f"{base_url(domain)}/contacts"
    except ValueError:
        return False

    try:
        response = _make_session(email, api_key).get(url, params={"page_size": 1}, timeout=REQUEST_TIMEOUT_SECONDS)
        return response.status_code == 200
    except Exception:
        return False


def agilecrm_source(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AgileCRMResumeConfig],
) -> SourceResponse:
    endpoint_config = AGILECRM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            domain=domain,
            email=email,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
    )
