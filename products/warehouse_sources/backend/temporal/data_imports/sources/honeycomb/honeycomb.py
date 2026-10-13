import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.settings import (
    HONEYCOMB_ENDPOINTS,
    HoneycombEndpointConfig,
    HoneycombScope,
)

# Honeycomb hosts a separate API instance per region; keys are region-specific, so requests
# against the wrong host 401 even with a valid key.
HONEYCOMB_BASE_URLS: dict[str, str] = {
    "us": "https://api.honeycomb.io",
    "eu": "https://api.eu1.honeycomb.io",
}
# Honeycomb's keyword for environment-scoped resources (markers, derived columns) that live
# outside any real dataset.
ENVIRONMENT_WIDE_SLUG = "__all__"

# Recipient payloads carry live credentials: PagerDuty integration keys, webhook signing
# secrets, and webhook / MS Teams URLs (capability URLs). Those must never land in a
# warehouse table any project member can query, so recipient `details` are filtered to an
# allow-list — unknown keys (new recipient types) are redacted, failing closed.
SAFE_RECIPIENT_DETAIL_KEYS = frozenset({"email_address", "slack_channel", "webhook_name", "pagerduty_integration_name"})
# Recipient types whose `target` (the abbreviated form embedded in trigger / burn-alert rows)
# is a plain address rather than a credential.
SAFE_RECIPIENT_TARGET_TYPES = frozenset({"email", "slack"})
# Endpoints whose raw responses contain recipient credentials — excluded from HTTP sample
# capture so unsanitized bodies are never persisted (still metered and logged).
ENDPOINTS_WITH_CREDENTIAL_PAYLOADS = frozenset({"recipients", "triggers", "burn_alerts"})
REDACTED_VALUE = "[REDACTED]"

# How far back a full refresh (or the first incremental sync) reads SLO hourly counts.
SLO_COUNTS_HISTORY_LOOKBACK = timedelta(days=90)
# Each counts-history request covers one window per SLO; a week is 168 hourly buckets.
SLO_COUNTS_HISTORY_WINDOW = timedelta(days=7)
SECONDS_PER_HOUR = 3600


class HoneycombRetryableError(Exception):
    pass


class HoneycombSloCountsUnavailableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class HoneycombResumeConfig:
    # The fan-out dataset currently being processed, bookmarked by its stable slug (not a
    # positional index) so datasets created/deleted between a crash and the retry can't resume
    # us into the wrong dataset. The bookmarked dataset is re-fetched in full on resume — its
    # rows may not have been durably flushed — and merge dedupes on the primary key. None for
    # environment-level endpoints, which are a single request with nothing to resume.
    dataset_slug: str | None = None
    # The same bookmark for the board views fan-out, which walks boards instead of datasets.
    board_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Honeycomb-Team": api_key,
        "Content-Type": "application/json",
    }


def _base_url(region: str) -> str:
    return HONEYCOMB_BASE_URLS.get(region, HONEYCOMB_BASE_URLS["us"])


@retry(
    retry=retry_if_exception_type((HoneycombRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger):
    response = session.get(url, headers=headers, timeout=60)

    # Honeycomb rate limits per key/team and returns 429 on exceed; retry those plus
    # transient 5xx with exponential backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise HoneycombRetryableError(f"Honeycomb API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404s are expected during the fan-out (a dataset deleted mid-sync, or a plan/permission
        # gap on the __all__ pseudo-dataset) and handled by the caller.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Honeycomb API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _fetch_list(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Fetch a Honeycomb v1 list endpoint, which returns the full collection as one JSON array.

    Honeycomb's v1 config endpoints (datasets, columns, triggers, SLOs, markers, boards,
    recipients) are unpaginated. A non-list body has no rows to emit, so it is logged and
    treated as empty rather than crashing the sync on an unexpected shape."""
    response = _fetch_page(session, url, headers, logger)
    data = response.json()
    if not isinstance(data, list):
        logger.warning(f"Honeycomb: expected a JSON array from {url}, got {type(data).__name__}; skipping")
        return []
    return data


def _fetch_list_skipping_missing(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Fetch a fan-out list, treating 404 as empty.

    A dataset deleted between enumeration and this fetch 404s, as does the ``__all__``
    pseudo-dataset on endpoints/plans where it isn't available. Neither should fail the
    whole sync — the rows are genuinely absent. Any other HTTP error is re-raised."""
    try:
        return _fetch_list(session, url, headers, logger)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return []
        raise


def _fetch_slo_counts_buckets(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]] | None:
    """Fetch one SLO's hourly count buckets, or None on 404 (SLO deleted, or feature off)."""
    try:
        data = _fetch_page(session, url, headers, logger).json()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None
        raise
    buckets = data.get("buckets") if isinstance(data, dict) else None
    return buckets if isinstance(buckets, list) else []


def _to_epoch_seconds(value: Any) -> int | None:
    """Normalise a persisted watermark (int epoch, datetime, or string) to epoch seconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int((value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp())
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp())
    return None


def _sanitize_recipient(recipient: dict[str, Any]) -> dict[str, Any]:
    """Redact credential-bearing fields from a recipient object (full or embedded form)."""
    sanitized = dict(recipient)
    details = sanitized.get("details")
    if isinstance(details, dict):
        sanitized["details"] = {
            key: (value if key in SAFE_RECIPIENT_DETAIL_KEYS else REDACTED_VALUE) for key, value in details.items()
        }
    if "target" in sanitized and sanitized.get("type") not in SAFE_RECIPIENT_TARGET_TYPES:
        sanitized["target"] = REDACTED_VALUE
    return sanitized


def _sanitize_row(endpoint_name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Scrub recipient credentials from a row before it reaches the warehouse."""
    if endpoint_name == "recipients":
        return _sanitize_recipient(row)
    embedded = row.get("recipients")
    if isinstance(embedded, list):
        row = dict(row)
        row["recipients"] = [_sanitize_recipient(item) if isinstance(item, dict) else item for item in embedded]
    return row


def _list_dataset_slugs(
    session: requests.Session, base_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    return [dataset["slug"] for dataset in _fetch_list(session, f"{base_url}/1/datasets", headers, logger)]


def _rows_for_dataset(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: HoneycombEndpointConfig,
    dataset_slug: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Fetch one fan-out dataset's rows, injecting the dataset slug into each row."""
    url = f"{base_url}{config.path.format(dataset_slug=dataset_slug)}"

    if config.scope == HoneycombScope.PER_SLO:
        # Burn alerts are listed per SLO, so walk the dataset's SLOs first. A multi-dataset SLO
        # is listed under each dataset it spans; the (id, dataset_slug) primary key keeps the
        # re-fetched burn alerts distinct per dataset rather than multi-matching on merge.
        rows: list[dict[str, Any]] = []
        slos = _fetch_list_skipping_missing(session, f"{base_url}/1/slos/{dataset_slug}", headers, logger)
        for slo in slos:
            slo_id = slo["id"]
            items = _fetch_list_skipping_missing(session, f"{url}?slo_id={slo_id}", headers, logger)
            rows.extend(
                {**_sanitize_row(config.name, item), "dataset_slug": dataset_slug, "slo_id": slo_id} for item in items
            )
        return rows

    items = _fetch_list_skipping_missing(session, url, headers, logger)
    return [{**_sanitize_row(config.name, item), "dataset_slug": dataset_slug} for item in items]


def _iter_fan_out(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: HoneycombEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[HoneycombResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk every dataset and emit each dataset's rows as one batch, bookmarking progress.

    Full refresh: Honeycomb's config endpoints expose no server-side timestamp filter, so
    each sync re-walks every dataset. Rows re-pulled on resume dedupe on the composite
    primary key."""
    dataset_slugs = _list_dataset_slugs(session, base_url, headers, logger)
    if config.include_environment_wide:
        dataset_slugs.append(ENVIRONMENT_WIDE_SLUG)

    # Resolve the saved bookmark to the slice of datasets still to process. The bookmarked
    # dataset itself is re-fetched — its rows may have been yielded but not durably flushed
    # before the crash. If it no longer exists, start over; merge dedupes the re-pulled rows.
    resume = manager.load_state() if manager.can_resume() else None
    start_index = 0
    if resume is not None and resume.dataset_slug is not None and resume.dataset_slug in dataset_slugs:
        start_index = dataset_slugs.index(resume.dataset_slug)
        logger.debug(f"Honeycomb: resuming {config.name} fan-out from dataset={resume.dataset_slug}")

    for dataset_slug in dataset_slugs[start_index:]:
        rows = _rows_for_dataset(session, base_url, headers, config, dataset_slug, logger)
        if not rows:
            continue
        yield rows
        # Save AFTER yielding so a crash re-yields this dataset rather than skipping it.
        manager.save_state(HoneycombResumeConfig(dataset_slug=dataset_slug))


def _iter_board_views(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: HoneycombEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[HoneycombResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk every board and emit its views as one batch, bookmarking progress by board id."""
    board_ids = [board["id"] for board in _fetch_list(session, f"{base_url}/1/boards", headers, logger)]

    resume = manager.load_state() if manager.can_resume() else None
    start_index = 0
    if resume is not None and resume.board_id is not None and resume.board_id in board_ids:
        start_index = board_ids.index(resume.board_id)
        logger.debug(f"Honeycomb: resuming {config.name} fan-out from board={resume.board_id}")

    for board_id in board_ids[start_index:]:
        url = f"{base_url}{config.path.format(board_id=board_id)}"
        items = _fetch_list_skipping_missing(session, url, headers, logger)
        if not items:
            continue
        yield [{**item, "board_id": board_id} for item in items]
        manager.save_state(HoneycombResumeConfig(board_id=board_id))


def _iter_slo_counts_history(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: HoneycombEndpointConfig,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Emit hourly SLO count buckets, one batch per time window across every SLO.

    Windows are the outer loop so each batch's max `start_time` never goes backwards, which
    keeps the ascending incremental watermark safe to checkpoint after every batch. The
    watermark hour itself is re-read: the latest bucket is often `is_partial` and keeps
    growing until the hour completes, and merge on the primary key replaces it."""
    now = int(datetime.now(UTC).timestamp())
    floor = now - int(SLO_COUNTS_HISTORY_LOOKBACK.total_seconds())
    watermark = _to_epoch_seconds(db_incremental_field_last_value)
    # The lookback also floors the watermark: a non-epoch value (e.g. a user-picked count
    # column) would otherwise walk decades of empty windows, one request per SLO each.
    start = floor if watermark is None else max(watermark, floor)
    start -= start % SECONDS_PER_HOUR

    slos: list[tuple[str, str]] = []
    for dataset_slug in _list_dataset_slugs(session, base_url, headers, logger):
        for slo in _fetch_list_skipping_missing(session, f"{base_url}/1/slos/{dataset_slug}", headers, logger):
            slos.append((dataset_slug, slo["id"]))

    window_seconds = int(SLO_COUNTS_HISTORY_WINDOW.total_seconds())
    window_start = start
    while window_start < now:
        window_end = min(window_start + window_seconds, now)
        query = urlencode({"start_time": window_start, "end_time": window_end})
        rows: list[dict[str, Any]] = []
        found_any = False
        for dataset_slug, slo_id in slos:
            url = f"{base_url}{config.path.format(dataset_slug=dataset_slug, slo_id=slo_id)}?{query}"
            buckets = _fetch_slo_counts_buckets(session, url, headers, logger)
            if buckets is None:
                continue
            found_any = True
            rows.extend({**bucket, "dataset_slug": dataset_slug, "slo_id": slo_id} for bucket in buckets)
        # One deleted SLO 404s on its own; every SLO 404ing means the endpoint is off for this
        # team, which must fail loudly rather than finish as an empty sync.
        if slos and not found_any and window_start == start:
            raise HoneycombSloCountsUnavailableError(
                "Honeycomb SLO counts history is unavailable for this API key: every SLO returned 404"
            )
        if rows:
            yield rows
        window_start = window_end


def get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneycombResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = HONEYCOMB_ENDPOINTS[endpoint]
    base_url = _base_url(region)
    headers = _get_headers(api_key)
    # One session reused across every request so urllib3 keeps the connection alive instead of
    # re-handshaking per request. Redact the key: it rides in the X-Honeycomb-Team header, which
    # the tracked transport's built-in scrubber doesn't recognise, so a logged/sampled request
    # would otherwise leak it. Responses carrying recipient credentials are additionally kept
    # out of HTTP sample capture — the name-based scrubbers can't recognise those payloads.
    session = make_tracked_session(redact_values=(api_key,), capture=endpoint not in ENDPOINTS_WITH_CREDENTIAL_PAYLOADS)

    if config.scope == HoneycombScope.ENVIRONMENT:
        rows = _fetch_list(session, f"{base_url}{config.path}", headers, logger)
        if rows:
            yield [_sanitize_row(config.name, row) for row in rows]
        return

    if config.scope == HoneycombScope.PER_BOARD:
        yield from _iter_board_views(session, base_url, headers, config, logger, resumable_source_manager)
        return

    if config.scope == HoneycombScope.PER_SLO_TIME_WINDOW:
        yield from _iter_slo_counts_history(session, base_url, headers, config, logger, db_incremental_field_last_value)
        return

    yield from _iter_fan_out(session, base_url, headers, config, logger, resumable_source_manager)


def honeycomb_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HoneycombResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = HONEYCOMB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, str | None]:
    """Confirm the API key is genuine with one cheap probe of the auth endpoint.

    GET /1/auth describes the key and its scopes, so it works for any configuration key
    regardless of which per-resource permissions were granted."""
    url = f"{_base_url(region)}/1/auth"
    try:
        # Redact the key here too — see get_rows() for why the X-Honeycomb-Team header needs it.
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Honeycomb API key. Check the key and that the selected region matches your account."
    return False, f"Honeycomb API error: {response.status_code}"
