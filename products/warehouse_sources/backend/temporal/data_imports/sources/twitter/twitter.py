import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from requests import Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter.settings import (
    BASE_URL,
    EARLIEST_START_TIME,
    TWITTER_ENDPOINTS,
    TwitterEndpointConfig,
)

# An X handle is 1-15 characters of `[A-Za-z0-9_]`. The handle is interpolated into a request URL,
# so anything outside that set is rejected rather than escaped.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")

_REQUEST_TIMEOUT = 30

# Smallest `max_results` every paged endpoint accepts: the post timelines require at least 5, the
# user and list endpoints at least 1. Used for the permission probes, which only need the status.
_PROBE_PAGE_SIZE = 5


class TwitterUserNotFoundError(Exception):
    """The configured handle resolves to no X account."""


@frozen
class TwitterResumeConfig:
    pagination_token: str


def normalize_username(raw: str) -> str:
    """Return the bare handle, or raise when it isn't one X could issue."""
    username = raw.strip().lstrip("@")
    if not _USERNAME_RE.match(username):
        raise ValueError(
            "That doesn't look like an X handle. Enter just the handle (the 'posthog' in "
            "'x.com/posthog'), without the URL."
        )
    return username


def _session(bearer_token: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {bearer_token}"},
        redact_values=(bearer_token,),
    )


def to_rfc3339(value: Any) -> str:
    """Format an incremental watermark as the second-granularity UTC instant X expects.

    The watermark arrives as a ``datetime`` from the warehouse and as a string on the first
    incremental run (the endpoint's ``initial_value``), so both shapes are accepted.
    """
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_user_id(bearer_token: str, username: str) -> str:
    """Look the handle up as the numeric id every per-account endpoint path needs."""
    response = _session(bearer_token).get(
        f"{BASE_URL}/2/users/by/username/{normalize_username(username)}",
        params={"user.fields": "id"},
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    user_id = (response.json().get("data") or {}).get("id")
    if not user_id:
        raise TwitterUserNotFoundError(f"X has no account with the handle @{username}")
    return str(user_id)


def validate_credentials(bearer_token: str, username: str) -> tuple[bool, str | None]:
    try:
        handle = normalize_username(username)
    except ValueError as error:
        return False, str(error)

    response = _session(bearer_token).get(
        f"{BASE_URL}/2/users/by/username/{handle}",
        params={"user.fields": "id"},
        timeout=_REQUEST_TIMEOUT,
    )

    if response.status_code == 401:
        return False, "X rejected that bearer token. Generate a new one in the X developer portal and try again."
    if response.status_code == 403:
        # Unlike a scoped API, X gates whole endpoints on the project's API access, and user
        # lookup is the lowest rung. A 403 here means no table in this source can ever sync, so it
        # is reported at source-create rather than deferred to a per-table probe.
        return (
            False,
            "That token's X app cannot read user lookups. Check the app is attached to a project, "
            "and that the project has API credits, then try again.",
        )
    if response.status_code != 200:
        return False, f"X returned HTTP {response.status_code} for the handle @{handle}."

    if not (response.json().get("data") or {}).get("id"):
        return False, f"X has no account with the handle @{handle}."

    return True, None


def endpoint_permissions(bearer_token: str, username: str, endpoints: list[str]) -> dict[str, str | None]:
    """Report which tables this token's X app can actually read.

    X gates endpoints per app rather than per scope, so a token that lists posts fine still 403s on
    followers. Probing up front lets the schema picker say which tables to leave off instead of
    letting them fail on their first sync.
    """
    session = _session(bearer_token)
    results: dict[str, str | None] = {}
    user_id: str | None = None

    for name in endpoints:
        config = TWITTER_ENDPOINTS.get(name)
        if config is None:
            continue

        if config.needs_user_id and user_id is None:
            try:
                user_id = resolve_user_id(bearer_token, username)
            except Exception:
                # Nothing can be said per-table when the handle itself won't resolve; source-level
                # validation already reports that case.
                return {}

        path = config.path.format(user_id=user_id) if config.needs_user_id else config.path
        params = {"usernames": normalize_username(username)} if name == "Profile" else {"max_results": _PROBE_PAGE_SIZE}

        try:
            response = session.get(f"{BASE_URL}{path}", params=params, timeout=_REQUEST_TIMEOUT)
        except Exception:
            # A network blip is not a permission answer — report the table as reachable and let the
            # sync surface a real failure.
            results[name] = None
            continue

        if response.status_code == 403:
            results[name] = "Your X app's API access doesn't cover this endpoint."
        elif response.status_code == 401:
            results[name] = "X rejected the bearer token."
        else:
            results[name] = None

    return results


def get_resource(
    endpoint_config: TwitterEndpointConfig,
    username: str,
    user_id: str | None,
    should_use_incremental_field: bool,
) -> EndpointResource:
    path = endpoint_config.path.format(user_id=user_id) if endpoint_config.needs_user_id else endpoint_config.path

    params: dict[str, Any] = dict(endpoint_config.extra_params)
    if endpoint_config.needs_user_id:
        params["max_results"] = endpoint_config.page_size
    else:
        params["usernames"] = username

    endpoint: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "data",
        "paginator": SinglePagePaginator()
        if not endpoint_config.needs_user_id
        else JSONResponseCursorPaginator(cursor_path="meta.next_token", cursor_param="pagination_token"),
    }

    if should_use_incremental_field and endpoint_config.start_time_param:
        endpoint["incremental"] = {
            "cursor_path": "created_at",
            "start_param": endpoint_config.start_time_param,
            "initial_value": EARLIEST_START_TIME,
            "convert": to_rfc3339,
        }

    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _iter_pages(
    bearer_token: str,
    username: str,
    endpoint_config: TwitterEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TwitterResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
) -> Iterator[Any]:
    # Resolved here rather than in `twitter_source` so the handle lookup happens on the pipeline's
    # iterator thread with the rest of the endpoint's requests, not while the activity is still
    # assembling the response.
    user_id = resolve_user_id(bearer_token, username) if endpoint_config.needs_user_id else None

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": bearer_token},
            # The bearer token rides every request, so pin the host and refuse redirects: a 3xx
            # from X must not carry the credential off api.x.com.
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": _REQUEST_TIMEOUT,
        },
        "resources": [get_resource(endpoint_config, username, user_id, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.pagination_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(TwitterResumeConfig(pagination_token=str(state["cursor"])))

    yield from rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def twitter_source(
    bearer_token: str,
    username: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TwitterResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    endpoint_config = schema_for_resource(TWITTER_ENDPOINTS, endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: _iter_pages(
            bearer_token=bearer_token,
            username=username,
            endpoint_config=endpoint_config,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
        ),
        primary_keys=[endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
