"""Care Quality Commission (CQC) Syndication API transport.

The CQC Syndication API (https://api.cqc.org.uk/public/v1) exposes the UK regulator's data on
health and social care providers and locations. Two list endpoints (`/providers`, `/locations`)
return thin summary records (id + name) with page-number pagination; the rich record — addresses,
registration dates, organisation/service types, regulated activities, specialisms, and latest
ratings — only comes from the per-id detail endpoints (`/providers/{id}`, `/locations/{id}`). So
each stream pages the list and fans out one detail call per id.

Authentication is a single subscription/primary key (obtained from the CQC developer portal at
api-portal.service.cqc.org.uk) sent as the `Ocp-Apim-Subscription-Key` header. A `partnerCode`
query param is recommended on every request — clients sending it get the 2000 req/min tier; without
it requests are throttled harder and 429 more readily.

Incremental sync: the API only surfaces change detection via `/changes/provider` and
`/changes/location` (which return changed ids for a `startTimestamp`/`endTimestamp` window). Those
would require fanning out to detail per changed id, but — critically — the detail records carry no
stable "last modified" timestamp we can anchor the pipeline's incremental watermark to. Without a
row-level cursor field the watermark can't advance correctly, so both streams ship full-refresh
only. Full refresh is resumable at list-page granularity so a long fan-out survives heartbeat
timeouts.
"""

import math
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.settings import (
    CQC_ENDPOINTS,
    CQCEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CQC_BASE_URL = "https://api.cqc.org.uk/public/v1"

# Records per list page. The detail fan-out dominates request volume, so this only trades off list
# round-trips; a few hundred keeps each resumable page a sensible unit of work.
LIST_PAGE_SIZE = 500


class CQCRetryableError(Exception):
    pass


@dataclasses.dataclass
class CQCResumeConfig:
    # Next list page to fetch. On resume we re-fetch this page (and re-fan-out its detail); merge
    # dedupes the re-pulled rows on the primary key.
    page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Ocp-Apim-Subscription-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "PostHog-DataWarehouse",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{CQC_BASE_URL}{path}"
    filtered = {key: value for key, value in params.items() if value is not None and value != ""}
    if not filtered:
        return url
    return f"{url}?{urlencode(filtered)}"


@retry(
    retry=retry_if_exception_type((CQCRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient — back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise CQCRetryableError(f"CQC API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"CQC API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str, partner_code: str | None) -> bool:
    # A single cheap probe of the providers list confirms the subscription key is genuine without
    # depending on any particular record existing.
    url = _build_url("/providers", {"page": 1, "perPage": 1, "partnerCode": partner_code})
    try:
        # `redact_values` scrubs the subscription key from logged URLs and captured HTTP samples;
        # `allow_redirects=False` stops a 30x from forwarding the credentialed header off-host.
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
        response = session.get(url, headers=_get_headers(api_key), timeout=30)
        return response.status_code == 200
    except Exception:
        return False


def _iter_detail_rows(
    session: requests.Session,
    config: CQCEndpointConfig,
    headers: dict[str, str],
    partner_code: str | None,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[CQCResumeConfig],
    start_page: int,
) -> Iterator[Any]:
    page = start_page
    while True:
        list_data = _fetch(
            session,
            _build_url(config.list_path, {"page": page, "perPage": LIST_PAGE_SIZE, "partnerCode": partner_code}),
            headers,
            logger,
        )

        items = list_data.get(config.list_data_key, [])
        if not items:
            break

        # If totalPages is missing or smaller than the page we just fetched, don't trust it to
        # terminate — fall back to the empty-items check above, which is the safe loop terminator.
        total_pages = list_data.get("totalPages")
        if total_pages is None or total_pages < page:
            total_pages = math.inf

        for item in items:
            # Direct access: a list record missing its id field is an API contract violation worth
            # surfacing as a KeyError rather than silently skipping the row.
            record_id = item[config.id_field]

            detail = _fetch(
                session,
                _build_url(config.detail_path.format(id=record_id), {"partnerCode": partner_code}),
                headers,
                logger,
            )
            batcher.batch(detail)

            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-fetches the current page rather than skipping
                # rows; merge dedupes the re-pulled records on the primary key.
                resumable_source_manager.save_state(CQCResumeConfig(page=page))

        if page >= total_pages:
            break

        page += 1
        # Advance the bookmark so a crash between pages resumes on the next page.
        resumable_source_manager.save_state(CQCResumeConfig(page=page))


def get_rows(
    api_key: str,
    partner_code: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CQCResumeConfig],
) -> Iterator[Any]:
    config = CQC_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every list page and detail call so urllib3 keeps the connection
    # alive instead of re-handshaking per request. `redact_values` scrubs the subscription key
    # from logged URLs and captured HTTP samples; `allow_redirects=False` stops a 30x from
    # forwarding the credentialed header off-host.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_page = resume.page if resume is not None else 1
    if resume is not None:
        logger.debug(f"CQC: resuming {endpoint} from page {start_page}")

    yield from _iter_detail_rows(
        session, config, headers, partner_code, logger, batcher, resumable_source_manager, start_page
    )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def care_quality_commission_source(
    api_key: str,
    partner_code: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CQCResumeConfig],
) -> SourceResponse:
    config = CQC_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            partner_code=partner_code,
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
