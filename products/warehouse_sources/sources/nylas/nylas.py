import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import orjson
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.nylas.settings import (
    AGENT_ACCOUNT_PROVIDER,
    DEFAULT_EVENT_HISTORY_DAYS,
    DEFAULT_GRANT_SCOPE,
    DEFAULT_REGION,
    EVENT_FUTURE_DAYS,
    EVENT_NO_CANCELLED_PROVIDERS,
    EVENT_UPDATED_FILTER_MAX_AGE_DAYS,
    EVENT_UPDATED_FILTER_PROVIDERS,
    GOOGLE_UPDATED_FILTER_TOO_OLD,
    GRANTS_PAGE_SIZE,
    ICLOUD_MAX_EVENT_WINDOW_DAYS,
    ICLOUD_PROVIDER,
    NYLAS_ENDPOINTS,
    NYLAS_REGION_BASE_URLS,
    WEBHOOK_TRIGGERS,
    NylasEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ExternalWebhookInfo,
    ResumableSourceManager,
    SourceResponse,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSourceManager,
    WebhookSyncResult,
    make_tracked_session,
    validate_via_probe,
)
from products.warehouse_sources.sources.sdk.internals import table_from_py_list

REQUEST_TIMEOUT_SECONDS = 60
WEBHOOK_REQUEST_TIMEOUT_SECONDS = 30

WEBHOOK_DESCRIPTION = "PostHog data warehouse"

UNSUPPORTED_PROVIDER_ERROR = "Method not supported for provider"


@dataclasses.dataclass(frozen=True)
class NylasResumeConfig:
    # The grant being read, for the endpoints that are read once per grant.
    grant_id: str | None = None
    # The request series being read inside that grant: a calendar and time range for events,
    # an empty string for the endpoints with one series per grant.
    unit: str | None = None
    # Cursor of the next page of that series. None means its first page.
    page_token: str | None = None
    # Offset of the next page of the grants list.
    offset: int | None = None


@dataclasses.dataclass(frozen=True)
class NylasConnection:
    api_key: str
    region: str = DEFAULT_REGION
    grant_scope: str = DEFAULT_GRANT_SCOPE
    # When set, only these grants are synced, on top of `grant_scope`.
    grant_ids: frozenset[str] = frozenset()
    include_message_bodies: bool = True
    event_history_days: int = DEFAULT_EVENT_HISTORY_DAYS

    @property
    def base_url(self) -> str:
        return base_url_for_region(self.region)

    @property
    def filters_grants(self) -> bool:
        return self.grant_scope != DEFAULT_GRANT_SCOPE or bool(self.grant_ids)


def base_url_for_region(region: str | None) -> str:
    try:
        return NYLAS_REGION_BASE_URLS[(region or DEFAULT_REGION).lower()]
    except KeyError:
        raise ValueError(f"Unknown Nylas region: {region}")


def parse_grant_ids(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(part.strip() for part in value.replace("\n", ",").split(",") if part.strip())


def _make_session(api_key: str) -> requests.Session:
    # capture=False: responses hold email content and, for the webhook calls, the signing secret.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        capture=False,
    )


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    cleaned = {key: value for key, value in params.items() if value is not None}
    return f"{base_url}{path}?{urlencode(cleaned)}" if cleaned else f"{base_url}{path}"


def _to_unix_seconds(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _to_unix_seconds(parsed)
    return None


def _error_message(response: requests.Response | None) -> str | None:
    if response is None:
        return None
    try:
        error = response.json().get("error")
    except Exception:
        return None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return None


def validate_credentials(api_key: str, region: str | None) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: _make_session(api_key),
        _build_url(base_url_for_region(region), "/v3/grants", {"limit": 1}),
    )


def _fetch(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


def _grant_in_scope(grant: dict[str, Any], connection: NylasConnection) -> bool:
    grant_id = grant.get("id")
    if not grant_id:
        return False
    if connection.grant_ids and grant_id not in connection.grant_ids:
        return False
    is_agent_account = grant.get("provider") == AGENT_ACCOUNT_PROVIDER
    if connection.grant_scope == "agent_accounts":
        return is_agent_account
    if connection.grant_scope == "connected_accounts":
        return not is_agent_account
    return True


def _iter_grant_pages(
    session: requests.Session, connection: NylasConnection, start_offset: int = 0
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Yield (grants in scope, offset of the next page or None) for each page of the grants list."""
    offset = start_offset
    while True:
        # Oldest first, so a grant created during the walk lands on the last page instead of
        # shifting the pages already read.
        params = {"limit": GRANTS_PAGE_SIZE, "offset": offset, "sort_by": "created_at", "order_by": "asc"}
        page = _fetch(session, _build_url(connection.base_url, "/v3/grants", params)).get("data") or []
        has_more = len(page) >= GRANTS_PAGE_SIZE
        offset += len(page)
        yield [grant for grant in page if _grant_in_scope(grant, connection)], offset if has_more else None
        if not has_more:
            return


def list_syncable_grants(session: requests.Session, connection: NylasConnection) -> list[dict[str, Any]]:
    """The in-scope grants that Nylas can still read. An invalid grant fails every request."""
    return [
        grant
        for grants, _ in _iter_grant_pages(session, connection)
        for grant in grants
        if grant.get("grant_status", "valid") == "valid"
    ]


def list_syncable_grant_ids(session: requests.Session, connection: NylasConnection) -> list[str]:
    return [grant["id"] for grant in list_syncable_grants(session, connection)]


def _get_grant_rows(
    session: requests.Session,
    connection: NylasConnection,
    resumable_source_manager: ResumableSourceManager[NylasResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume is not None and resume.offset else 0

    for grants, next_offset in _iter_grant_pages(session, connection, start_offset):
        if next_offset is not None:
            resumable_source_manager.save_state(NylasResumeConfig(offset=next_offset))
        if grants:
            yield grants
        else:
            resumable_source_manager.safe_point()


def _api_key_still_valid(session: requests.Session, connection: NylasConnection) -> bool:
    try:
        _fetch(session, _build_url(connection.base_url, "/v3/grants", {"limit": 1}))
    except requests.RequestException:
        return False
    return True


def _grant_is_gone(session: requests.Session, connection: NylasConnection, grant_id: str) -> bool:
    try:
        response = session.get(f"{connection.base_url}/v3/grants/{grant_id}", timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        return False
    return response.status_code == 404


def _is_grant_level_failure(
    error: requests.HTTPError, session: requests.Session, connection: NylasConnection, grant_id: str
) -> bool:
    """True when only this grant is unreadable, so the sync can move on to the next one.

    A grant can be deleted or lose its provider authorization between the grants list and the
    read. Nylas answers both with a 4xx. A 401 or 403 is also what a revoked API key returns, and
    skipping every grant on that would end the sync with no rows and no error, so the key is
    checked again before the grant is skipped. Nylas also answers 404 to some requests it cannot
    serve for a grant that exists, so a 404 only skips a grant that is really gone.
    """
    status = error.response.status_code if error.response is not None else None
    if status == 404:
        return _grant_is_gone(session, connection, grant_id)
    if status == 400:
        # A grant whose provider has no such data, such as email on a virtual calendar.
        return UNSUPPORTED_PROVIDER_ERROR in (_error_message(error.response) or "")
    if status in (401, 403):
        return _api_key_still_valid(session, connection)
    return False


def _shape_row(row: dict[str, Any], grant_id: str, endpoint: str, include_message_bodies: bool) -> dict[str, Any]:
    shaped = {**row, "grant_id": row.get("grant_id") or grant_id}
    if include_message_bodies:
        return shaped
    if endpoint == "messages":
        shaped.pop("body", None)
    elif endpoint == "threads" and isinstance(shaped.get("latest_draft_or_message"), dict):
        shaped["latest_draft_or_message"] = {
            key: value for key, value in shaped["latest_draft_or_message"].items() if key != "body"
        }
    return shaped


@dataclasses.dataclass(frozen=True)
class _RequestUnit:
    """One paginated request series inside a grant."""

    key: str
    params: dict[str, Any]


def _event_windows(provider: str | None, history_days: int, today: date) -> list[tuple[int, int]]:
    """Time ranges that cover the configured event history and the coming year, as Unix seconds.

    The bounds sit on UTC midnight, so a run that resumes on the same day builds the same ranges.
    """
    midnight = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    start = midnight - timedelta(days=max(history_days, 0))
    end = midnight + timedelta(days=EVENT_FUTURE_DAYS)
    if provider != ICLOUD_PROVIDER:
        return [(int(start.timestamp()), int(end.timestamp()))]

    windows: list[tuple[int, int]] = []
    while start < end:
        window_end = min(start + timedelta(days=ICLOUD_MAX_EVENT_WINDOW_DAYS), end)
        windows.append((int(start.timestamp()), int(window_end.timestamp())))
        start = window_end
    return windows


def _list_calendar_ids(session: requests.Session, connection: NylasConnection, grant_id: str) -> list[str]:
    calendar_ids: list[str] = []
    page_token: str | None = None
    while True:
        params = {"limit": NYLAS_ENDPOINTS["calendars"].page_size, "page_token": page_token}
        data = _fetch(session, _build_url(connection.base_url, f"/v3/grants/{grant_id}/calendars", params))
        calendar_ids.extend(row["id"] for row in data.get("data") or [] if isinstance(row, dict) and row.get("id"))
        page_token = data.get("next_cursor") or None
        if not page_token:
            return calendar_ids


def _units_for_grant(
    session: requests.Session,
    connection: NylasConnection,
    config: NylasEndpointConfig,
    grant: dict[str, Any],
    incremental_after: int | None,
    today: date,
) -> list[_RequestUnit]:
    params: dict[str, Any] = {"limit": config.page_size, **config.extra_params}
    provider = grant.get("provider")

    if config.name != "events":
        if incremental_after is not None and config.incremental_param:
            params[config.incremental_param] = incremental_after
        return [_RequestUnit(key="", params=params)]

    # A provider without the filter, or a watermark too old for it, gets the whole time range
    # again. The merge removes the rows read twice.
    oldest_filter = int((datetime.combine(today, datetime.min.time(), tzinfo=UTC)).timestamp()) - (
        EVENT_UPDATED_FILTER_MAX_AGE_DAYS * 86400
    )
    if (
        incremental_after is not None
        and config.incremental_param
        and provider in EVENT_UPDATED_FILTER_PROVIDERS
        and incremental_after >= oldest_filter
    ):
        params[config.incremental_param] = incremental_after
    if provider not in EVENT_NO_CANCELLED_PROVIDERS:
        params["show_cancelled"] = "true"

    return [
        _RequestUnit(
            key=f"{calendar_id}|{start}", params={**params, "calendar_id": calendar_id, "start": start, "end": end}
        )
        for calendar_id in _list_calendar_ids(session, connection, grant["id"])
        for start, end in _event_windows(provider, connection.event_history_days, today)
    ]


class _UpdateFilterTooOld(Exception):
    """The provider refused the incremental filter because the watermark is too far back."""


def _update_filter_too_old(error: requests.HTTPError) -> bool:
    if error.response is None:
        return False
    return GOOGLE_UPDATED_FILTER_TOO_OLD in error.response.text


@dataclasses.dataclass(frozen=True)
class _GrantWalk:
    session: requests.Session
    connection: NylasConnection
    config: NylasEndpointConfig
    logger: FilteringBoundLogger
    resumable_source_manager: ResumableSourceManager[NylasResumeConfig]

    def skip_or_raise(self, error: requests.HTTPError, grant_id: str) -> None:
        if not _is_grant_level_failure(error, self.session, self.connection, grant_id):
            raise error
        status = error.response.status_code if error.response is not None else None
        self.logger.warning(f"Nylas: skipping {self.config.name} for grant_id={grant_id}, status={status}")

    def fetch_page(self, grant_id: str, params: dict[str, Any], page_token: str | None) -> dict[str, Any]:
        path = self.config.path.format(grant_id=grant_id)
        url = _build_url(self.connection.base_url, path, {**params, "page_token": page_token})
        try:
            return _fetch(self.session, url)
        except requests.HTTPError as error:
            if self.config.incremental_param in params and _update_filter_too_old(error):
                raise _UpdateFilterTooOld from error
            self.skip_or_raise(error, grant_id)
            return {}

    def units(self, grant: dict[str, Any], incremental_after: int | None, today: date) -> list[_RequestUnit]:
        try:
            return _units_for_grant(self.session, self.connection, self.config, grant, incremental_after, today)
        except requests.HTTPError as error:
            self.skip_or_raise(error, grant["id"])
            return []


def _get_unit_rows(
    walk: _GrantWalk,
    grant_id: str,
    units: list[_RequestUnit],
    page_token: str | None,
    next_grant: NylasResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    """Read every request series of one grant. `page_token` is the saved cursor of the first one."""
    manager = walk.resumable_source_manager
    for unit_index, unit in enumerate(units):
        after_unit = (
            NylasResumeConfig(grant_id=grant_id, unit=units[unit_index + 1].key)
            if unit_index + 1 < len(units)
            else next_grant
        )

        params = unit.params
        while True:
            try:
                data = walk.fetch_page(grant_id, params, page_token)
            except _UpdateFilterTooOld:
                params = {key: value for key, value in params.items() if key != walk.config.incremental_param}
                continue
            rows = [
                _shape_row(row, grant_id, walk.config.name, walk.connection.include_message_bodies)
                for row in data.get("data") or []
                if isinstance(row, dict)
            ]
            page_token = data.get("next_cursor") or None

            next_position = (
                NylasResumeConfig(grant_id=grant_id, unit=unit.key, page_token=page_token) if page_token else after_unit
            )
            if next_position is not None:
                manager.save_state(next_position)
            if rows:
                yield rows
            else:
                manager.safe_point()

            if not page_token:
                break


def _resume_units(units: list[_RequestUnit], resume: NylasResumeConfig | None) -> tuple[list[_RequestUnit], str | None]:
    """The series still to read in the bookmarked grant, and the cursor of the first one."""
    unit_keys = [unit.key for unit in units]
    # A bookmarked series that is gone restarts the grant.
    if resume is None or resume.unit not in unit_keys:
        return units, None
    return units[unit_keys.index(resume.unit) :], resume.page_token


def _get_per_grant_rows(
    session: requests.Session,
    connection: NylasConnection,
    config: NylasEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NylasResumeConfig],
    incremental_after: int | None,
) -> Iterator[list[dict[str, Any]]]:
    walk = _GrantWalk(session, connection, config, logger, resumable_source_manager)
    grants = list_syncable_grants(session, connection)
    grant_ids = [grant["id"] for grant in grants]
    today = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # A bookmarked grant that is gone restarts the walk. The merge removes the rows read twice.
    if resume is not None and resume.grant_id in grant_ids:
        grants = grants[grant_ids.index(resume.grant_id) :]
        logger.debug(f"Nylas: resuming {config.name} from grant_id={resume.grant_id}")
    else:
        resume = None

    for grant_index, grant in enumerate(grants):
        next_grant = (
            NylasResumeConfig(grant_id=grants[grant_index + 1]["id"]) if grant_index + 1 < len(grants) else None
        )
        units, page_token = _resume_units(
            walk.units(grant, incremental_after, today), resume if grant_index == 0 else None
        )

        if not units:
            if next_grant is not None:
                resumable_source_manager.save_state(next_grant)
            resumable_source_manager.safe_point()
            continue

        yield from _get_unit_rows(walk, grant["id"], units, page_token, next_grant)


def get_rows(
    connection: NylasConnection,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NylasResumeConfig],
    incremental_after: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NYLAS_ENDPOINTS[endpoint]
    session = _make_session(connection.api_key)

    if not config.per_grant:
        yield from _get_grant_rows(session, connection, resumable_source_manager)
        return

    yield from _get_per_grant_rows(session, connection, config, logger, resumable_source_manager, incremental_after)


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, (str, bytes)):
        try:
            value = orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    return dict(value) if isinstance(value, dict) else None


def make_webhook_table_transformer(
    connection: NylasConnection, config: NylasEndpointConfig, allowed_grant_ids: Callable[[], frozenset[str] | None]
) -> Callable[[pa.Table], pa.Table]:
    """Build the transformer that turns a batch of notifications into rows of one table.

    A notification is the envelope `{type, time, data: {object}}`. One batch can hold several
    notifications for one object (created, then updated, or a redelivery), and the merge only
    removes duplicates across syncs, so the batch keeps the newest one per primary key.

    A Nylas webhook covers every grant of the application, so notifications for grants outside the
    configured scope are dropped here. `allowed_grant_ids` returns None when every grant is in scope.
    """

    def transform(table: pa.Table) -> pa.Table:
        if "data" not in table.column_names:
            return table_from_py_list([])

        allowed = allowed_grant_ids()
        times = table.column("time").to_pylist() if "time" in table.column_names else [None] * table.num_rows
        types = table.column("type").to_pylist() if "type" in table.column_names else [None] * table.num_rows

        latest: dict[tuple[str, ...], tuple[int, dict[str, Any]]] = {}
        for data, sent_at, event_type in zip(table.column("data").to_pylist(), times, types):
            payload = _as_dict(data)
            row = _as_dict(payload.get("object")) if payload else None
            if not row or row.get("object") != config.webhook_object_type:
                continue
            if any(not row.get(key) for key in config.primary_keys):
                continue
            if allowed is not None and row["grant_id"] not in allowed:
                continue
            if isinstance(event_type, str) and event_type.startswith("event.deleted"):
                # The notification only names the event. `cancelled` is the status the API
                # gives a deleted event, so the row reads the same as a polled one.
                row["status"] = "cancelled"
            row = _shape_row(row, row["grant_id"], config.name, connection.include_message_bodies)

            key = tuple(str(row[field]) for field in config.primary_keys)
            timestamp = _to_unix_seconds(sent_at) or 0
            # Later rows win ties, so arrival order decides between equal timestamps.
            if key not in latest or timestamp >= latest[key][0]:
                latest[key] = (timestamp, row)

        return table_from_py_list([row for _, row in latest.values()])

    return transform


def nylas_source(
    connection: NylasConnection,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NylasResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NYLAS_ENDPOINTS[endpoint]

    incremental_after: int | None = None
    if should_use_incremental_field and config.incremental_param:
        watermark = _to_unix_seconds(db_incremental_field_last_value)
        # The docs don't say whether the filter includes its bound, so read the watermark second
        # again. The merge removes the rows read twice.
        incremental_after = max(watermark - 1, 0) if watermark is not None else None

    webhook_enabled = False
    if config.webhook_object_type:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def allowed_grant_ids() -> frozenset[str] | None:
        if not connection.filters_grants:
            return None
        return frozenset(list_syncable_grant_ids(_make_session(connection.api_key), connection))

    def items() -> Any:
        if webhook_enabled:
            cached: list[frozenset[str] | None] = []

            def cached_allowed_grant_ids() -> frozenset[str] | None:
                if not cached:
                    cached.append(allowed_grant_ids())
                return cached[0]

            return webhook_source_manager.get_items(
                table_transformer=make_webhook_table_transformer(connection, config, cached_allowed_grant_ids)
            )
        return get_rows(
            connection=connection,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            incremental_after=incremental_after,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # Rows arrive grant by grant, newest first within a grant, so there is no order across the run.
        sort_mode=None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _format_request_error(error: requests.RequestException) -> str:
    response = error.response
    if response is None:
        return f"Could not reach Nylas: {error}"
    return _error_message(response) or f"Nylas returned status {response.status_code}"


def _list_webhooks(session: requests.Session, base_url: str) -> list[dict[str, Any]]:
    response = session.get(f"{base_url}/v3/webhooks", timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json().get("data")
    return [webhook for webhook in data if isinstance(webhook, dict)] if isinstance(data, list) else []


def _find_webhook_by_url(session: requests.Session, base_url: str, webhook_url: str) -> dict[str, Any] | None:
    return next(
        (webhook for webhook in _list_webhooks(session, base_url) if webhook.get("webhook_url") == webhook_url), None
    )


def create_webhook(api_key: str, region: str | None, webhook_url: str) -> WebhookCreationResult:
    base_url = base_url_for_region(region)
    session = _make_session(api_key)
    try:
        existing = _find_webhook_by_url(session, base_url, webhook_url)
        if existing is not None and existing.get("id"):
            # Nylas only returns the secret on create and on rotate, so a webhook left by an
            # earlier attempt gets a new secret rather than a duplicate webhook.
            webhook_id = existing["id"]
            response = session.put(
                f"{base_url}/v3/webhooks/{webhook_id}",
                json={"trigger_types": list(WEBHOOK_TRIGGERS), "status": "active"},
                timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            response = session.post(
                f"{base_url}/v3/webhooks/rotate-secret/{webhook_id}", timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS
            )
        else:
            response = session.post(
                f"{base_url}/v3/webhooks",
                json={
                    "trigger_types": list(WEBHOOK_TRIGGERS),
                    "webhook_url": webhook_url,
                    "description": WEBHOOK_DESCRIPTION,
                },
                timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
    except requests.RequestException as error:
        return WebhookCreationResult(success=False, error=_format_request_error(error))

    data = response.json().get("data")
    secret = data.get("webhook_secret") if isinstance(data, dict) else None
    return WebhookCreationResult(
        success=True,
        extra_inputs={"signing_secret": secret} if secret else {},
        pending_inputs=[] if secret else ["signing_secret"],
    )


def sync_webhook_events(
    api_key: str, region: str | None, webhook_url: str, desired_triggers: list[str]
) -> WebhookSyncResult:
    base_url = base_url_for_region(region)
    session = _make_session(api_key)
    try:
        webhook = _find_webhook_by_url(session, base_url, webhook_url)
        if webhook is None or not webhook.get("id"):
            return WebhookSyncResult(success=False, error="No Nylas webhook found for this source")
        if set(webhook.get("trigger_types") or []) == set(desired_triggers):
            return WebhookSyncResult(success=True)
        response = session.put(
            f"{base_url}/v3/webhooks/{webhook['id']}",
            json={"trigger_types": desired_triggers},
            timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        return WebhookSyncResult(success=False, error=_format_request_error(error))
    return WebhookSyncResult(success=True)


def get_external_webhook_info(api_key: str, region: str | None, webhook_url: str) -> ExternalWebhookInfo:
    base_url = base_url_for_region(region)
    try:
        webhook = _find_webhook_by_url(_make_session(api_key), base_url, webhook_url)
    except requests.RequestException as error:
        return ExternalWebhookInfo(exists=False, error=_format_request_error(error))

    if webhook is None:
        return ExternalWebhookInfo(exists=False)

    return ExternalWebhookInfo(
        exists=True,
        url=webhook.get("webhook_url"),
        enabled_events=webhook.get("trigger_types"),
        status=webhook.get("status"),
        description=webhook.get("description"),
    )


def delete_webhook(api_key: str, region: str | None, webhook_url: str) -> WebhookDeletionResult:
    base_url = base_url_for_region(region)
    session = _make_session(api_key)
    try:
        webhook = _find_webhook_by_url(session, base_url, webhook_url)
        if webhook is None or not webhook.get("id"):
            return WebhookDeletionResult(success=True)
        response = session.delete(f"{base_url}/v3/webhooks/{webhook['id']}", timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS)
        if response.status_code != 404:
            response.raise_for_status()
    except requests.RequestException as error:
        return WebhookDeletionResult(success=False, error=_format_request_error(error))
    return WebhookDeletionResult(success=True)
