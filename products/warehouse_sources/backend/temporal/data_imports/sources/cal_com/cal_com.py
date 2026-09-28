from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from functools import partial
from typing import Any, Optional, cast
from urllib.parse import quote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    BOOKING_ATTENDEES_ENDPOINT,
    BOOKING_ATTENDEES_PARENT,
    CAL_COM_ENDPOINTS,
    CAL_COM_HOSTS,
    ORG_PATH_PLACEHOLDER,
    CalComEndpointConfig,
    endpoint_requires_organization,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Cheap single-object endpoint used to confirm an API key is genuine. The key is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/me"
DEFAULT_REGION = "us"
REQUEST_TIMEOUT_SECONDS = 30

# Seed for the afterCreatedAt/afterUpdatedAt filters before a table has a watermark.
EPOCH_INCREMENTAL_VALUE = "1970-01-01T00:00:00.000Z"

ORGANIZATION_REQUIRED_ERROR = (
    "This Cal.com table holds organization data, but the account the API key belongs to is not in "
    "a Cal.com organization. Deselect the organization tables, or reconnect with a key from an "
    "account that has organization admin access."
)


@frozen
class CalComResumeConfig:
    # Opaque `pagination.nextCursor` for cursor-paginated endpoints (bookings). A crashed sync
    # resumes from the page after the last one yielded; merge dedupes the re-pulled page on `id`.
    cursor: str | None = None
    # `skip` offset for offset-paginated endpoints (webhooks).
    skip: int | None = None
    # Fan-out endpoints resume per parent — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def _host(region: str) -> str:
    # Fall back to US rather than raising: an unrecognized stored value must not break a sync that
    # is already running.
    return CAL_COM_HOSTS.get(region, CAL_COM_HOSTS[DEFAULT_REGION])


def _headers(config: CalComEndpointConfig) -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret headers are set here. Cal.com versions endpoints individually via the
    # `cal-api-version` header; omitting it silently falls back to a legacy behavior, so it must be
    # pinned per endpoint.
    headers = {"Accept": "application/json"}
    if config.api_version:
        headers["cal-api-version"] = config.api_version
    return headers


def _client_config(region: str, api_key: str, config: CalComEndpointConfig) -> ClientConfig:
    return {
        "base_url": _host(region),
        "headers": _headers(config),
        "auth": {"type": "bearer", "token": api_key},
        # Rows carry contact details and free text the name-based sample scrubbers can't spot.
        "capture": False,
    }


def _path_format_values(organization_id: int | None) -> dict[str, str]:
    return {} if organization_id is None else {"orgId": str(organization_id)}


def _format_path(path: str, organization_id: int | None) -> str:
    if ORG_PATH_PLACEHOLDER not in path:
        return path
    if organization_id is None:
        raise ValueError(ORGANIZATION_REQUIRED_ERROR)
    return path.replace(ORG_PATH_PLACEHOLDER, str(organization_id))


def _format_incremental_value(value: Any) -> str:
    # Cal.com's afterUpdatedAt/afterCreatedAt filters take ISO 8601 date strings; normalize to UTC
    # with a Z suffix to avoid timezone ambiguity.
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_incremental_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _resolve_incremental_field(config: CalComEndpointConfig, incremental_field: str | None) -> str | None:
    return incremental_field or config.default_incremental_field


def _build_incremental_params(
    config: CalComEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return {}

    field = _resolve_incremental_field(config, incremental_field)
    if field is None:
        return {}

    param = config.incremental_param_by_field.get(field)
    if param is None:
        raise ValueError(f"Cal.com endpoint '{config.name}' has no server-side filter for field '{field}'")

    return {param: _format_incremental_value(db_incremental_field_last_value)}


def _build_sort_params(
    config: CalComEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Ask for the sort that matches the cursor, so the pipeline's watermark advances in order."""
    param = config.default_sort_param
    if should_use_incremental_field:
        field = _resolve_incremental_field(config, incremental_field)
        if field is not None:
            param = config.sort_param_by_field.get(field, param)
    return {param: "asc"} if param else {}


def _incremental_window(config: CalComEndpointConfig, cursor_path: str) -> IncrementalConfig | None:
    param = config.incremental_param_by_field.get(cursor_path)
    if param is None:
        return None
    return {
        "cursor_path": cursor_path,
        "start_param": param,
        "initial_value": EPOCH_INCREMENTAL_VALUE,
        "convert": _format_incremental_value,
    }


def _make_paginator(config: CalComEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        # Bookings pages carry {"pagination": {"nextCursor": ..., "hasMore": ...}}; a null/absent
        # nextCursor (always the case when hasMore is false) terminates.
        return JSONResponseCursorPaginator(cursor_path="pagination.nextCursor", cursor_param="cursor")
    if config.pagination == "offset":
        # These endpoints return no pagination metadata; a short (or empty) page means we're done.
        return OffsetPaginator(
            limit=config.page_size,
            offset_param="skip",
            limit_param="take",
            total_path=None,
        )
    return SinglePagePaginator()


def _top_level_items(
    config: CalComEndpointConfig,
    api_key: str,
    region: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    organization_id: int | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> Iterable[Any]:
    params: dict[str, Any] = _build_incremental_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    params.update(_build_sort_params(config, should_use_incremental_field, incremental_field))
    if config.pagination == "cursor":
        # Bookings `limit` maxes at 100; a larger value is rejected with 400 Bad Request. The
        # offset paginator injects its own `take`/`skip` pair.
        params["limit"] = config.page_size

    client_config = _client_config(region, api_key, config)
    client_config["paginator"] = _make_paginator(config)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": _format_path(config.path, organization_id),
                    "params": params,
                    # Every v2 endpoint wraps its payload as {"status": "success", "data": ...}.
                    # A 200 body without `data` means the response shape changed — fail loud
                    # instead of silently syncing 0 rows.
                    "data_selector": "data",
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "cursor" and resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}
            elif config.pagination == "offset" and resume.skip is not None:
                initial_paginator_state = {"offset": resume.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework checkpoints AFTER a page is yielded
        # so a crash re-fetches from the next page (already-yielded pages are persisted) and merge
        # dedupes the re-pulled page on the primary key.
        if not state:
            return
        if config.pagination == "cursor" and state.get("cursor") is not None:
            resumable_source_manager.save_state(CalComResumeConfig(cursor=state["cursor"]))
        elif config.pagination == "offset" and state.get("offset") is not None:
            resumable_source_manager.save_state(CalComResumeConfig(skip=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if config.pagination in ("cursor", "offset") else None,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_items(
    config: CalComEndpointConfig,
    api_key: str,
    region: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    organization_id: int | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> Iterable[Any]:
    fanout = config.fanout
    assert fanout is not None
    parent_config = CAL_COM_ENDPOINTS[fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                CalComResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    # A 200 without the `data` envelope means the shape changed, on either hop.
    parent_endpoint: Endpoint = {
        "paginator": _make_paginator(parent_config),
        "data_selector": "data",
        "data_selector_required": True,
    }
    child_endpoint: Endpoint = {
        "paginator": _make_paginator(config),
        "data_selector": "data",
        "data_selector_required": True,
    }

    return cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=CAL_COM_ENDPOINTS,
            child_endpoint=config.name,
            fanout=fanout,
            client_config=_client_config(region, api_key, config),
            path_format_values=_path_format_values(organization_id),
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=lambda cursor_path: _incremental_window(config, cursor_path),
            # The offset paginators inject their own `take`/`skip`.
            page_size_param=None,
            parent_endpoint_extra=parent_endpoint,
            child_endpoint_extra=child_endpoint,
            child_params_extra=_build_sort_params(config, should_use_incremental_field, incremental_field) or None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )


def _booking_attendees_items(
    config: CalComEndpointConfig,
    api_key: str,
    region: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield one batch of attendee rows per page of bookings.

    Hand-rolled rather than a dependent resource because the two hops need different
    `cal-api-version` headers and a dependent resource sends one set of client headers for both.
    """
    parent_config = CAL_COM_ENDPOINTS[BOOKING_ATTENDEES_PARENT]

    # Bounding the bookings walk is what keeps an incremental sync off every booking ever made.
    parent_params: dict[str, Any] = _build_incremental_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    parent_params["limit"] = parent_config.page_size

    parent_client_config = _client_config(region, api_key, parent_config)
    parent_client_config["paginator"] = _make_paginator(parent_config)

    parent_rest_config: RESTAPIConfig = {
        "client": parent_client_config,
        "resources": [
            {
                "name": BOOKING_ATTENDEES_PARENT,
                "endpoint": {
                    "path": parent_config.path,
                    "params": parent_params,
                    "data_selector": "data",
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The hook runs when this generator asks for the next page, so after its rows are out.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(CalComResumeConfig(cursor=state["cursor"]))

    bookings = rest_api_resource(
        parent_rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    # capture=False for the same reason as `_client_config`: attendee rows are contact details.
    session = make_tracked_session(redact_values=(api_key,), capture=False)
    headers = {**_headers(config), "Authorization": f"Bearer {api_key}"}
    base_url = _host(region)

    for page in bookings:
        rows: list[dict[str, Any]] = []
        for booking in page:
            uid = booking.get("uid")
            if uid is None:
                continue
            response = session.get(
                f"{base_url}/bookings/{quote(str(uid), safe='')}/attendees",
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 404:
                # The booking went away between the listing and this fetch.
                continue
            response.raise_for_status()
            body = response.json()
            attendees = body.get("data") if isinstance(body, dict) else None
            if not isinstance(attendees, list):
                raise ValueError(f"Cal.com attendees response for booking '{uid}' matched nothing for `data`")
            for attendee in attendees:
                rows.append(
                    {
                        **attendee,
                        "bookingUid": uid,
                        "bookingCreatedAt": booking.get("createdAt"),
                        "bookingUpdatedAt": booking.get("updatedAt"),
                    }
                )
        if rows:
            yield rows


def cal_com_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
    region: str = DEFAULT_REGION,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    organization_id: int | None = None,
) -> SourceResponse:
    config = CAL_COM_ENDPOINTS[endpoint]
    if organization_id is None and endpoint_requires_organization(endpoint):
        raise ValueError(ORGANIZATION_REQUIRED_ERROR)

    items: Any
    if endpoint == BOOKING_ATTENDEES_ENDPOINT:
        items = partial(
            _booking_attendees_items,
            config,
            api_key,
            region,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    else:
        builder = _fanout_items if config.fanout is not None else _top_level_items
        resource = builder(
            config,
            api_key,
            region,
            team_id,
            job_id,
            resumable_source_manager,
            organization_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
        items = lambda: resource  # noqa: E731

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # "desc" holds the watermark until a sync completes, for the newest-first endpoints.
        sort_mode=config.sort_mode,
    )


def resolve_organization_id(api_key: str, region: str = DEFAULT_REGION) -> int | None:
    """The id of the Cal.com organization the API key's account belongs to, or None if it has none.

    Organization-scoped paths carry the id, and Cal.com does not expose it anywhere the user can
    read it off, so it is resolved from the key's own profile rather than asked for on the form.
    """
    session = make_tracked_session(redact_values=(api_key,))
    response = session.get(
        f"{_host(region)}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    organization_id = data.get("organizationId")
    return int(organization_id) if organization_id is not None else None


def check_organization_access(api_key: str, organization_id: int, region: str = DEFAULT_REGION) -> str | None:
    """None when the key can read organization data, otherwise why it cannot."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_host(region)}/organizations/{organization_id}/memberships",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return None
    if status == 403:
        return (
            "This API key belongs to an organization member without admin access, so Cal.com will "
            "not return organization data. Reconnect with a key from an organization admin."
        )
    return None


def validate_credentials(api_key: str, region: str = DEFAULT_REGION) -> tuple[bool, str | None]:
    # The API key is account-wide, so a single probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_host(region)}{DEFAULT_PROBE_PATH}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        # A key from the other region is rejected exactly like a bad key, so name the region too.
        return (
            False,
            "Cal.com rejected this API key. Check the key, and check that the selected region matches your Cal.com account.",
        )
    if status is None:
        return False, "Could not connect to Cal.com"
    return False, f"Cal.com returned HTTP {status}"
