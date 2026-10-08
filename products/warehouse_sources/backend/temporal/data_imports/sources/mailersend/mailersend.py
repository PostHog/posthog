import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import structlog
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mailersend.settings import (
    MAILERSEND_ENDPOINTS,
    MailerSendEndpointConfig,
)

logger = structlog.get_logger(__name__)

# MailerSend serves every account from a single global base URL (no per-account hostname).
MAILERSEND_BASE_URL = "https://api.mailersend.com/v1"

# Every MailerSend list endpoint is page based and accepts page numbers 1 to 1000. The API keeps
# advertising a `links.next` on page 1000, so following it asks for page 1001 and the request is
# rejected with a 422. Stop at the cap instead and finish the table.
MAILERSEND_MAX_PAGE = 1000

# Fallback lookback for a date-filtered endpoint that declares no retention tiers.
MAILERSEND_DEFAULT_ACTIVITY_DAYS = 30

# Parent resource name for the Activity fan-out. include_from_parent=["id"] injects the parent
# domain's id as `_domains_id`; a data_map renames it to `domain_id` so each activity row carries
# the same key it did before the rest_source migration.
_DOMAINS_PARENT = "domains"


@dataclasses.dataclass(frozen=True)
class MailerSendResumeConfig:
    # Legacy fields kept (with defaults) so resume state saved by the pre-migration source still
    # deserializes via `dataclass(**saved)`. New runs checkpoint through `fanout_state` — the
    # rest_source paginator/fan-out snapshot. If only the legacy fields are present we start that
    # endpoint fresh; full-refresh replaces and Activity's merge dedupes, so nothing is lost.
    next_page: int = 1
    domain_id: str | None = None
    fanout_state: dict[str, Any] | None = None


def _page_number(url: Optional[str]) -> int:
    """The page a MailerSend pagination link points at; 1 when the link carries no page param."""
    if not url:
        return 1
    values = parse_qs(urlsplit(url).query).get("page")
    if not values:
        return 1
    try:
        return int(values[0])
    except ValueError:
        return 1


class MailerSendPaginator(JSONResponsePaginator):
    """Follows `links.next` but never past MailerSend's last accepted page."""

    def __init__(self) -> None:
        super().__init__(next_url_path="links.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and _page_number(self._next_url) > MAILERSEND_MAX_PAGE:
            logger.warning(
                "mailersend.page_cap_reached",
                max_page=MAILERSEND_MAX_PAGE,
            )
            self._has_next_page = False


def _to_datetime(value: Any) -> datetime:
    """Coerce an incremental cursor value into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    # ISO 8601 string (MailerSend returns e.g. "2021-08-31T13:43:35.000000Z").
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _activity_date_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    lookback_days: int,
) -> SyncWindow[int]:
    """Build the required date_from/date_to window for the Activity endpoint as Unix timestamps.

    MailerSend requires both bounds, rejects date_from >= date_to, and rejects a window that
    reaches back further than the account's activity retention. `lookback_days` is the retention
    tier being tried, so it bounds the first-sync lookback and also clamps an incremental cursor
    that has fallen behind retention. On incremental syncs the window starts at the last-seen
    created_at; merge upsert dedupes the inclusive boundary row.
    """
    now = datetime.now(UTC)
    earliest = now - timedelta(days=lookback_days)
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        date_from = max(_to_datetime(db_incremental_field_last_value), earliest)
    else:
        date_from = earliest

    if date_from >= now:
        # A future-dated cursor would make date_from >= date_to and 422 the request; clamp it.
        date_from = now - timedelta(seconds=1)

    return SyncWindow(start=int(date_from.timestamp()), end=int(now.timestamp()))


def check_credentials(api_token: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe a cheap endpoint to confirm the token is genuine.

    MailerSend tokens are scoped per sending domain with granular permissions, so a valid token may
    legitimately lack the "Domains" read scope. We accept a 403 at source-create time (schema_name is
    None) and only reject an outright 401. Per-schema scope gaps surface later via the sync-time
    non-retryable error handling.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{MAILERSEND_BASE_URL}/domains?limit=10",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )

    if status is None:
        return False, "Could not reach MailerSend. Please check your connection and try again."
    if status == 200:
        return True, None
    if status == 403 and schema_name is None:
        return True, None
    if status in (401, 403):
        return False, "Invalid or insufficiently-scoped MailerSend API token."
    return False, f"Unexpected response from MailerSend (status {status})."


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": MAILERSEND_BASE_URL,
        # Auth (Bearer) is supplied via framework auth so the token is redacted from logs and errors;
        # only the non-secret content-negotiation headers are set here.
        "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        # MailerSend returns the next page as a full URL under `links.next`, null on the last page.
        "paginator": MailerSendPaginator(),
        # `links.next` is followed verbatim, so pin every request (and the Bearer token) to
        # api.mailersend.com and refuse redirects — a tampered/off-host `links.next` or a 3xx can't
        # retarget the credentialed request. `allowed_hosts=[]` means base-host only.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _activity_resource(
    api_token: str,
    endpoint: str,
    config: MailerSendEndpointConfig,
    team_id: int,
    job_id: str,
    window: SyncWindow[int],
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_state: Optional[dict[str, Any]],
) -> Any:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": _DOMAINS_PARENT,
                "endpoint": {
                    "path": "/domains",
                    "params": {"limit": config.page_size},
                    "data_selector": "data",
                },
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "domain_id": {
                            "type": "resolve",
                            "resource": _DOMAINS_PARENT,
                            "field": "id",
                        },
                        "limit": config.page_size,
                        # The window is computed once per run and rides as static query params —
                        # MailerSend filters server-side on created_at within [date_from, date_to].
                        "date_from": window.start,
                        "date_to": window.end,
                    },
                    "data_selector": "data",
                },
                "include_from_parent": ["id"],
                # activity ids are only unique within a domain, so stamp each row with its
                # domain_id — the [domain_id, id] primary key stays unique table-wide.
                "data_map": rename_parent_fields(_DOMAINS_PARENT, {"id": "domain_id"}),
            },
        ],
    }
    resources = {
        resource.name: resource
        for resource in rest_api_resources(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=resume_hook,
            initial_paginator_state=initial_state,
        )
    }
    return resources[endpoint]


def _activity_pages(
    api_token: str,
    endpoint: str,
    config: MailerSendEndpointConfig,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_state: Optional[dict[str, Any]],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[Any]]:
    """Page the Activity endpoint, narrowing the date window when MailerSend rejects it.

    How far back activity can be read is set by the account's plan and no endpoint reports it, so
    the only way to find it is to ask. Start at the widest retention tier and step down a tier each
    time a request comes back rejected, so an account on any plan syncs the activity it does keep.
    Once rows have come back the window was accepted, and a later rejection is a real failure.
    """
    tiers = config.window_tiers_days or (MAILERSEND_DEFAULT_ACTIVITY_DAYS,)
    for index, lookback_days in enumerate(tiers):
        window = _activity_date_window(should_use_incremental_field, db_incremental_field_last_value, lookback_days)
        rows_yielded = False
        try:
            for page in _activity_resource(
                api_token, endpoint, config, team_id, job_id, window, resume_hook, initial_state
            ):
                rows_yielded = rows_yielded or bool(page)
                yield page
            return
        except HTTPError as error:
            window_rejected = error.response is not None and error.response.status_code == 422
            if rows_yielded or not window_rejected or index == len(tiers) - 1:
                raise
            logger.warning(
                "mailersend.activity_window_narrowed",
                rejected_lookback_days=lookback_days,
                next_lookback_days=tiers[index + 1],
            )


def mailersend_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailerSendResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MAILERSEND_ENDPOINTS[endpoint]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state is not None:
            initial_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist AFTER a page yields (framework saves only when a next page/parent remains) so a
        # crash re-yields the last chunk rather than skipping it; merge/replace dedupes the overlap.
        if state is not None:
            resumable_source_manager.save_state(MailerSendResumeConfig(fanout_state=state))

    items: Callable[[], Any]
    if config.fan_out_over_domains:
        items = partial(
            _activity_pages,
            api_token=api_token,
            endpoint=endpoint,
            config=config,
            team_id=team_id,
            job_id=job_id,
            resume_hook=save_checkpoint,
            initial_state=initial_state,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
    else:
        simple_config: RESTAPIConfig = {
            "client": _client_config(api_token),
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {"limit": config.page_size},
                        "data_selector": "data",
                    },
                }
            ],
        }
        resource = rest_api_resource(
            simple_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
        items = lambda: resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # MailerSend's Activity endpoint doesn't document its sort order. "desc" is the safe choice:
        # the incremental watermark is only committed once the full window has been read, so an
        # interrupted sync can't checkpoint past unfetched rows and lose them.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
