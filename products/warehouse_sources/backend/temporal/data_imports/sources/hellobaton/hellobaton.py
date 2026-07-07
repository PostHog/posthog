import re
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.settings import (
    HELLOBATON_ENDPOINTS,
    PER_PAGE,
    HellobatonEndpointConfig,
)

HELLOBATON_API_PATH = "/api"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<company>.hellobaton.com`.
_COMPANY_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class HellobatonRetryableError(Exception):
    pass


@dataclasses.dataclass
class HellobatonResumeConfig:
    # Next 1-indexed page to fetch. None means "start from page 1".
    next_page: int | None = None


def normalize_company(company: str) -> str:
    """Reduce user input to a bare, validated Baton company (instance) label.

    Accepts either the full host (``yourcompany.hellobaton.com``) or the bare company
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<company>.hellobaton.com``.
    """
    cleaned = company.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".hellobaton.com")
    if not _COMPANY_RE.match(cleaned):
        raise ValueError(
            f"Invalid Baton company: {company!r}. Enter just your company instance, e.g. 'yourcompany' "
            "for yourcompany.hellobaton.com."
        )
    return cleaned


def _base_url(company: str) -> str:
    return f"https://{normalize_company(company)}.hellobaton.com{HELLOBATON_API_PATH}"


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def _scrub_url(url: str | None) -> str:
    # The api_key rides in the query string, so strip the query before the URL reaches any error
    # message or log line — otherwise a non-2xx response would leak the credential into job errors.
    # The host and path stay intact so `get_non_retryable_errors()` can still match on them.
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@retry(
    retry=retry_if_exception_type((HellobatonRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=60)

    # Baton rate limits at 1000 req/min per API key; 429 and transient 5xx are retryable.
    if response.status_code == 429 or response.status_code >= 500:
        raise HellobatonRetryableError(
            f"Baton API error (retryable): status={response.status_code}, url={_scrub_url(url)}"
        )

    if not response.ok:
        logger.error(f"Baton API error: status={response.status_code}, body={response.text}, url={_scrub_url(url)}")
        # Raise with the api_key scrubbed from the URL rather than calling raise_for_status(), whose
        # message embeds the full credential-bearing URL.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {_scrub_url(response.url)}",
            response=response,
        )

    return response.json()


def get_rows(
    company: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HellobatonResumeConfig],
) -> Iterator[Any]:
    config = HELLOBATON_ENDPOINTS[endpoint]
    base_url = _base_url(company)
    # Baton authenticates via the api_key query param (not a header) and re-requires it on every page.
    params: dict[str, Any] = {"api_key": api_key, "page_size": PER_PAGE}
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # The api_key travels in the query string, so redact it from logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,) if api_key else ())

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None and resume.next_page else 1
    if page > 1:
        logger.debug(f"Baton: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, _build_url(base_url, config.path, {**params, "page": page}), logger)
        items = data.get("results", [])
        if not items:
            break

        # Baton's cursor is a full `next` URL; its absence is the definitive end-of-pages signal.
        has_more = bool(data.get("next"))

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
                # merge dedupes on the primary key.
                if has_more:
                    resumable_source_manager.save_state(HellobatonResumeConfig(next_page=page + 1))

        if not has_more:
            break
        page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def hellobaton_source(
    company: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HellobatonResumeConfig],
) -> SourceResponse:
    config: HellobatonEndpointConfig = HELLOBATON_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            company=company,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(company: str, api_key: str) -> tuple[bool, int | None]:
    """Probe Baton's `/projects/` list with a 1-row page to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the company is malformed so the caller can surface a precise message.
    """
    url = _build_url(_base_url(company), "/projects/", {"api_key": api_key, "page_size": 1})
    try:
        session = make_tracked_session(redact_values=(api_key,) if api_key else ())
        response = session.get(url, timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
