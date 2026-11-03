from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import quote

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.proofpointtap import (
    ProofpointTapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.proofpoint_tap.settings import (
    AUTH_ERRORS,
    BASE_URL,
    CAMPAIGN_IDS_PATH,
    CAMPAIGN_WINDOW,
    ENDPOINTS,
    MIN_WINDOW,
    OVERLAP,
    PEOPLE_WINDOW_DAYS,
    RETENTION,
    SIEM_ALL_PATH,
    SIEM_SELECTORS,
    WINDOW,
    TapEndpoint,
)


@frozen
class TapCursor:
    cursor_kind: ClassVar[str] = "proofpoint_tap_query_end"
    query_end_time: str


@frozen
class TapResumeState:
    next_start: str = ""
    end: str = ""
    # Lookup tables: the IDs already read in the window that starts at next_start.
    done: tuple[str, ...] = ()
    # People tables: the next page to read.
    page: int = 1


@frozen
class TapWindowBounds:
    start: datetime
    end: datetime
    resume: TapResumeState | None


def parse_timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def get_resource(
    config: ProofpointTapSourceConfig,
    name: str,
    path: str,
    params: dict[str, Any],
    team_id: int,
    job_id: str,
    api_version: str,
    ignore_not_found: bool = False,
) -> Resource:
    endpoint: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "$",
        "data_selector_required": True,
    }
    if ignore_not_found:
        endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/",
            "auth": {"type": "http_basic", "username": config.service_principal, "password": config.secret},
            "paginator": "single_page",
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": [{"name": name, "endpoint": endpoint}],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def fetch_payload(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    path: str,
    params: dict[str, Any],
    api_version: str,
    ignore_not_found: bool = False,
) -> dict[str, Any] | None:
    resource = get_resource(
        config, inputs.schema_name, path, params, inputs.team_id, inputs.job_id, api_version, ignore_not_found
    )
    payloads = [payload for page in resource for payload in page]
    if ignore_not_found and not payloads:
        return None
    if len(payloads) != 1 or not isinstance(payloads[0], dict):
        raise ValueError("Proofpoint TAP returned an invalid response. Retry the sync.")
    return payloads[0]


def fetch_siem_window(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    path: str,
    start: datetime,
    window_end: datetime,
    api_version: str,
) -> tuple[datetime, dict[str, Any]]:
    payload = fetch_payload(
        config,
        inputs,
        path,
        {"format": "json", "interval": f"{start.isoformat()}/{window_end.isoformat()}"},
        api_version,
    )
    assert payload is not None
    raw_end = payload.get("queryEndTime")
    if not isinstance(raw_end, str):
        raise ValueError("Proofpoint TAP returned an invalid response. Retry the sync.")
    query_end = parse_timestamp(raw_end)
    if query_end != window_end:
        raise ValueError("Proofpoint TAP returned an invalid query end time. Retry the sync.")
    return query_end, payload


def dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Proofpoint TAP returned an invalid response. Retry the sync.")
    return value


def validate_credentials(
    config: ProofpointTapSourceConfig, team_id: int, schema_name: str | None, api_version: str
) -> tuple[bool, str | None]:
    endpoint = ENDPOINTS.get(schema_name or "")
    # The campaign and People APIs allow 50 requests a day, so a SIEM request checks the credentials.
    if endpoint is None or endpoint.kind in ("campaigns", "people"):
        path = ENDPOINTS["clicks_blocked"].path
    elif endpoint.kind == "threats":
        path = SIEM_ALL_PATH
    else:
        path = endpoint.path
    try:
        list(
            get_resource(
                config,
                schema_name or "clicks_blocked",
                path,
                {"format": "json", "sinceSeconds": 30},
                team_id,
                "",
                api_version,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 403 and schema_name is None:
            return True, None
        if status is not None and status in AUTH_ERRORS:
            return False, AUTH_ERRORS[status]
        raise
    return True, None


def window_bounds(
    inputs: SourceInputs,
    manager: ResumableSourceManager[TapResumeState],
    cursor_manager: SourceCursorManager[TapCursor],
) -> TapWindowBounds:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    # Leave time for the first request before the oldest interval expires.
    earliest = now - RETENTION + 2 * OVERLAP
    end = now - OVERLAP
    start = earliest
    cursor = cursor_manager.load() if inputs.should_use_incremental_field else None
    if cursor is not None:
        start = max(earliest, parse_timestamp(cursor.query_end_time) - OVERLAP)
    elif inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        start = max(earliest, parse_timestamp(inputs.db_incremental_field_last_value) - OVERLAP)

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None:
        start = max(earliest, parse_timestamp(resume.next_start))
        end = min(end, parse_timestamp(resume.end))
    return TapWindowBounds(start=start, end=end, resume=resume)


def siem_items(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    settings: TapEndpoint,
    manager: ResumableSourceManager[TapResumeState],
    cursor_manager: SourceCursorManager[TapCursor],
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    bounds = window_bounds(inputs, manager, cursor_manager)
    start, end, resume = bounds.start, bounds.end, bounds.resume
    last_end: datetime | None = None
    while end - start >= MIN_WINDOW:
        window_end = min(start + WINDOW, end)
        query_end, payload = fetch_siem_window(config, inputs, settings.path, start, window_end, api_version)
        rows = dict_rows(payload.get(settings.selector))
        if any(not row.get(settings.primary_key) for row in rows):
            raise ValueError("Proofpoint TAP returned an event without its unique ID. Retry the sync.")

        # Event timestamps can predate detection, so only the queried interval can advance the cursor.
        for row in rows:
            row["query_end_time"] = query_end
        manager.save_state(TapResumeState(next_start=query_end.isoformat(), end=end.isoformat()))
        if rows:
            yield rows
        manager.safe_point()
        last_end = query_end
        start = query_end

    if last_end is not None:
        cursor_manager.stage(TapCursor(query_end_time=last_end.isoformat()))
    elif resume is not None and start >= end:
        cursor_manager.stage(TapCursor(query_end_time=end.isoformat()))


def siem_threat_ids(
    config: ProofpointTapSourceConfig, inputs: SourceInputs, api_version: str
) -> Callable[[datetime, datetime], Iterator[dict[str, Any]]]:
    def list_window(start: datetime, window_end: datetime) -> Iterator[dict[str, Any]]:
        _, payload = fetch_siem_window(config, inputs, SIEM_ALL_PATH, start, window_end, api_version)
        for selector in SIEM_SELECTORS:
            for event in dict_rows(payload.get(selector) or []):
                if event.get("threatID"):
                    yield {"id": event["threatID"]}
                for threat in event.get("threatsInfoMap") or []:
                    if isinstance(threat, dict) and threat.get("threatID"):
                        yield {"id": threat["threatID"]}

    return list_window


def campaign_ids(
    config: ProofpointTapSourceConfig, inputs: SourceInputs, settings: TapEndpoint, api_version: str
) -> Callable[[datetime, datetime], Iterator[dict[str, Any]]]:
    page_size = settings.page_size or 100

    def list_window(start: datetime, window_end: datetime) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            payload = fetch_payload(
                config,
                inputs,
                CAMPAIGN_IDS_PATH,
                {"interval": f"{start.isoformat()}/{window_end.isoformat()}", "size": page_size, "page": page},
                api_version,
            )
            assert payload is not None
            campaigns = dict_rows(payload.get(settings.selector) or [])
            yield from campaigns
            if len(campaigns) < page_size:
                return
            page += 1

    return list_window


def lookup_items(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    settings: TapEndpoint,
    manager: ResumableSourceManager[TapResumeState],
    cursor_manager: SourceCursorManager[TapCursor],
    api_version: str,
    window: timedelta,
    list_window: Callable[[datetime, datetime], Iterator[dict[str, Any]]],
) -> Iterator[list[dict[str, Any]]]:
    """Look up the details of every ID that a time window lists, one window at a time."""
    bounds = window_bounds(inputs, manager, cursor_manager)
    start, end, resume = bounds.start, bounds.end, bounds.resume
    # A resumed run lists its window again and skips the IDs it already read there.
    done = list(resume.done) if resume is not None else []
    seen = set(done)
    last_end: datetime | None = None
    while end - start >= MIN_WINDOW:
        window_end = min(start + window, end)
        manager.save_state(TapResumeState(next_start=start.isoformat(), end=end.isoformat(), done=tuple(done)))
        for entry in list_window(start, window_end):
            item_id = entry.get("id")
            if not isinstance(item_id, str) or not item_id:
                raise ValueError("Proofpoint TAP returned an item without its unique ID. Retry the sync.")
            if item_id in seen:
                continue
            seen.add(item_id)
            # An ID that SIEM events still reference can be gone from the lookup API.
            detail = fetch_payload(
                config, inputs, settings.path.format(id=quote(item_id, safe="")), {}, api_version, ignore_not_found=True
            )
            if detail is not None and detail.get("id") != item_id:
                raise ValueError("Proofpoint TAP returned details for a different item. Retry the sync.")
            done.append(item_id)
            manager.save_state(TapResumeState(next_start=start.isoformat(), end=end.isoformat(), done=tuple(done)))
            if detail is None:
                manager.safe_point()
                continue
            yield [{**entry, **detail, "query_end_time": window_end}]
        manager.safe_point()
        done = []
        last_end = window_end
        start = window_end

    if last_end is not None:
        cursor_manager.stage(TapCursor(query_end_time=last_end.isoformat()))
    elif resume is not None and start >= end:
        cursor_manager.stage(TapCursor(query_end_time=end.isoformat()))


def people_items(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    settings: TapEndpoint,
    manager: ResumableSourceManager[TapResumeState],
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    page_size = settings.page_size or 100
    seen: set[str] = set()
    # The endpoint allows 50 requests a day, so a retry after the quota resets continues at the next page.
    resume = manager.load_state() if manager.can_resume() else None
    page = resume.page if resume is not None else 1
    while True:
        payload = fetch_payload(
            config, inputs, settings.path, {"window": PEOPLE_WINDOW_DAYS, "size": page_size, "page": page}, api_version
        )
        assert payload is not None
        users = dict_rows(payload.get(settings.selector))
        rows = []
        for user in users:
            identity = user.get("identity")
            guid = identity.get("guid") if isinstance(identity, dict) else None
            if not isinstance(guid, str) or not guid:
                raise ValueError("Proofpoint TAP returned a user without its unique ID. Retry the sync.")
            # Results are ranked, so a user can move to another page while the sync reads them.
            if guid not in seen:
                seen.add(guid)
                rows.append({**user, "guid": guid, "interval": payload.get("interval")})
        manager.save_state(TapResumeState(page=page + 1))
        if rows:
            yield rows
        manager.safe_point()
        if len(users) < page_size:
            return
        page += 1


def proofpoint_tap_source(
    config: ProofpointTapSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[TapResumeState],
    cursor_manager: SourceCursorManager[TapCursor],
    api_version: str,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)

    def items() -> Iterator[list[dict[str, Any]]]:
        if settings.kind == "siem":
            yield from siem_items(config, inputs, settings, manager, cursor_manager, api_version)
        elif settings.kind == "threats":
            list_window = siem_threat_ids(config, inputs, api_version)
            yield from lookup_items(config, inputs, settings, manager, cursor_manager, api_version, WINDOW, list_window)
        elif settings.kind == "campaigns":
            list_window = campaign_ids(config, inputs, settings, api_version)
            yield from lookup_items(
                config, inputs, settings, manager, cursor_manager, api_version, CAMPAIGN_WINDOW, list_window
            )
        else:
            yield from people_items(config, inputs, settings, manager, api_version)

    partitioned = settings.partition_key is not None
    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        primary_keys=[settings.primary_key],
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        sort_mode="desc" if settings.kind == "siem" else None,
        on_complete=manager.clear_state,
    )
