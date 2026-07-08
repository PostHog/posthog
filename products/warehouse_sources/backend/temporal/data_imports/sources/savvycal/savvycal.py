import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import SAVVYCAL_ENDPOINTS

SAVVYCAL_BASE_URL = "https://api.savvycal.com/v1"
# List endpoints accept a `limit` of up to 100; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Cheap single-object endpoint used to confirm a token is genuine. Personal access tokens carry
# the account's full read access, so one probe validates every list endpoint.
DEFAULT_PROBE_PATH = "/me"


class SavvyCalRetryableError(Exception):
    pass


@dataclasses.dataclass
class SavvyCalResumeConfig:
    # Cursor for the next page, taken verbatim from the API's `metadata.after`. `None` means start
    # from the first page. A crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on `id`.
    after: str | None = None
    # The `from` date bound the interrupted run was started with (events incremental only). Reused
    # verbatim on resume so the saved cursor stays paired with the query it was minted under, even
    # if the watermark advanced between attempts.
    from_date: str | None = None


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _format_from_date(value: Any) -> str:
    """Format an incremental cursor for the events `from` filter (YYYY-MM-DD).

    `from` is an inclusive lower bound on the event *start date*, so truncating a datetime
    watermark to its date re-fetches the watermark day; merge dedupes on `id`.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@retry(
    retry=retry_if_exception_type((SavvyCalRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    response = session.get(f"{SAVVYCAL_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SavvyCalRetryableError(f"SavvyCal API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"SavvyCal API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # List endpoints wrap records in {"entries": [...], "metadata": {"after": ..., "before": ..., "limit": ...}}.
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise SavvyCalRetryableError(f"SavvyCal returned an unexpected payload for {path}: {type(data).__name__}")

    metadata = data.get("metadata")
    after = metadata.get("after") if isinstance(metadata, dict) else None
    return data["entries"], after if isinstance(after, str) and after else None


def _base_params(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumed_from_date: str | None,
) -> dict[str, Any]:
    config = SAVVYCAL_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.params}

    if endpoint == "events":
        from_date = resumed_from_date
        if from_date is None and should_use_incremental_field and db_incremental_field_last_value is not None:
            from_date = _format_from_date(db_incremental_field_last_value)

        if from_date is not None:
            # `from` only applies with period=fixed. The spec marks `until` independently optional,
            # so we leave the window open-ended; unverifiable without live credentials.
            params["period"] = "fixed"
            params["from"] = from_date
        else:
            params["period"] = "all"

    return params


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SavvyCalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume else None
    params = _base_params(
        endpoint,
        should_use_incremental_field,
        db_incremental_field_last_value,
        resumed_from_date=resume.from_date if resume else None,
    )
    if resume and resume.after is not None:
        logger.debug(f"SavvyCal: resuming {endpoint} from cursor {after}")

    config = SAVVYCAL_ENDPOINTS[endpoint]
    while True:
        page_params = {**params, "after": after} if after is not None else params
        items, after = _fetch_page(session, config.path, page_params, logger)
        if items:
            yield items

        # A null `metadata.after` cursor means we've reached the end of the collection.
        if not after:
            break

        # Save AFTER yielding so a crash re-fetches from the next cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SavvyCalResumeConfig(after=after, from_date=params.get("from")))


def savvycal_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SavvyCalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAVVYCAL_ENDPOINTS[endpoint]

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Events are requested with direction=asc on start time, matching the incremental cursor;
        # other endpoints are full refresh, where the watermark is unused.
        sort_mode="asc",
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{SAVVYCAL_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SavvyCal: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SavvyCal returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid SavvyCal personal access token"
    return False, message or "Could not validate SavvyCal personal access token"
