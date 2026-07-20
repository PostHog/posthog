import base64
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.settings import (
    OPINION_STAGE_ENDPOINTS,
)

OPINION_STAGE_BASE_URL = "https://api.opinionstage.com"
# JSON:API `page[size]`. The API does not document a hard maximum, so a moderate page keeps the
# per-page payload bounded while minimising round trips for the small item/widget catalogue.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm the API key is genuine. The personal API key is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v2/items"
# Opinion Stage speaks the JSON:API media type for both request Accept and response Content-Type.
JSON_API_MEDIA_TYPE = "application/vnd.api+json"


class OpinionStageRetryableError(Exception):
    pass


@dataclasses.dataclass
class OpinionStageResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _headers(api_key: str) -> dict[str, str]:
    # HTTP Basic auth: the personal API key is the username and the password is blank, so the
    # credential is base64("<api_key>:"). Precomputing the header keeps the raw key out of URLs.
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": JSON_API_MEDIA_TYPE}


@retry(
    retry=retry_if_exception_type((OpinionStageRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int,
    per_page: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{OPINION_STAGE_BASE_URL}{path}",
        params={"page[number]": page, "page[size]": per_page},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise OpinionStageRetryableError(
            f"Opinion Stage API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"Opinion Stage API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # JSON:API always wraps a collection under a top-level `data` list; missing it means a malformed
    # response, so fail loudly rather than silently advancing the cursor past lost rows.
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise OpinionStageRetryableError(
            f"Opinion Stage returned an unexpected payload for {path}: {type(data).__name__}"
        )
    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpinionStageResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = OPINION_STAGE_ENDPOINTS[endpoint]
    # `redact_values` masks the API key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"Opinion Stage: resuming {endpoint} from page {page}")

    while True:
        payload = _fetch_page(session, config.path, page, PAGE_SIZE, logger)

        # Yield the raw JSON:API resource objects ({id, type, attributes}); `id` is the primary key.
        items = payload["data"]
        if items:
            yield items

        # JSON:API paginates via `links.next`: a null/absent next link (or an empty page) is the end
        # of the collection.
        next_link = (payload.get("links") or {}).get("next")
        if not next_link or not items:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(OpinionStageResumeConfig(next_page=page))


def opinion_stage_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpinionStageResumeConfig],
) -> SourceResponse:
    config = OPINION_STAGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the personal API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(
            f"{OPINION_STAGE_BASE_URL}{path}",
            params={"page[number]": 1, "page[size]": 1},
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Opinion Stage: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Opinion Stage returned HTTP {response.status_code}"

    return 200, None
