import dataclasses
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import requests
from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    FanoutEndpointLike,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    COMPENSATIONS_LOOKBACK_MONTHS,
    PERSONIO_ENDPOINTS,
    PersonioEndpointConfig,
)

PERSONIO_BASE_URL = "https://api.personio.de"
TOKEN_URL = f"{PERSONIO_BASE_URL}/v2/auth/token"


@dataclasses.dataclass(frozen=True)
class PersonioResumeConfig:
    # Personio v2 paginates via _meta.links.next.href, a self-contained URL (opaque cursor), so
    # the URL is all we persist. Optional/defaulted so previously saved state (which always carried
    # next_url) still parses via dataclass(**saved).
    next_url: Optional[str] = None
    # Endpoints read as several listings (org unit types, compensation month windows) record which
    # listing next_url belongs to.
    segment: Optional[str] = None
    # Fan-out endpoints checkpoint the shape `build_dependent_resource` emits.
    fanout_state: Optional[dict[str, Any]] = None


def _make_auth(client_id: str, client_secret: str) -> OAuth2Auth:
    """Personio v2 uses OAuth2 client-credentials with the credentials carried in the request body.

    Tokens last ~24h; the framework mints one lazily, caches it for the run, and re-mints on
    expiry — replacing the pre-framework mint-once-then-reactive-401-remint handling."""
    return OAuth2Auth(
        token_url=TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="body",
    )


def _format_updated_at(value: Any) -> str:
    """Format an incremental cursor for Personio's RFC3339 date-time filters."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _month_start(value: Any) -> date:
    if isinstance(value, datetime):
        value = value.date()
    elif not isinstance(value, date):
        value = date.fromisoformat(str(value)[:10])
    return value.replace(day=1)


def _add_months(month: date, months: int) -> date:
    index = month.year * 12 + month.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _month_starts(first: date, last: date) -> list[date]:
    """The first day of each calendar month from the month of `first` through the month of `last`."""
    months = []
    month = _month_start(first)
    while month <= last:
        months.append(month)
        month = _add_months(month, 1)
    return months


@frozen
class _Segment:
    """One listing of an endpoint that Personio serves as several listings."""

    key: str
    params: dict[str, Any]
    row_map: Callable[[dict[str, Any]], dict[str, Any]] | None = None


class PersonioPaginator(JSONResponsePaginator):
    """Follow Personio's self-contained ``_meta.links.next.href`` link, stopping on an empty page.

    Personio returns a next href until the listing is exhausted; the hand-rolled source also
    stopped as soon as a page came back empty (even if a next link was still present), so mirror
    that guard here. Resume state (the pending ``next_url``) is inherited from the base next-url
    paginator."""

    def __init__(self) -> None:
        super().__init__(next_url_path="_meta.links.next.href")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def validate_credentials(client_id: str, client_secret: str) -> bool:
    """Confirm the credentials are valid by minting a token — scopes are granted per credential,
    so a successful mint is the only universal probe."""
    auth = _make_auth(client_id, client_secret)
    # Force the lazy token mint through the public auth callable; a bad credential raises here.
    probe = Request(method="GET", url=PERSONIO_BASE_URL).prepare()
    try:
        auth(probe)
    except (OAuth2AuthRequestError, requests.RequestException):
        return False
    return True


def _client_config(auth: OAuth2Auth) -> ClientConfig:
    return {
        "base_url": PERSONIO_BASE_URL,
        "auth": auth,
        # Pin every request — including _meta.links.next.href links and the seeded resume URL — to
        # api.personio.de so a tampered next/resume link can't exfiltrate the bearer token. Disable
        # redirects so a 3xx can't bounce the authenticated request (and token) off-host either.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _segments(config: PersonioEndpointConfig) -> list[_Segment]:
    """The listings a multi-listing endpoint reads, in order."""
    if config.monthly_windows:
        today = datetime.now(UTC).date()
        first = _add_months(_month_start(today), -COMPENSATIONS_LOOKBACK_MONTHS)

        def add_period(period_start: date) -> Callable[[dict[str, Any]], dict[str, Any]]:
            return lambda row: {**row, "period_start": period_start}

        return [
            _Segment(
                key=start.isoformat(),
                params={
                    "start_date": start.isoformat(),
                    "end_date": (_add_months(start, 1) - timedelta(days=1)).isoformat(),
                },
                row_map=add_period(start),
            )
            for start in _month_starts(first, today)
        ]
    return [_Segment(key=variant["type"], params=dict(variant)) for variant in config.query_variants]


def _segmented_resource(
    endpoint: str,
    config: PersonioEndpointConfig,
    auth: OAuth2Auth,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PersonioResumeConfig],
    resume: Optional[PersonioResumeConfig],
) -> Resource:
    segments = _segments(config)
    start_index = 0
    if resume is not None and resume.segment is not None:
        start_index = next((i for i, segment in enumerate(segments) if segment.key == resume.segment), 0)

    def build(index: int) -> Resource:
        segment = segments[index]
        key = segment.key
        next_key = segments[index + 1].key if index + 1 < len(segments) else None
        initial_paginator_state: Optional[dict[str, Any]] = None
        if index == start_index and resume is not None and resume.segment == key and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state is not None and state.get("next_url") is not None:
                resumable_source_manager.save_state(PersonioResumeConfig(segment=key, next_url=state["next_url"]))
            elif next_key is not None:
                # The last page of this listing is on its way, so a resume starts at the next one.
                resumable_source_manager.save_state(PersonioResumeConfig(segment=next_key))

        rest_config: RESTAPIConfig = {
            "client": _client_config(auth),
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {"limit": config.page_size, **segment.params},
                        "data_selector": "_data",
                        "paginator": PersonioPaginator(),
                    },
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        return resource.add_map(segment.row_map) if segment.row_map is not None else resource

    first = build(start_index)

    def pages() -> Iterator[list[dict[str, Any]]]:
        for index in range(start_index, len(segments)):
            resource = first if index == start_index else build(index)
            if index != start_index:
                resumable_source_manager.save_state(PersonioResumeConfig(segment=segments[index].key))
            # Every earlier listing is fully handed on, so a hand-off here loses nothing. Months with
            # no compensations otherwise send requests with no yield in between.
            resumable_source_manager.safe_point()
            yield from resource

    # As a `Resource`, the chain keeps the framework's checkpoints: each page reaches the pipeline
    # with its cursor already staged.
    return Resource(pages, name=endpoint, hints=first._hints)


def personio_source(
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PersonioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PERSONIO_ENDPOINTS[endpoint]
    auth = _make_auth(client_id, client_secret)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    incremental_params: dict[str, Any] = {}
    if (
        config.incremental_param is not None
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        incremental_params[config.incremental_param] = _format_updated_at(db_incremental_field_last_value)

    items: Callable[[], Iterable[Any]]
    if config.fanout is not None:

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(PersonioResumeConfig(fanout_state=state))

        resource = build_dependent_resource(
            # Every endpoint in a fan-out is paginated, so page_size is set on both.
            endpoint_configs=cast(Mapping[str, FanoutEndpointLike], PERSONIO_ENDPOINTS),
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(auth),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            should_use_incremental_field=should_use_incremental_field,
            # The cursor rides in child_params_extra; the factory only switches the child to merge.
            incremental_config_factory=lambda _field: None,
            parent_endpoint_extra={"data_selector": "_data", "paginator": PersonioPaginator()},
            child_endpoint_extra={"data_selector": "_data", "paginator": PersonioPaginator()},
            child_params_extra=incremental_params,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
        )
        items = lambda: resource
    elif config.monthly_windows or config.query_variants:
        segmented = _segmented_resource(endpoint, config, auth, team_id, job_id, resumable_source_manager, resume)
        items = lambda: segmented
    else:
        params: dict[str, Any] = {**incremental_params}
        if config.page_size is not None:
            params["limit"] = config.page_size

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.next_url is not None:
            initial_paginator_state = {"next_url": resume.next_url}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # The framework calls the hook AFTER a page is yielded and only while a next page remains,
            # so a crash re-yields the last batch (merge dedupes on primary key) rather than skipping it.
            if state is not None and state.get("next_url") is not None:
                resumable_source_manager.save_state(PersonioResumeConfig(next_url=state["next_url"]))

        endpoint_config: Endpoint = {
            "path": config.path,
            "params": params,
            "data_selector": "_data",
            "paginator": PersonioPaginator(),
        }
        rest_config: RESTAPIConfig = {
            "client": _client_config(auth),
            "resources": [{"name": endpoint, "endpoint": endpoint_config}],
        }
        single_resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        items = lambda: single_resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Fan-out rows arrive per person, newest-first, so they are not one ordered series.
        sort_mode=None if config.fanout is not None else "asc",
    )
