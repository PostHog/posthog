import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.settings import (
    METRICS_GRANULARITY,
    METRICS_INITIAL_LOOKBACK,
    METRICS_WINDOW,
    PAGE_SIZE,
    RAYGUN_BASE_URL,
    RAYGUN_ENDPOINTS,
    RaygunEndpointConfig,
)

# The `applications` response carries `apiKey` — the ingestion key for that application — which
# anyone with warehouse viewer access could otherwise read and use to submit forged crash/APM/RUM
# data. It is never needed downstream, so strip it at the source.
_APPLICATIONS_SENSITIVE_FIELDS = frozenset({"apiKey"})


@dataclasses.dataclass(frozen=True)
class RaygunResumeConfig:
    # Offset (rows to skip) for the next page of a top-level list endpoint.
    offset: int = 0
    # Retained so resume state saved before the rest_source migration still parses; the fan-out
    # bookmark now lives in `fanout_state`. Never written by the current code.
    application_identifier: str | None = None
    # Framework dependent-resource resume state for fan-out endpoints, of the shape
    # ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    fanout_state: dict[str, Any] | None = None
    # Two-level fan-out endpoints (application -> parent -> child): the application being read, the
    # parent page offset, the parent's index on that page, which state filter it is on, and the
    # offset of the next child page.
    nested_application_identifier: str | None = None
    nested_parent_offset: int = 0
    nested_parent_index: int = 0
    nested_state_index: int = 0
    nested_child_offset: int = 0


def _strip_application_api_key(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _APPLICATIONS_SENSITIVE_FIELDS}


def _make_session(personal_access_token: str) -> Any:
    # `capture=False`: customer and session rows carry end-user PII (externalIdentifier, names,
    # IP addresses) and application rows carry ingestion API keys — fields the name-based sample
    # scrubbers can't recognise, so keep response bodies out of HTTP sample storage entirely.
    # Requests are still metered and logged (status + url). `redact_values` masks the token as
    # defense in depth (the framework auth also scrubs it from raised errors).
    return make_tracked_session(redact_values=(personal_access_token,), capture=False)


def _client_config(personal_access_token: str) -> ClientConfig:
    return {
        "base_url": RAYGUN_BASE_URL,
        # Auth (Bearer) goes through the framework auth config so its value is redacted from raised
        # errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": personal_access_token},
        "session": _make_session(personal_access_token),
        # Raygun list endpoints return a bare JSON array with no `total`; termination is the
        # short/empty page (OffsetPaginator default). `count` is Raygun's page-size param.
        "paginator": OffsetPaginator(limit=PAGE_SIZE, limit_param="count", total_path=None),
    }


def _rest_client(personal_access_token: str) -> RESTClient:
    return RESTClient(
        base_url=RAYGUN_BASE_URL,
        headers={"Accept": "application/json"},
        auth=BearerTokenAuth(personal_access_token),
        session=_make_session(personal_access_token),
    )


# An application, error group or deployment deleted after it was listed has nothing left to read.
_SKIP_DELETED_PARENT = create_response_hooks([{"status_code": 404, "action": "ignore"}])


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _floor_to_hour(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _get_page(client: RESTClient, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return next(
        client.paginate(path=path, params=params, paginator=SinglePagePaginator(), hooks=_SKIP_DELETED_PARENT),
        [],
    )


def _list_application_identifiers(
    client: RESTClient, resumable_source_manager: ResumableSourceManager[RaygunResumeConfig]
) -> list[str]:
    identifiers: list[str] = []
    offset = 0
    while True:
        page = _get_page(client, "/applications", {"orderby": "name", "offset": offset, "count": PAGE_SIZE})
        identifiers.extend(row["identifier"] for row in page)
        resumable_source_manager.safe_point()
        if len(page) < PAGE_SIZE:
            return identifiers
        offset += PAGE_SIZE


def _nested_child_pages(
    client: RESTClient,
    config: RaygunEndpointConfig,
    path: str,
    state_filter: Optional[str],
    offset: int,
    watermark: Optional[datetime],
) -> Iterator[tuple[list[dict[str, Any]], Optional[int]]]:
    """Yield each child page with the offset of the page after it, or None after the last page."""
    while True:
        params: dict[str, Any] = {"orderby": config.orderby, "offset": offset, "count": PAGE_SIZE}
        if state_filter is not None:
            params["filter"] = f"state eq {state_filter}"
        rows = _get_page(client, path, params)
        is_last = len(rows) < PAGE_SIZE
        if watermark is not None and config.incremental_fields and rows:
            # Children sort newest first, so a page that reaches below the watermark is the last new one.
            oldest = _parse_timestamp(rows[-1].get(config.incremental_fields[0]["field"]))
            is_last = is_last or (oldest is not None and oldest < watermark)
        offset += PAGE_SIZE
        yield rows, None if is_last else offset
        if is_last:
            return


def _nested_fan_out_rows(
    personal_access_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    """Read a child listing for every parent row of every application.

    The rest_source dependent-resource support covers one level of fan-out; these endpoints sit two
    levels below the application list. Resume state points at the next child page, so a resumed
    run reads no page twice.
    """
    config = RAYGUN_ENDPOINTS[endpoint]
    parent = config.nested_parent
    assert parent is not None
    client = _rest_client(personal_access_token)
    watermark = _parse_timestamp(db_incremental_field_last_value)
    state_filters: tuple[Optional[str], ...] = config.state_filters or (None,)

    application_identifiers = _list_application_identifiers(client, resumable_source_manager)

    start_index, parent_offset, parent_index, state_index, child_offset = 0, 0, 0, 0, 0
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.nested_application_identifier in application_identifiers:
        start_index = application_identifiers.index(resume.nested_application_identifier)
        parent_offset = resume.nested_parent_offset
        parent_index = resume.nested_parent_index
        state_index = resume.nested_state_index
        child_offset = resume.nested_child_offset

    for application_identifier in application_identifiers[start_index:]:
        parent_path = parent.path.format(application_identifier=application_identifier)
        while True:
            parents = _get_page(
                client, parent_path, {"orderby": parent.orderby, "offset": parent_offset, "count": PAGE_SIZE}
            )
            for index in range(parent_index, len(parents)):
                parent_row = parents[index]
                parent_identifier = parent_row["identifier"]
                if watermark is not None and parent.skip_below_watermark_field is not None:
                    last_activity = _parse_timestamp(parent_row.get(parent.skip_below_watermark_field))
                    if last_activity is not None and last_activity < watermark:
                        # Advance the cursor past it, so a resume after many quiet parents skips them.
                        resumable_source_manager.save_state(
                            RaygunResumeConfig(
                                nested_application_identifier=application_identifier,
                                nested_parent_offset=parent_offset,
                                nested_parent_index=index + 1,
                            )
                        )
                        state_index, child_offset = 0, 0
                        resumable_source_manager.safe_point()
                        continue

                child_path = config.path.format(
                    application_identifier=application_identifier, parent_identifier=parent_identifier
                )
                for current_state_index in range(state_index, len(state_filters)):
                    state_filter = state_filters[current_state_index]
                    for rows, next_offset in _nested_child_pages(
                        client, config, child_path, state_filter, child_offset, watermark
                    ):
                        if next_offset is not None:
                            position = (index, current_state_index, next_offset)
                        elif current_state_index + 1 < len(state_filters):
                            position = (index, current_state_index + 1, 0)
                        else:
                            position = (index + 1, 0, 0)
                        resumable_source_manager.save_state(
                            RaygunResumeConfig(
                                nested_application_identifier=application_identifier,
                                nested_parent_offset=parent_offset,
                                nested_parent_index=position[0],
                                nested_state_index=position[1],
                                nested_child_offset=position[2],
                            )
                        )
                        if rows:
                            yield [
                                {
                                    **row,
                                    "applicationIdentifier": application_identifier,
                                    parent.identifier_column: parent_identifier,
                                    **({config.state_column: state_filter} if config.state_column else {}),
                                }
                                for row in rows
                            ]
                        else:
                            resumable_source_manager.safe_point()
                    child_offset = 0
                state_index, child_offset = 0, 0
                resumable_source_manager.safe_point()

            if len(parents) < PAGE_SIZE:
                break
            parent_offset += PAGE_SIZE
            parent_index = 0
        parent_offset, parent_index, state_index, child_offset = 0, 0, 0, 0


def _metrics_rows(
    personal_access_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    """Read hourly metric series for every application, one row per metric, aggregation and hour.

    Each run re-reads from the watermark (or the initial lookback) to now. That is a few requests
    per application, so these endpoints keep no resume state.
    """
    config = RAYGUN_ENDPOINTS[endpoint]
    client = _rest_client(personal_access_token)
    end = _floor_to_hour(datetime.now(UTC))
    watermark = _parse_timestamp(db_incremental_field_last_value)
    start = _floor_to_hour(watermark if watermark is not None else end - METRICS_INITIAL_LOOKBACK)

    for application_identifier in _list_application_identifiers(client, resumable_source_manager):
        path = config.path.format(application_identifier=application_identifier)
        window_start = start
        while window_start < end:
            window_end = min(window_start + METRICS_WINDOW, end)
            for request in config.metrics_requests:
                body = {
                    "start": _format_timestamp(window_start),
                    "end": _format_timestamp(window_end),
                    "granularity": METRICS_GRANULARITY,
                    "aggregation": request.aggregation,
                    "metrics": list(request.metrics),
                }
                series_list = next(
                    client.paginate(
                        path=path,
                        method="post",
                        json=body,
                        paginator=SinglePagePaginator(),
                        hooks=_SKIP_DELETED_PARENT,
                    ),
                    [],
                )
                rows = [
                    {
                        "applicationIdentifier": application_identifier,
                        "metric": series.get("metric"),
                        "aggregation": series.get("aggregation"),
                        "time": point.get("time"),
                        "value": point.get("value"),
                    }
                    for series in series_list
                    for point in series.get("series") or []
                ]
                if rows:
                    yield rows
                else:
                    resumable_source_manager.safe_point()
            window_start = window_end


def validate_token(personal_access_token: str) -> tuple[bool, int | None]:
    """Probe the token against the cheapest scoped endpoint. Returns (is_valid, status_code).

    A 200 confirms the token is genuine and carries `applications:read`. The status code lets the
    caller distinguish a bad token (401) from a valid token missing a scope (403)."""
    return validate_via_probe(
        lambda: _make_session(personal_access_token),
        f"{RAYGUN_BASE_URL}/applications?count=1",
        headers={"Authorization": f"Bearer {personal_access_token}", "Accept": "application/json"},
    )


def _top_level_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any],
):
    config = RAYGUN_ENDPOINTS[endpoint]

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": {"orderby": config.orderby},
        },
    }
    if endpoint == "applications":
        resource_config["data_map"] = _strip_application_api_key

    rest_config: RESTAPIConfig = {
        "client": _client_config(personal_access_token),
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only seed from a top-level (offset) checkpoint; a fan-out checkpoint has no meaning here.
        if resume is not None and resume.fanout_state is None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(RaygunResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any],
):
    config = RAYGUN_ENDPOINTS[endpoint]
    parent_config = RAYGUN_ENDPOINTS["applications"]

    rest_config: RESTAPIConfig = {
        "client": _client_config(personal_access_token),
        "resources": [
            {
                "name": "applications",
                "endpoint": {
                    "path": parent_config.path,
                    "params": {"orderby": parent_config.orderby},
                },
            },
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {
                        # Resolve the per-application child path from each application's identifier.
                        "application_identifier": {
                            "type": "resolve",
                            "resource": "applications",
                            "field": "identifier",
                        },
                        "orderby": config.orderby,
                    },
                },
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only seed from a fan-out checkpoint. State saved before the migration (old-shape offset/
        # application_identifier, no fanout_state) can't drive the framework's per-parent resume, so
        # that part starts fresh — the parent list is re-enumerated and merge dedupes re-pulled rows.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(RaygunResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == endpoint)


def raygun_source(
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RAYGUN_ENDPOINTS[endpoint]

    resource: Any
    if config.metrics_requests:
        resource = _metrics_rows(
            personal_access_token, endpoint, resumable_source_manager, db_incremental_field_last_value
        )
    elif config.nested_parent is not None:
        resource = _nested_fan_out_rows(
            personal_access_token, endpoint, resumable_source_manager, db_incremental_field_last_value
        )
    elif config.fan_out_over_applications:
        resource = _fan_out_source(
            personal_access_token,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
        )
    else:
        resource = _top_level_source(
            personal_access_token,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Metrics endpoints save no cursor, so a handed-off run would start over rather than resume.
        supports_resume=not config.metrics_requests,
    )
