import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.settings import (
    REPORT_DEFAULT_BACKFILL_DAYS,
    REPORT_LOOKBACK_DAYS,
    REPORT_WINDOW_DAYS,
    TABOOLA_API_BASE_URL,
    TABOOLA_ENDPOINTS,
    TABOOLA_TOKEN_URL,
)

REQUEST_TIMEOUT_SECONDS = 120
# Rate limits are plan/endpoint dependent and poorly documented; back off on 429.
MAX_RETRY_ATTEMPTS = 5


class TaboolaRetryableError(Exception):
    pass


@dataclasses.dataclass
class TaboolaResumeConfig:
    # Reports: the start date (yyyy-mm-dd) of the next unfetched window.
    # campaign_items: the index of the next campaign to fetch items for.
    next_window_start: Optional[str] = None
    next_campaign_index: Optional[int] = None


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _encode_path_segment(value: str) -> str:
    """Percent-encode a value before interpolating it into a URL path.

    ``account_id`` is a non-secret field a user can edit on an existing source while the
    saved credentials are preserved. Without encoding, a value containing ``/``, ``?``,
    ``#``, or ``.`` could redirect the authenticated request to an unintended Backstage
    endpoint. Encoding with ``safe=""`` keeps every delimiter inside the single path segment.
    """
    return quote(value, safe="")


def _mint_token(session: requests.Session, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a bearer token (short-lived)."""
    response = session.post(
        TABOOLA_TOKEN_URL,
        data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    # Transient token-endpoint failures must be retryable so the re-mint inside the
    # @retry-decorated fetch backs off instead of failing the whole sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise TaboolaRetryableError(f"Taboola token endpoint error (retryable): status={response.status_code}")
    response.raise_for_status()
    return response.json()["access_token"]


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


def validate_credentials(client_id: str, client_secret: str) -> bool:
    """Confirm the credentials are valid by minting a token."""
    try:
        _mint_token(_get_session(client_secret), client_id, client_secret)
        return True
    except Exception:
        return False


def get_rows(
    client_id: str,
    client_secret: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TaboolaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TABOOLA_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    token = _mint_token(session, client_id, client_secret)
    account_base = f"{TABOOLA_API_BASE_URL}/{_encode_path_segment(account_id)}"

    @retry(
        retry=retry_if_exception_type((TaboolaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch(url: str) -> dict[str, Any]:
        nonlocal token
        response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Access tokens are short-lived; re-mint once if one expires mid-sync.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret)
            response = session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise TaboolaRetryableError(f"Taboola API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Taboola API error: status={response.status_code}, body={response.text[:500]}, url={url}")
            response.raise_for_status()

        return response.json()

    def results_of(data: Any) -> list[dict[str, Any]]:
        items = data.get("results") if isinstance(data, dict) else None
        return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.kind == "entity":
        items = results_of(fetch(f"{account_base}{config.path}"))
        if items:
            yield items
        return

    if config.kind == "campaign_items":
        campaigns = results_of(fetch(f"{account_base}/campaigns/"))
        campaign_ids = [str(campaign["id"]) for campaign in campaigns if campaign.get("id") is not None]

        start_index = 0
        if resume_config is not None and resume_config.next_campaign_index is not None:
            start_index = resume_config.next_campaign_index
            logger.debug(f"Taboola: resuming campaign_items from campaign index {start_index}")

        for index in range(start_index, len(campaign_ids)):
            campaign_id = campaign_ids[index]
            items = results_of(fetch(f"{account_base}/campaigns/{_encode_path_segment(campaign_id)}/items/"))
            if items:
                yield items
            # Save state AFTER yielding so a crash re-yields the in-flight
            # campaign (merge dedupes on primary key).
            resumable_source_manager.save_state(TaboolaResumeConfig(next_campaign_index=index + 1))
        return

    if config.kind == "snapshot_report":
        # Trailing-window aggregate (rows carry no date) — full refresh.
        end = datetime.now(tz=UTC).date()
        start = end - timedelta(days=REPORT_LOOKBACK_DAYS)
        params = urlencode({"start_date": start.isoformat(), "end_date": end.isoformat()})
        items = results_of(fetch(f"{account_base}{config.path}?{params}"))
        if items:
            yield items
        return

    # Date-windowed report. Recent rows restate, so incremental runs re-pull a
    # trailing lookback window before the watermark.
    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=REPORT_DEFAULT_BACKFILL_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)

    if resume_config is not None and resume_config.next_window_start:
        resumed = _to_date(resume_config.next_window_start)
        if resumed is not None and resumed > start:
            start = resumed
            logger.debug(f"Taboola: resuming {endpoint} from window start {start.isoformat()}")

    while start <= today:
        window_end = min(start + timedelta(days=REPORT_WINDOW_DAYS - 1), today)
        params = urlencode({"start_date": start.isoformat(), "end_date": window_end.isoformat()})
        items = results_of(fetch(f"{account_base}{config.path}?{params}"))
        if items:
            yield items

        start = window_end + timedelta(days=1)
        if start <= today:
            # Save state AFTER yielding so a crash re-yields the in-flight window.
            resumable_source_manager.save_state(TaboolaResumeConfig(next_window_start=start.isoformat()))


def taboola_source(
    client_id: str,
    client_secret: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TaboolaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TABOOLA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            account_id=account_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        # Report windows are walked oldest-first, so the date watermark only
        # moves forward; the lookback re-pull happens below the saved watermark
        # and merges on (date, campaign).
        sort_mode="asc",
    )
