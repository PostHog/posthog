import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import (
    DEEPGRAM_ENDPOINTS,
    DeepgramEndpointConfig,
)

DEEPGRAM_BASE_URL = "https://api.deepgram.com/v1"

# The requests log caps `limit` at 1000; use the max to minimise round trips.
REQUESTS_PAGE_SIZE = 1000

REQUEST_TIMEOUT_SECONDS = 60


class DeepgramRetryableError(Exception):
    pass


@dataclasses.dataclass
class DeepgramResumeConfig:
    # Stable project-id bookmark of the project currently being fetched. Not a positional index so a
    # project added/removed between a crash and the retry can't resume us into the wrong project.
    project_id: str | None = None
    # Next page to fetch for the paginated requests endpoint (0-indexed). None for the unpaginated
    # full-refresh endpoints.
    page: int | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def _get_session(api_key: str) -> requests.Session:
    # The API key travels in the Authorization header on every request; register it for value-based
    # redaction so a failed or sampled request never persists the customer's secret in HTTP logs.
    return make_tracked_session(redact_values=(api_key,))


@retry(
    retry=retry_if_exception_type(
        (
            DeepgramRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger, params: dict[str, Any]
) -> dict:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise DeepgramRetryableError(f"Deepgram API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Deepgram API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # Listing projects is the cheapest probe that proves the token is genuine; it is also the seed for
    # every other (project-scoped) endpoint, so a token that can't list projects can't sync anything.
    try:
        response = _get_session(api_key).get(
            f"{DEEPGRAM_BASE_URL}/projects",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def _list_project_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    data = _fetch_json(session, f"{DEEPGRAM_BASE_URL}/projects", headers, logger, params={})
    return [project["project_id"] for project in data.get("projects", []) if project.get("project_id")]


def _format_start_value(value: Any) -> str:
    """Format an incremental cursor value for Deepgram's `start` filter.

    Deepgram accepts YYYY-MM-DD or ISO 8601; we send full ISO 8601 with a Z suffix. Future-dated
    cursors are capped at now so we never build a start-in-the-future filter (harmless but pointless).
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        aware = now if aware > now else aware
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        capped = now.date() if value > now.date() else value
        return capped.isoformat()
    return str(value)


def _redact_url_userinfo(url: str) -> str:
    """Strip embedded userinfo (`user:pass@`) from a URL.

    Deepgram callback URLs can carry Basic Auth credentials in the userinfo component; those must not
    land in the warehouse where anyone with query access could read them. The host/path is preserved
    so the row still records which callback was used.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=host))


def _transform_row(row: dict[str, Any], project_id: str, config: DeepgramEndpointConfig) -> dict[str, Any]:
    if config.flatten_key and isinstance(row.get(config.flatten_key), dict):
        nested = row.pop(config.flatten_key)
        row = {**row, **nested}
    # Fan-out rows carry the parent project's id so the composite primary key stays unique table-wide.
    row["project_id"] = project_id
    # Request-log rows can echo the callback URL, which may embed Basic Auth credentials.
    if isinstance(row.get("callback"), str):
        row["callback"] = _redact_url_userinfo(row["callback"])
    # A row missing a required primary-key field would let the delta merge build a partial predicate
    # and overwrite unrelated rows in the same project, so fail loudly instead of emitting it.
    for primary_key in config.primary_keys:
        if row.get(primary_key) is None:
            raise ValueError(f"Deepgram {config.name} row missing required primary key '{primary_key}'")
    return row


def _build_request_params(
    config: DeepgramEndpointConfig,
    page: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": REQUESTS_PAGE_SIZE, "page": page}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["start"] = _format_start_value(db_incremental_field_last_value)
    return params


def _iter_project_endpoint(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    config: DeepgramEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    project_ids = _list_project_ids(session, headers, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = project_ids
    resume_page: int | None = None
    if resume is not None and resume.project_id is not None and resume.project_id in project_ids:
        remaining = project_ids[project_ids.index(resume.project_id) :]
        resume_page = resume.page
        logger.debug(f"Deepgram: resuming {config.name} from project_id={resume.project_id}, page={resume_page}")

    for index, project_id in enumerate(remaining):
        base_url = f"{DEEPGRAM_BASE_URL}/projects/{project_id}{config.path}"

        if config.paginated:
            page = resume_page if index == 0 and resume_page is not None else 0
            while True:
                params = _build_request_params(
                    config, page, should_use_incremental_field, db_incremental_field_last_value
                )
                data = _fetch_json(session, base_url, headers, logger, params)
                items = data.get(config.data_key, [])

                if items:
                    yield [_transform_row(item, project_id, config) for item in items]

                # A short page (fewer rows than the limit) or an empty page means we've reached the end.
                if len(items) < REQUESTS_PAGE_SIZE:
                    break

                page += 1
                # Save AFTER yielding so a crash re-fetches from the last saved page rather than skipping
                # it; merge dedupes any re-pulled rows on the primary key.
                resumable_source_manager.save_state(DeepgramResumeConfig(project_id=project_id, page=page))
        else:
            data = _fetch_json(session, base_url, headers, logger, params={})
            items = data.get(config.data_key, [])
            if items:
                yield [_transform_row(item, project_id, config) for item in items]

        resume_page = None
        # Advance the bookmark to the next project so a crash between projects resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(DeepgramResumeConfig(project_id=remaining[index + 1], page=0))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DEEPGRAM_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every request so urllib3 keeps the connection alive instead of
    # re-handshaking per project/page.
    session = _get_session(api_key)

    if config.is_project_list:
        data = _fetch_json(session, f"{DEEPGRAM_BASE_URL}/projects", headers, logger, params={})
        items = data.get(config.data_key, [])
        if items:
            yield items
        return

    yield from _iter_project_endpoint(
        session,
        headers,
        logger,
        resumable_source_manager,
        config,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )


def deepgram_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepgramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DEEPGRAM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The requests log's default order isn't documented and can't be curl-verified without a live
        # token, so we use "desc": the pipeline finalises the incremental watermark (max `created`) only
        # at job end rather than checkpointing per batch, which stays correct regardless of the actual
        # arrival order. The `start` filter still bounds each incremental sync server-side, so this is
        # not a re-fetch-all-history situation. Full-refresh endpoints keep the default "asc".
        sort_mode="desc" if config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
