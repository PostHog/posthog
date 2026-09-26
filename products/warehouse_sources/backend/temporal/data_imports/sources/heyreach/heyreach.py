from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from functools import partial
from typing import Any, Optional

from dateutil import parser

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.settings import (
    ENDPOINTS,
    HEYREACH_BASE_URL,
    PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
    HeyReachEndpointConfig,
)

# HeyReach launched in 2021, so this start date covers every account's full stats history.
STATS_START_DATE = "2020-01-01T00:00:00.000Z"

AUTH_HEADER = "X-API-KEY"


@frozen
class HeyReachResumeConfig:
    offset: int


def _offset_paginator() -> OffsetPaginator:
    # Every HeyReach list endpoint is POST with `offset`/`limit` in the JSON body and a
    # `{"totalCount": n, "items": [...]}` envelope.
    return OffsetPaginator(
        limit=PAGE_SIZE,
        offset_param="offset",
        limit_param="limit",
        total_path="totalCount",
        param_location="json",
    )


def _make_client(api_key: str) -> RESTClient:
    return RESTClient(
        base_url=HEYREACH_BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name=AUTH_HEADER, location="header"),
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _rest_config(api_key: str, endpoint_config: HeyReachEndpointConfig) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": HEYREACH_BASE_URL,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "auth": {
                "type": "api_key",
                "name": AUTH_HEADER,
                "api_key": api_key,
                "location": "header",
            },
            "paginator": _offset_paginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint_config.name,
                "table_name": endpoint_config.name,
                "write_disposition": "replace",
                "endpoint": {
                    "method": "POST",
                    "path": endpoint_config.path,
                    "json": dict(endpoint_config.request_body),
                    "data_selector": "items",
                },
                "table_format": "delta",
            }
        ],
    }


def _top_level_rows(
    api_key: str,
    endpoint_config: HeyReachEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HeyReachResumeConfig],
):
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset"):
            resumable_source_manager.save_state(HeyReachResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        _rest_config(api_key, endpoint_config),
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_rows(api_key: str, endpoint_config: HeyReachEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    fanout = endpoint_config.fanout
    assert fanout is not None
    parent_config = ENDPOINTS[fanout.parent]
    client = _make_client(api_key)

    for parent_page in client.paginate(
        path=parent_config.path,
        method="post",
        json={**parent_config.request_body, **fanout.parent_body},
        paginator=_offset_paginator(),
        data_selector="items",
    ):
        for parent_row in parent_page:
            parent_id = parent_row.get("id")
            if parent_id is None:
                continue
            for child_page in client.paginate(
                path=endpoint_config.path,
                method="post",
                json={**endpoint_config.request_body, fanout.body_param: parent_id},
                paginator=_offset_paginator(),
                data_selector="items",
            ):
                # An API-provided field of the same name wins over the injected parent id.
                rows = [{fanout.body_param: parent_id, **row} for row in child_page]
                if rows:
                    yield rows


def _overall_stats_rows(api_key: str, endpoint_config: HeyReachEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    client = _make_client(api_key)
    body = {
        # Empty arrays mean "all senders" / "all campaigns".
        "accountIds": [],
        "campaignIds": [],
        "startDate": STATS_START_DATE,
        "endDate": datetime.now(tz=UTC).isoformat(),
    }
    # The endpoint returns everything in one response; the selector resolves the day-keyed
    # `byDayStats` object, which paginate wraps as a single-element page.
    for page in client.paginate(
        path=endpoint_config.path,
        method="post",
        json=body,
        data_selector="byDayStats",
    ):
        for by_day in page:
            rows = [{"date": parser.parse(day), **(stats or {})} for day, stats in (by_day or {}).items()]
            if rows:
                yield rows


def _build_response(endpoint_config: HeyReachEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items,
        primary_keys=list(endpoint_config.primary_keys),
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def heyreach_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HeyReachResumeConfig],
) -> SourceResponse:
    endpoint_config = ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"HeyReach endpoint does not exist: {endpoint}")

    if endpoint_config.daily_stats:
        return _build_response(endpoint_config, partial(_overall_stats_rows, api_key, endpoint_config))

    if endpoint_config.fanout is not None:
        # Fan-out runs restart from the first parent on resume: the parent set can change
        # between attempts, so an offset into it is not a stable cursor.
        return _build_response(endpoint_config, partial(_fanout_rows, api_key, endpoint_config))

    resource = _top_level_rows(api_key, endpoint_config, team_id, job_id, resumable_source_manager)
    return _build_response(endpoint_config, lambda: resource)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # A non-ASCII key can't be encoded into the request header (requests uses latin-1),
    # which would otherwise surface a raw UnicodeEncodeError to the user.
    if not api_key.isascii():
        return (
            False,
            "Your HeyReach API key contains an unsupported character (for example an invisible one "
            "pasted from another app). Retype it by hand and try again.",
        )

    # allow_redirects=False: the key rides a custom header, which requests would replay to a
    # cross-origin redirect target.
    is_valid, status = validate_via_probe(
        lambda: make_tracked_session(headers={AUTH_HEADER: api_key}, redact_values=(api_key,)),
        f"{HEYREACH_BASE_URL}/auth/CheckApiKey",
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
    )

    if is_valid:
        return True, None
    if status in (401, 403):
        return (
            False,
            "HeyReach rejected the API key. Create a new key in HeyReach under "
            "Settings > Integrations > HeyReach API and try again.",
        )
    if status is None:
        return False, "Couldn't reach HeyReach to check the API key. Try again in a few minutes."
    return (
        False,
        f"HeyReach returned an unexpected status ({status}) while checking the API key. Try again in a few minutes.",
    )
