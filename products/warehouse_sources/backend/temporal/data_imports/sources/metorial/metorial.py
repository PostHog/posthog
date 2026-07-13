import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import (
    METORIAL_BASE_URL,
    METORIAL_ENDPOINTS,
    PAGE_SIZE,
)

REQUEST_TIMEOUT_SECONDS = 60
# Production keys allow 5000 requests / 10 min (development keys only 100 / 10 min), so a large
# backfill can hit 429s — back off generously rather than failing the sync.
RETRY_ATTEMPTS = 6
RETRY_MAX_WAIT_SECONDS = 120


class MetorialRetryableError(Exception):
    pass


@dataclasses.dataclass
class MetorialResumeConfig:
    # `after` cursor for the next page: the id of the last record already yielded. None starts at
    # page one. Metorial pages by record id, so the cursor stays valid across a crash/retry.
    after: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_watermark(value: Any) -> str:
    """Format the incremental watermark for Metorial's `<field>[gt]` filter.

    Truncates to whole seconds, rounding the lower bound *down* — an incremental sync re-fetches at
    most a few boundary rows (merge dedupes them on `id`) rather than skipping any.

    Accepts the shapes the pipeline can hand back for a DateTime field (datetime/date, ISO-8601
    string, epoch seconds) and raises for anything else — a malformed filter value would make
    Metorial silently return unfiltered/unexpected results rather than erroring.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Unsupported Metorial incremental watermark value: {value!r}")
    elif isinstance(value, int | float) and not isinstance(value, bool):
        value = datetime.fromtimestamp(value, tz=UTC)

    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        raise ValueError(f"Unsupported Metorial incremental watermark value: {value!r}")
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_url(
    path: str,
    after: str | None,
    incremental_field: str | None,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "order": "asc"}
    if after:
        params["after"] = after
    if incremental_field and db_incremental_field_last_value is not None:
        # Metorial parses the query string with `qs`, so the nested date filter uses bracket
        # syntax: `created_at[gt]=...` -> `{created_at: {gt: ...}}`. The filter is a plain
        # where-clause resent on every page, so pagination terminates at the watermark server-side.
        params[f"{incremental_field}[gt]"] = _format_watermark(db_incremental_field_last_value)
    return f"{METORIAL_BASE_URL}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((MetorialRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=RETRY_MAX_WAIT_SECONDS),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], bool]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise MetorialRetryableError(f"Metorial API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Metorial API error: status={response.status_code}, body={response.text[:200]!r}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise MetorialRetryableError(f"Metorial returned an unexpected payload for {url}: {type(data).__name__}")

    pagination = data.get("pagination") or {}
    return data["items"], bool(pagination.get("has_more_after"))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetorialResumeConfig],
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = METORIAL_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume is not None else None
    if after:
        logger.debug(f"Metorial: resuming {endpoint} from after={after}")

    while True:
        url = _build_url(config.path, after, incremental_field, db_incremental_field_last_value)
        items, has_more_after = _fetch_page(session, url, logger)

        if items:
            yield items

        if not has_more_after or not items:
            break

        last_id = items[-1].get("id")
        if not isinstance(last_id, str) or not last_id or last_id == after:
            # Defensive: without an advancing id cursor we'd refetch the same page forever.
            logger.warning(f"Metorial: {endpoint} page did not advance the `after` cursor, stopping")
            break

        after = last_id
        # Save AFTER yielding so a crash re-fetches from the last yielded page's cursor (never
        # skipping a page); merge dedupes any re-pulled rows on the `id` primary key.
        resumable_source_manager.save_state(MetorialResumeConfig(after=after))


def metorial_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MetorialResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = METORIAL_ENDPOINTS[endpoint]

    chosen_field = incremental_field if should_use_incremental_field else None
    if chosen_field is not None:
        allowed = {f["field"] for f in config.incremental_fields}
        if chosen_field not in allowed:
            raise ValueError(f"Incremental field '{chosen_field}' is not supported for Metorial '{endpoint}'")

    # `order=asc` sorts by record id, and Metorial ids are time-sorted, so `created_at` arrives
    # ascending and the pipeline's per-batch watermark checkpointing is safe. `updated_at` is NOT
    # monotonic in id order, so those syncs declare `desc` — the pipeline then commits the
    # watermark only when the run completes, never mid-run past unseen rows.
    sort_mode: SortMode = "asc" if chosen_field in (None, "created_at") else "desc"

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            incremental_field=chosen_field,
            db_incremental_field_last_value=db_incremental_field_last_value if chosen_field else None,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=sort_mode,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # One cheap probe confirms the key is genuine. Secret keys are project-scoped with full read
    # access, so a single endpoint validates every stream; 401/403 are the only conclusive
    # "invalid" signals (429/5xx would push users to rotate a working key, so they get a retry
    # message instead).
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{METORIAL_BASE_URL}/sessions?{urlencode({'limit': 1})}", timeout=15)
    except requests.RequestException:
        return False, "Could not reach Metorial to validate the API key. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Metorial API key. Use a secret key (`metorial_sk_...`) from your project dashboard."
    return (
        False,
        f"Metorial could not validate the API key right now (status {response.status_code}). Please try again.",
    )
