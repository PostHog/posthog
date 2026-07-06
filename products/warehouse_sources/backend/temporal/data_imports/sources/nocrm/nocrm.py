import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.settings import (
    NOCRM_ENDPOINTS,
    NoCRMEndpointConfig,
)

# noCRM caps `/leads` at a default of 100 per page; request the max to minimise round-trips against
# the low (~2000 req/day) account quota.
PAGE_SIZE = 100

REQUEST_TIMEOUT_SECONDS = 60

# noCRM hosts every account under `<subdomain>.nocrm.io`. Only the subdomain label is user-supplied,
# so restrict it to the DNS-label charset — this keeps a crafted value from breaking out of the
# `.nocrm.io` origin and pointing the authenticated request somewhere else (SSRF).
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class NoCRMRetryableError(Exception):
    pass


class NoCRMConfigError(Exception):
    """The connector config is malformed (e.g. an invalid subdomain) and can never succeed."""


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user typed to a bare, validated noCRM subdomain label.

    Accepts a bare label (`acme`) or a full host/URL (`acme.nocrm.io`, `https://acme.nocrm.io/`) and
    returns just `acme`. Raises `NoCRMConfigError` when nothing valid remains, so we never build a
    request URL around an attacker-controlled host.
    """
    value = (subdomain or "").strip().lower()
    # Strip scheme and any path if the user pasted a full URL.
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    # Strip the shared apex domain if present, leaving just the account label.
    value = value.removesuffix(".nocrm.io")
    if not _SUBDOMAIN_RE.match(value):
        raise NoCRMConfigError(
            "Invalid noCRM subdomain. Enter just your account's subdomain, e.g. 'acme' for acme.nocrm.io."
        )
    return value


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.nocrm.io/api/v2"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-KEY": api_key,
        "Accept": "application/json",
    }


def _format_updated_after(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC string noCRM's `updated_after` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now.

    If bad source data pushes the `updated_at` cursor past now, every later sync would ask noCRM for
    changes since a future date and get nothing back, wedging the table until real data catches up.
    Asking for changes newer than now is a no-op anyway, so clamping lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_base_params(
    config: NoCRMEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Query params shared by every page of a sync (everything except limit/offset)."""
    params: dict[str, Any] = {}

    if config.default_sort_order:
        params["order"] = config.default_sort_order
        params["direction"] = "asc"

    if (
        config.supports_incremental
        and config.incremental_param
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[config.incremental_param] = _format_updated_after(
            _clamp_future_value_to_now(db_incremental_field_last_value)
        )
        # Sort ascending by the changed field so pages arrive in the order the `asc` watermark expects.
        if config.incremental_sort_order:
            params["order"] = config.incremental_sort_order
            params["direction"] = "asc"

    return params


@dataclasses.dataclass
class NoCRMResumeConfig:
    # Offset (row count already consumed) to resume limit/offset pagination from. The incremental
    # window is recomputed from the job's stable last-value, so only the offset needs persisting.
    offset: int = 0


@retry(
    retry=retry_if_exception_type((NoCRMRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> tuple[list[dict], int | None]:
    """Fetch one page, returning the row list and the `X-TOTAL-COUNT` total when the header is present.

    noCRM list endpoints return a bare JSON array. Over-quota (429) and transient 5xx are retried;
    on 429 noCRM sends `API-RETRY-AFTER`, but tenacity's exponential backoff is a safe fallback that
    keeps us well under the daily cap without parsing the header.
    """
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise NoCRMRetryableError(f"noCRM API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"noCRM API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    body = response.json()
    # List endpoints return a bare array; be defensive about a wrapped object just in case.
    items = body if isinstance(body, list) else body.get("data", [])

    total_header = response.headers.get("X-TOTAL-COUNT")
    total = int(total_header) if total_header is not None and total_header.isdigit() else None

    return items, total


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NoCRMResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    config = NOCRM_ENDPOINTS[endpoint]
    base_url = _base_url(subdomain)
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values`
    # masks the API key in logged URLs and captured samples. `allow_redirects=False` stops a redirect
    # from sending the key to another host. `retry=Retry(total=0)` disables the adapter's own retries
    # so they don't stack on top of the tenacity retry in `_fetch_page`.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0))

    base_params = _build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0

    # Guards against an endpoint that ignores `offset` and re-serves the first page forever: if a page
    # leads with the same id we already saw, pagination isn't advancing, so stop.
    previous_first_id: Any = None

    while True:
        params = {**base_params, "limit": PAGE_SIZE, "offset": offset}
        url = f"{base_url}{config.path}?{urlencode(params)}"

        items, total = _fetch_page(session, url, headers, logger)
        if not items:
            break

        first_id = items[0].get("id") if isinstance(items[0], dict) else None
        if offset > 0 and first_id is not None and first_id == previous_first_id:
            logger.warning(f"noCRM: endpoint {endpoint} did not honour offset pagination, stopping to avoid a loop")
            break
        previous_first_id = first_id

        yield items
        offset += len(items)

        # Terminate on a short final page or once we've consumed the pre-pagination total.
        if len(items) < PAGE_SIZE:
            break
        if total is not None and offset >= total:
            break

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(NoCRMResumeConfig(offset=offset))


def validate_credentials(api_key: str, subdomain: str) -> bool:
    """Probe the cheap `/ping` endpoint to confirm the API key and subdomain are genuine."""
    try:
        url = f"{_base_url(subdomain)}/ping"
    except NoCRMConfigError:
        return False
    try:
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0))
        response = session.get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def nocrm_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NoCRMResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NOCRM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            subdomain=subdomain,
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
        # Leads are requested with `order=last_update&direction=asc` on incremental syncs, and the
        # ResumableSource offset state (not the watermark) drives mid-sync resume, so `asc` matches
        # the framework's incremental checkpointing.
        sort_mode="asc",
    )
