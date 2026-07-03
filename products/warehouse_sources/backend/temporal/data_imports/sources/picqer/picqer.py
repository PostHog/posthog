import re
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

from requests import Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import (
    PAGE_SIZE,
    PICQER_ENDPOINTS,
    PicqerEndpointConfig,
)

PICQER_API_PATH = "/api/v1"

# Picqer requires a descriptive User-Agent identifying the application plus contact info.
PICQER_USER_AGENT = "PostHog (https://posthog.com - hey@posthog.com)"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<account>.picqer.com`.
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclasses.dataclass
class PicqerResumeConfig:
    # Next offset to fetch. None means "start from offset 0".
    offset: int | None = None


def normalize_account(account: str) -> str:
    """Reduce user input to a bare, validated Picqer account subdomain.

    Accepts either the full host (``yourcompany.picqer.com``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<account>.picqer.com``.
    """
    cleaned = account.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".picqer.com")
    if not _ACCOUNT_RE.match(cleaned):
        raise ValueError(
            f"Invalid Picqer account: {account!r}. Enter just your account name, e.g. 'yourcompany' "
            "for yourcompany.picqer.com."
        )
    return cleaned


def _base_url(account: str) -> str:
    return f"https://{normalize_account(account)}.picqer.com{PICQER_API_PATH}"


def to_picqer_datetime(value: Any) -> str:
    """Format an incremental cursor value into Picqer's ``YYYY-MM-DD HH:MM:SS`` filter format.

    The persisted last value arrives as a ``datetime`` for DateTime incremental fields. Picqer's
    timestamps carry no timezone, so we format the wall-clock components directly (no timezone
    shift) to round-trip against the same values the API returned.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S")
    # Defensive: an ISO string ("2013-07-17T16:01:42") reduced to Picqer's space-separated form.
    return str(value).replace("T", " ")[:19]


def _make_session(api_key: str) -> Session:
    session = make_tracked_session(redact_values=(api_key,))
    session.headers.update({"User-Agent": PICQER_USER_AGENT, "Accept": "application/json"})
    # Picqer uses HTTP Basic auth with the API key as the username and a blank password.
    session.auth = (api_key, "")
    return session


def _fetch_page(session: Session, url: str, params: dict[str, Any]) -> Any:
    """Fetch a single Picqer list page. Rate limits (429) and transient 5xx are retried by the
    tracked session's adapter; a persistent auth/permission error raises via `raise_for_status`."""
    response = session.get(url, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def _build_params(
    config: PicqerEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Query params kept on every offset page. Picqer applies a filter server-side across the whole
    result set, so the `updated_after` cursor narrows every page and pagination ends naturally. Only
    endpoints with a genuine update-based filter are ever narrowed — full-refresh endpoints must
    never leak a cursor into the request."""
    params: dict[str, Any] = {}
    if (
        config.supports_incremental
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
        and config.incremental_filter_param is not None
    ):
        params[config.incremental_filter_param] = to_picqer_datetime(db_incremental_field_last_value)
    return params


def get_rows(
    account: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PicqerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PICQER_ENDPOINTS[endpoint]
    url = f"{_base_url(account)}{config.path}"
    session = _make_session(api_key)

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None and resume.offset is not None else 0
    if offset:
        logger.debug(f"Picqer: resuming {endpoint} from offset {offset}")

    while True:
        items = _fetch_page(session, url, {**params, "offset": offset})

        if not isinstance(items, list) or not items:
            break

        yield items

        # A short page means we've reached the end of the (optionally filtered) result set.
        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-runs from the next page rather than losing the last one —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(PicqerResumeConfig(offset=offset))


def picqer_source(
    account: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PicqerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PICQER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account=account,
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
    )


def validate_credentials(account: str, api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap Picqer list endpoint to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the account is malformed so the caller can surface a precise message. A
    ``403`` (valid key, insufficient scope) is treated as reachable — fulfilment keys legitimately
    have narrow scopes and per-table access is reported separately.
    """
    url = f"{_base_url(account)}/warehouses"
    try:
        response = _make_session(api_key).get(url, params={"offset": 0}, timeout=10)
    except Exception:
        return False, None
    return response.status_code in (200, 403), response.status_code
