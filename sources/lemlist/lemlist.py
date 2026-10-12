import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

from sources.lemlist.settings import LEMLIST_ENDPOINTS, LemlistEndpointConfig
from sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    HttpBasicAuth,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

LEMLIST_BASE_URL = "https://api.lemlist.com/api"
# lemlist caps list pages at 100 rows and rate-limits to 20 requests / 2s per API key.
PAGE_SIZE = 100

# lemlist selects an API version per endpoint via a `version` query param (not a header or path).
# The framework labels are opaque: v1 preserves the wire this source has always sent, v2 opts every
# version-aware endpoint into lemlist's current shape. campaigns/activities only serve v2 and so send
# it under either pin; /team's v2 additionally returns a `users` array, sent only under a v2 pin.
LEMLIST_API_VERSION_V1 = "v1"
LEMLIST_API_VERSION_V2 = "v2"
LEMLIST_SUPPORTED_VERSIONS = (LEMLIST_API_VERSION_V1, LEMLIST_API_VERSION_V2)
LEMLIST_DEFAULT_VERSION = LEMLIST_API_VERSION_V2


@dataclasses.dataclass
class LemlistResumeConfig:
    # Offset of the next page to fetch. lemlist uses limit/offset pagination, so a single integer
    # is enough to pick back up where a crashed run left off.
    offset: int = 0


def _format_datetime_z(value: datetime) -> str:
    """ISO 8601 with a Z suffix — one of the two formats lemlist accepts for minDate/maxDate."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future cursor at now.

    The watermark tracks the max createdAt seen. A future-dated activity would otherwise push the
    cursor past now, and every later sync would ask for activities newer than the future — a no-op
    that just risks tripping lemlist's "maxDate must be greater than minDate" style validation.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": LEMLIST_BASE_URL,
        # lemlist uses HTTP Basic auth with an empty username and the API key as the password.
        # Supplied via the framework auth config so the key is redacted from logs and errors.
        "auth": {"type": "http_basic", "username": "", "password": api_key},
    }


def _request_params(config: LemlistEndpointConfig, api_version: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.requires_version_v2 or (config.version_v2_enriches and api_version == LEMLIST_API_VERSION_V2):
        params["version"] = LEMLIST_API_VERSION_V2
    if config.request_sort_by:
        params["sortBy"] = config.request_sort_by
    if config.request_sort_order:
        params["sortOrder"] = config.request_sort_order
    return params


def _campaign_fanout_source(
    api_key: str,
    endpoint: str,
    config: LemlistEndpointConfig,
    team_id: int,
    job_id: str,
    api_version: str,
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = LEMLIST_ENDPOINTS[config.fanout.parent_name]
    fanout = dataclasses.replace(config.fanout, parent_params=_request_params(parent_config, api_version))

    child_endpoint_extra: Endpoint = {"paginator": SinglePagePaginator()}
    if config.data_selector:
        child_endpoint_extra["data_selector"] = config.data_selector

    resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=LEMLIST_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            # None of the per-campaign endpoints has a server-side time filter.
            db_incremental_field_last_value=None,
            # The parent's OffsetPaginator sends `limit`; the child endpoints take no page size.
            page_size_param=None,
            parent_endpoint_extra={"paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None)},
            child_endpoint_extra=child_endpoint_extra,
        ),
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def lemlist_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LemlistResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LEMLIST_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _campaign_fanout_source(api_key, endpoint, config, team_id, job_id, api_version)

    params = _request_params(config, api_version)

    # lemlist has no top-level `total`; the OffsetPaginator terminates on a short/empty page.
    # Non-paginated endpoints (team, team/senders) return their whole result in one response.
    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "params": params,
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None) if config.paginate else SinglePagePaginator(),
    }
    if config.data_selector:
        endpoint_config["data_selector"] = config.data_selector

    use_incremental = config.supports_incremental and should_use_incremental_field
    if use_incremental:
        # Only /activities honours the server-side minDate filter. Without a stored watermark yet,
        # bound the first sync by the configured lookback rather than pulling the whole history.
        initial_value: Optional[datetime] = None
        if config.default_lookback_days:
            initial_value = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        endpoint_config["incremental"] = {
            "start_param": "minDate",
            "cursor_path": "createdAt",
            "initial_value": initial_value,
            # Clamp a future watermark to now and render it in the Z-suffixed format lemlist expects.
            "convert": lambda value: _format_incremental_value(_clamp_future_value_to_now(value)),
        }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            cast(
                EndpointResource,
                {
                    "name": endpoint,
                    "endpoint": endpoint_config,
                },
            )
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginate and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(LemlistResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def validate_credentials(api_key: str) -> bool:
    # `/team` is the cheapest authenticated probe — no pagination, single object.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{LEMLIST_BASE_URL}/team",
        auth=HttpBasicAuth(username="", password=api_key),
    )
    return ok
