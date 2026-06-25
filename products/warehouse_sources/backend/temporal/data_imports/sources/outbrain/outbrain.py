import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

from django.core.cache import cache

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.settings import (
    OUTBRAIN_BASE_URL,
    OUTBRAIN_ENDPOINTS,
    REPORT_DEFAULT_BACKFILL_DAYS,
    REPORT_LOOKBACK_DAYS,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
PAGE_SIZE = 100
# Periodic reports return one row per day; 500 covers the full default backfill.
REPORT_ROW_LIMIT = 500
# Tokens are valid 30 days but /login is capped at 2 requests/hour, so the
# token is cached across runs and only re-minted when it expires.
TOKEN_CACHE_TTL_SECONDS = 29 * 24 * 60 * 60


class OutbrainRetryableError(Exception):
    pass


@dataclasses.dataclass
class OutbrainResumeConfig:
    # Index of the next fan-out parent (marketer or campaign) to process.
    next_index: int


def _get_session(password: str, token: Optional[str] = None) -> requests.Session:
    secrets = tuple(value for value in (password, token) if value)
    return make_tracked_session(redact_values=secrets)


def _token_cache_key(username: str, password: str) -> str:
    digest = hashlib.sha256(f"{username}:{password}".encode()).hexdigest()[:32]
    return f"data_imports_outbrain_token_{digest}"


def _login(username: str, password: str) -> str:
    # The login response body returns OB-TOKEN-V1 in plaintext, and the token is
    # not known until the response arrives, so it cannot be value-redacted from a
    # captured HTTP sample. The login host is the fixed, trusted Outbrain API
    # (no user-supplied host, so no SSRF concern), so issue it on an untracked
    # session to keep the token out of HTTP sample capture entirely.
    # nosemgrep: data-imports-http-transport-requests-verb — untracked on purpose so the token-bearing login response is never sampled
    response = requests.get(
        f"{OUTBRAIN_BASE_URL}/login",
        auth=(username, password),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    token = response.json().get("OB-TOKEN-V1")
    if not token:
        raise ValueError("Outbrain login returned no OB-TOKEN-V1 token")
    return token


def _get_token(username: str, password: str, force_refresh: bool = False) -> str:
    cache_key = _token_cache_key(username, password)
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    token = _login(username, password)
    cache.set(cache_key, token, TOKEN_CACHE_TTL_SECONDS)
    return token


def validate_credentials(username: str, password: str) -> bool:
    """Confirm the credentials are valid via the cached-token login flow."""
    try:
        _get_token(username, password)
        return True
    except Exception:
        return False


def get_rows(
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OutbrainResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = OUTBRAIN_ENDPOINTS[endpoint]
    token = _get_token(username, password)
    # Build the session with the token in redact_values so it is masked from
    # logged URLs and captured HTTP samples on every data request.
    session = _get_session(password, token)

    @retry(
        retry=retry_if_exception_type((OutbrainRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def fetch(url: str) -> dict[str, Any]:
        nonlocal token, session
        response = session.get(url, headers={"OB-TOKEN-V1": token}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last 30 days; if the cached one has expired mid-sync, re-mint
        # once (the fresh token replaces it in the cache). Rebuild the session so
        # the new token value is registered in redact_values.
        if response.status_code == 401:
            token = _get_token(username, password, force_refresh=True)
            session = _get_session(password, token)
            response = session.get(url, headers={"OB-TOKEN-V1": token}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OutbrainRetryableError(f"Outbrain API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Outbrain API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response.json()

    def rows_of(data: Any, key: str) -> list[dict[str, Any]]:
        items = data.get(key) if isinstance(data, dict) else None
        return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []

    def fetch_paginated(path: str) -> Iterator[list[dict[str, Any]]]:
        offset = 0
        while True:
            params = {"limit": PAGE_SIZE, "offset": offset} if config.paginated else {}
            url = f"{OUTBRAIN_BASE_URL}{path}"
            if params:
                url = f"{url}?{urlencode(params)}"
            rows = rows_of(fetch(url), config.data_key)
            if rows:
                yield rows
            if not config.paginated or len(rows) < PAGE_SIZE:
                return
            offset += len(rows)

    def list_marketer_ids() -> list[str]:
        marketers = rows_of(fetch(f"{OUTBRAIN_BASE_URL}/marketers"), "marketers")
        return [str(m["id"]) for m in marketers if m.get("id")]

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume_config.next_index if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Outbrain: resuming {endpoint} from index {start_index}")

    if config.kind == "marketers":
        yield from fetch_paginated(config.path)
        return

    if config.kind in ("per_marketer", "per_campaign"):
        if config.kind == "per_marketer":
            parents = [
                ("_marketer_id", marketer_id, {"marketer_id": marketer_id}) for marketer_id in list_marketer_ids()
            ]
        else:
            campaign_ids: list[str] = []
            for marketer_id in list_marketer_ids():
                campaigns_config = OUTBRAIN_ENDPOINTS["campaigns"]
                offset = 0
                while True:
                    url = (
                        f"{OUTBRAIN_BASE_URL}/marketers/{quote(marketer_id)}/campaigns?"
                        f"{urlencode({'limit': PAGE_SIZE, 'offset': offset})}"
                    )
                    batch = rows_of(fetch(url), campaigns_config.data_key)
                    campaign_ids.extend(str(c["id"]) for c in batch if c.get("id"))
                    if len(batch) < PAGE_SIZE:
                        break
                    offset += len(batch)
            parents = [("_campaign_id", campaign_id, {"campaign_id": campaign_id}) for campaign_id in campaign_ids]

        for index in range(start_index, len(parents)):
            id_field, parent_id, path_params = parents[index]
            path = config.path.format(**{k: quote(v) for k, v in path_params.items()})
            for page in fetch_paginated(path):
                yield [{**row, id_field: parent_id} for row in page]
            # Save state AFTER yielding so a crash re-yields the in-flight
            # parent (merge dedupes on primary key).
            resumable_source_manager.save_state(OutbrainResumeConfig(next_index=index + 1))
        return

    # Report streams: one date-windowed request per marketer.
    today = datetime.now(tz=UTC).date()
    if config.kind == "snapshot_report":
        window_start = today - timedelta(days=REPORT_LOOKBACK_DAYS)
    else:
        window_start = today - timedelta(days=REPORT_DEFAULT_BACKFILL_DAYS)
        if should_use_incremental_field:
            watermark = _to_date(db_incremental_field_last_value)
            if watermark is not None:
                # Conversions restate for ~30 days — re-pull the lookback window.
                window_start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)

    marketer_ids = list_marketer_ids()
    for index in range(start_index, len(marketer_ids)):
        marketer_id = marketer_ids[index]
        params = urlencode(
            {
                "from": window_start.isoformat(),
                "to": today.isoformat(),
                "breakdown": "daily",
                "limit": REPORT_ROW_LIMIT,
            }
            if config.kind == "periodic_report"
            else {"from": window_start.isoformat(), "to": today.isoformat(), "limit": REPORT_ROW_LIMIT}
        )
        path = config.path.format(marketer_id=quote(marketer_id))
        rows = rows_of(fetch(f"{OUTBRAIN_BASE_URL}{path}?{params}"), config.data_key)

        out: list[dict[str, Any]] = []
        for row in rows:
            enriched = {**row, "_marketer_id": marketer_id}
            if config.kind == "periodic_report":
                metadata_value = row.get("metadata")
                metadata = metadata_value if isinstance(metadata_value, dict) else {}
                row_date = metadata.get("fromDate") or metadata.get("id")
                if not row_date:
                    continue
                enriched["_date"] = row_date
            out.append(enriched)
        if out:
            yield out

        # Save state AFTER yielding so a crash re-yields the in-flight marketer.
        resumable_source_manager.save_state(OutbrainResumeConfig(next_index=index + 1))


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def outbrain_source(
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OutbrainResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OUTBRAIN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys) if config.primary_keys else None,
        partition_count=1,
        partition_size=1,
        # The periodic report walks marketers sequentially and each marketer's
        # rows cover the same window, so the date watermark is only safe to
        # commit once a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
    )
