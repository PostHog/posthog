from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
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
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.settings import (
    SLEEKPLAN_BASE_URL,
    SLEEKPLAN_ENDPOINTS,
    SURVEY_LOOKBACK_DAYS,
    SURVEY_START_PARAM,
    SleekplanEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30
FIRST_PAGE = 1
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=False)
class SleekplanResumeConfig:
    # Next page to fetch, for the top-level endpoints.
    page: Optional[int] = None
    # Fan-out checkpoint for Comments and Votes:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {"page": N} | None}.
    fanout_state: Optional[dict] = None


class SleekplanPaginator(PageNumberPaginator):
    """Page-number paginator that stops on the `has_more` flag.

    The list endpoints wrap their rows in `{"data": {"items": ..., "has_more": bool, "page": int}}`,
    so `has_more: false` ends the walk without paying for the extra empty page. The survey endpoints
    return a bare array under `data` with no flag, and fall back to the base class's stop-on-empty.
    """

    def __init__(self) -> None:
        super().__init__(base_page=FIRST_PAGE, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return

        try:
            body = response.json()
        except ValueError:
            return

        if not isinstance(body, dict):
            return
        envelope = body.get("data")
        if isinstance(envelope, dict) and envelope.get("has_more") is False:
            self._has_next_page = False


def _flatten_vote_user(row: dict[str, Any]) -> dict[str, Any]:
    """Lift the voter's id to the row root so `Votes` has a usable primary key.

    A vote has no id of its own and nests the voter under `user`, which the (post id, user id)
    primary key cannot address.
    """
    user = row.get("user")
    row["user_id"] = user.get("user_id") if isinstance(user, dict) else None
    return row


# Per-row reshaping the `data_selector` can't express, keyed by endpoint. Only the fan-out
# endpoints need one today.
DATA_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {"Votes": _flatten_vote_user}


def _format_survey_date(value: Any) -> str:
    """Format an incremental cursor value as the `YYYY-MM-DD` date `date_start` takes, less the
    replacement-window lookback (see SURVEY_LOOKBACK_DAYS)."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    capped = min(normalized, datetime.now(UTC))
    return max(capped - timedelta(days=SURVEY_LOOKBACK_DAYS), EPOCH).strftime("%Y-%m-%d")


def _incremental_window(field_name: str) -> IncrementalConfig:
    return {
        "cursor_path": field_name,
        "start_param": SURVEY_START_PARAM,
        "initial_value": "1970-01-01",
        "convert": _format_survey_date,
    }


def _resolve_incremental_field(config: SleekplanEndpointConfig, incremental_field: str | None) -> str:
    """The user's chosen cursor, as long as the endpoint advertises it."""
    advertised = {field["field"] for field in config.incremental_fields}
    if incremental_field in advertised:
        return cast(str, incremental_field)
    return config.default_incremental_field or next(iter(advertised))


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SLEEKPLAN_BASE_URL,
        # Framework auth rather than a hand-built header, so the key is redacted from logs and
        # captured samples.
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
        # `capture=False`: Sleekplan is a feedback board, so responses carry arbitrary
        # user-authored content -- post/comment bodies, voter emails, survey free-text -- that
        # the generic name-based scrubber can't anonymize. Same reasoning as Frill and
        # Featurebase, the other feedback-board sources. Requests are still metered and logged.
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
    }


def _endpoint_params(config: SleekplanEndpointConfig) -> dict[str, Any]:
    return {"per_page": config.page_size, **config.params}


def _resource(
    config: SleekplanEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> EndpointResource:
    endpoint_config: Endpoint = {
        "path": config.path,
        "params": _endpoint_params(config),
        "data_selector": config.data_selector,
        "paginator": SleekplanPaginator(),
    }

    use_merge = should_use_incremental_field and bool(config.incremental_fields)
    if use_merge:
        endpoint_config["incremental"] = _incremental_window(_resolve_incremental_field(config, incremental_field))

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_merge else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: SleekplanEndpointConfig, items_fn: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key,
        sort_mode=config.sort_mode,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the cheapest authenticated list call.

    A Sleekplan API key inherits its owner's dashboard permissions, so a 403 means the key is real
    but its owner cannot read that resource. That is only fatal for the schema being checked -- at
    source-create time the key itself is still valid.
    """
    is_valid, status_code = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), capture=False),
        f"{SLEEKPLAN_BASE_URL}/users?per_page=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if is_valid:
        return True, None

    if status_code == 401:
        return False, "Invalid Sleekplan API key."
    if status_code == 403:
        if schema_name is None:
            return True, None
        return False, f"This Sleekplan API key does not have permission to read {schema_name}."
    if status_code is None:
        return False, "Could not reach the Sleekplan API."
    return False, f"Sleekplan API returned an unexpected status ({status_code})."


def sleekplan_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SleekplanResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SLEEKPLAN_ENDPOINTS[endpoint]
    client_config = _client_config(api_key)

    if config.fanout is not None:
        return _fan_out_source(config, client_config, team_id, job_id, resumable_source_manager)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.page is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The hook fires after a page is yielded, so a crash re-fetches the checkpointed page
        # (merge dedupes it) rather than skipping rows. Redis TTL cleans up on completion.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(SleekplanResumeConfig(page=int(state["page"])))

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [_resource(config, should_use_incremental_field, incremental_field)],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(config, lambda: resource)


def _fan_out_source(
    config: SleekplanEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SleekplanResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = SLEEKPLAN_ENDPOINTS[config.fanout.parent_name]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.fanout_state is not None:
            initial_paginator_state = resume_config.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(SleekplanResumeConfig(fanout_state=state))

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=SLEEKPLAN_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="per_page",
            parent_endpoint_extra={
                "paginator": SleekplanPaginator(),
                "data_selector": parent_config.data_selector,
            },
            child_endpoint_extra={
                "paginator": SleekplanPaginator(),
                "data_selector": config.data_selector,
            },
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )
    data_map = DATA_MAPS.get(config.name)
    if data_map is not None:
        resource = resource.add_map(data_map)

    items = cast(Iterable[Any], resource)
    return _make_source_response(config, lambda: items)


__all__ = ["SleekplanResumeConfig", "sleekplan_source", "validate_credentials"]
