import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.settings import (
    CHARGEDESK_ENDPOINTS,
    ChargedeskEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CHARGEDESK_BASE_URL = "https://api.chargedesk.com/v1"

# ChargeDesk doesn't document rate limits, so retry transient failures with capped exponential backoff.
MAX_ATTEMPTS = 5


class ChargedeskRetryableError(Exception):
    pass


@dataclasses.dataclass
class ChargedeskResumeConfig:
    # ChargeDesk has no opaque page cursor — pagination is purely `offset` within a `[max]`-bounded window,
    # so resuming only needs the next offset and the current upper time bound.
    offset: int = 0
    window_max: int | None = None
    # Which pass we were in when state was saved. An incremental sync against a newest-first API runs an
    # "earliest" backfill (rows older than what we have) followed by a "latest" pass (rows newer than the
    # watermark); "full" is the first/full-refresh scan. Tracking the phase lets a resume pick up the right
    # pass instead of restarting the whole sync.
    phase: str = "full"


def _auth(api_key: str) -> tuple[str, str]:
    # HTTP Basic with the secret key as the username and an empty password.
    return (api_key, "")


@retry(
    retry=retry_if_exception_type((ChargedeskRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    auth: tuple[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, auth=auth, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ChargedeskRetryableError(f"ChargeDesk API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"ChargeDesk API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_pages(
    session: requests.Session,
    auth: tuple[str, str],
    cfg: ChargedeskEndpointConfig,
    logger: FilteringBoundLogger,
    *,
    min_value: int | None,
    start_offset: int,
    start_window_max: int | None,
) -> Iterator[tuple[list[dict], tuple[int, int | None] | None]]:
    """Page through a ChargeDesk list endpoint by offset.

    Yields ``(page_items, resume_state)`` where ``resume_state`` is the ``(offset, window_max)`` to resume
    from to fetch the *next* page, or ``None`` when this is the terminal page. Results come back newest
    first, so once the offset nears the API's hard cap we reset it to 0 and pin ``[max]`` to the oldest row
    we just saw (the boundary row is re-fetched and deduped on the primary key by the merge).
    """
    url = f"{CHARGEDESK_BASE_URL}{cfg.path}"
    offset = start_offset
    window_max = start_window_max

    while True:
        params: dict[str, Any] = {"count": cfg.page_size, "offset": offset}
        if min_value is not None:
            params[f"{cfg.filter_param}[min]"] = min_value
        if window_max is not None:
            params[f"{cfg.filter_param}[max]"] = window_max

        data = _fetch_page(session, url, auth, params, logger)
        items = data.get("data", [])

        # A short page (fewer rows than requested) means there's nothing after it in this window.
        if len(items) < cfg.page_size:
            yield items, None
            return

        next_offset = offset + cfg.page_size
        next_window_max = window_max

        if next_offset + cfg.page_size > cfg.max_offset:
            oldest_ts = items[-1].get(cfg.timestamp_field)
            if not isinstance(oldest_ts, int):
                # Can't shift the window without a timestamp to anchor it, and stepping past the cap would
                # 400. Surface it rather than silently dropping the tail.
                logger.warning(
                    f"ChargeDesk: {cfg.name} hit the offset cap ({cfg.max_offset}) but the last row has no "
                    f"usable '{cfg.timestamp_field}' to continue from; stopping pagination for this window."
                )
                yield items, None
                return
            if oldest_ts == window_max:
                # The whole offset window collapsed onto a single timestamp: more than `max_offset` rows
                # share `oldest_ts`, so re-pinning `[max]` to the same value would re-fetch this exact page
                # forever (offset can't advance past the cap). Surface it and stop rather than spin until
                # Temporal kills the activity. The unreachable tail is a hard limitation of an offset+`[max]`
                # API when a single timestamp exceeds the offset cap.
                logger.warning(
                    f"ChargeDesk: {cfg.name} has more than {cfg.max_offset} rows at {cfg.timestamp_field}="
                    f"{oldest_ts}; the offset cap prevents fetching the rest of this timestamp, stopping "
                    f"pagination for this window."
                )
                yield items, None
                return
            logger.debug(f"ChargeDesk: {cfg.name} reached offset cap, shifting {cfg.filter_param}[max] to {oldest_ts}")
            next_offset = 0
            next_window_max = oldest_ts

        yield items, (next_offset, next_window_max)
        offset = next_offset
        window_max = next_window_max


def _run_pass(
    session: requests.Session,
    auth: tuple[str, str],
    cfg: ChargedeskEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: "ResumableSourceManager[ChargedeskResumeConfig]",
    *,
    phase: str,
    min_value: int | None,
    start_offset: int,
    start_window_max: int | None,
) -> Iterator[Any]:
    """Batch a single pass's pages, yielding tables and saving resume state at page boundaries.

    State is saved only after a whole page has been batched and a table yielded, so a crash re-fetches
    from the next page rather than skipping the unyielded tail of a partially consumed page.
    """
    for items, resume_state in _iter_pages(
        session,
        auth,
        cfg,
        logger,
        min_value=min_value,
        start_offset=start_offset,
        start_window_max=start_window_max,
    ):
        for item in items:
            batcher.batch(item)

        if batcher.should_yield():
            yield batcher.get_table()
            if resume_state is not None:
                resumable_source_manager.save_state(
                    ChargedeskResumeConfig(offset=resume_state[0], window_max=resume_state[1], phase=phase)
                )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[ChargedeskResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    db_incremental_field_earliest_value: Any = None,
) -> Iterator[Any]:
    cfg = CHARGEDESK_ENDPOINTS[endpoint]
    auth = _auth(api_key)
    # Redact the secret key from logged URLs / captured samples — it rides in the Basic auth header.
    session = make_tracked_session(redact_values=(api_key,))
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    incremental = should_use_incremental_field and cfg.supports_incremental
    no_watermark = db_incremental_field_last_value is None and db_incremental_field_earliest_value is None

    if not incremental or no_watermark:
        start_offset, window_max = (
            (resume.offset, resume.window_max) if resume and resume.phase == "full" else (0, None)
        )
        yield from _run_pass(
            session,
            auth,
            cfg,
            logger,
            batcher,
            resumable_source_manager,
            phase="full",
            min_value=None,
            start_offset=start_offset,
            start_window_max=window_max,
        )
    else:
        # Newest-first incremental: first walk older rows we don't have yet (bounded by the earliest value
        # we've synced), then the rows newer than our watermark. Skip the earliest pass entirely if a resume
        # tells us we already finished it.
        if db_incremental_field_earliest_value is not None and (resume is None or resume.phase == "earliest"):
            if resume is not None and resume.phase == "earliest":
                start_offset, window_max = resume.offset, resume.window_max
            else:
                start_offset, window_max = 0, int(db_incremental_field_earliest_value)
            yield from _run_pass(
                session,
                auth,
                cfg,
                logger,
                batcher,
                resumable_source_manager,
                phase="earliest",
                min_value=None,
                start_offset=start_offset,
                start_window_max=window_max,
            )

        if db_incremental_field_last_value is not None:
            if resume is not None and resume.phase == "latest":
                start_offset, window_max = resume.offset, resume.window_max
            else:
                start_offset, window_max = 0, None
            yield from _run_pass(
                session,
                auth,
                cfg,
                logger,
                batcher,
                resumable_source_manager,
                phase="latest",
                min_value=int(db_incremental_field_last_value),
                start_offset=start_offset,
                start_window_max=window_max,
            )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def chargedesk_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[ChargedeskResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    db_incremental_field_earliest_value: Optional[Any] = None,
) -> SourceResponse:
    cfg = CHARGEDESK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
        ),
        primary_keys=cfg.primary_keys,
        # ChargeDesk list endpoints return rows newest first (offset 0 is the most recent; the docs
        # recommend paginating earlier with `[max]`). Matches the newest-first contract Stripe uses.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[cfg.timestamp_field],
    )


def validate_credentials(api_key: str) -> bool:
    # A single company secret key grants full read access (ChargeDesk has no per-resource scopes), so one
    # cheap probe against /charges confirms the key is genuine.
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{CHARGEDESK_BASE_URL}/charges",
            auth=_auth(api_key),
            params={"count": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
