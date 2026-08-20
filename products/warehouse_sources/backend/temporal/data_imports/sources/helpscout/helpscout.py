from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.helpscout.settings import (
    HELP_SCOUT_API_BASE,
    HELP_SCOUT_ENDPOINTS,
    HelpScoutEndpointConfig,
)

# Help Scout paginates every list endpoint via the HAL `_links.next.href` URL, which is
# self-contained (carries its own query string), so it's all we ever need to persist or send.
_NEXT_URL_PATH = "_links.next.href"

_AUTH_ERROR = (
    "Help Scout authentication failed. Check your client ID and client secret, and confirm the "
    "app has an active user invited to your Help Scout account."
)


@frozen
class HelpScoutResumeConfig:
    # Top-level endpoints: the HAL next-page URL.
    next_url: str = ""
    # Fan-out (threads): the framework's dependent-resource resume state
    # (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: Optional[dict[str, Any]] = None


def _client_config(access_token: str) -> ClientConfig:
    return {
        "base_url": HELP_SCOUT_API_BASE,
        "auth": BearerTokenAuth(token=access_token),
        "paginator": JSONResponsePaginator(next_url_path=_NEXT_URL_PATH),
        # Pagination follows absolute `_links.next.href` URLs straight out of the response body,
        # and a resumed sync replays one that was persisted earlier. Pin every outgoing request to
        # the Help Scout API host and reject redirects, so a spoofed or tampered link can't replay
        # the bearer token against another origin (SSRF / credential exfiltration).
        # `allowed_hosts=[]` means "the base_url host only".
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _format_since(value: Any) -> str:
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _list_params(
    config: HelpScoutEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    if not config.supports_sort:
        return {}

    if should_use_incremental_field and config.updated_since_param and db_incremental_field_last_value is not None:
        sort_field = incremental_field or config.default_incremental_field or "modifiedAt"
        return {
            config.updated_since_param: _format_since(db_incremental_field_last_value),
            "sortField": sort_field,
            "sortOrder": "asc",
        }

    # Full refresh: an explicit stable sort avoids page-boundary skips/duplicates from rows
    # created while the sync is paginating (Help Scout doesn't document its default sort order).
    return {"sortField": config.partition_key or "createdAt", "sortOrder": "asc"}


def _top_level_resource(
    client_config: ClientConfig,
    config: HelpScoutEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HelpScoutResumeConfig],
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Any,
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _list_params(
                        config, should_use_incremental_field, incremental_field, db_incremental_field_last_value
                    ),
                    "data_selector": f"_embedded.{config.embedded_key}",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-yields the last page (merge dedupes on the
        # primary key) rather than skipping it; persist only while a next page remains.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(HelpScoutResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _threads_resource(
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HelpScoutResumeConfig],
) -> Resource:
    threads_config = HELP_SCOUT_ENDPOINTS["threads"]
    assert threads_config.fanout is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(HelpScoutResumeConfig(fanout_state=state))

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=HELP_SCOUT_ENDPOINTS,
            child_endpoint="threads",
            fanout=threads_config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Help Scout list endpoints take no page-size param — page size is fixed server-side.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
            parent_endpoint_extra={
                "paginator": JSONResponsePaginator(next_url_path=_NEXT_URL_PATH),
                "data_selector": "_embedded.conversations",
            },
            child_endpoint_extra={
                "paginator": JSONResponsePaginator(next_url_path=_NEXT_URL_PATH),
                "data_selector": "_embedded.threads",
            },
        ),
    )


def helpscout_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HelpScoutResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HELP_SCOUT_ENDPOINTS[endpoint]
    client_config = _client_config(access_token)

    if config.fanout:
        resource: Resource = _threads_resource(client_config, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(
            client_config,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            incremental_field,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(
    access_token: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    auth = BearerTokenAuth(token=access_token)

    if schema_name is None:
        # Help Scout tokens carry the authorizing user's full Mailbox API access, so there are no
        # per-resource scopes to probe. /users/me is the cheapest call that proves the token works.
        ok, status = validate_via_probe(
            lambda: make_tracked_session(redact_values=(access_token,)),
            f"{HELP_SCOUT_API_BASE}/users/me",
            auth=auth,
        )
        if ok:
            return True, None
        return False, _AUTH_ERROR

    config = HELP_SCOUT_ENDPOINTS.get(schema_name)
    if config is None:
        return False, f"Unknown Help Scout table '{schema_name}'"
    # threads has no bare list endpoint (it's always scoped to a conversation); probe
    # conversations instead, since that's the parent it fans out from.
    probe_path = HELP_SCOUT_ENDPOINTS["conversations"].path if config.fanout else config.path

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{HELP_SCOUT_API_BASE}{probe_path}",
        auth=auth,
    )
    if ok:
        return True, None
    if status == 401:
        return False, _AUTH_ERROR
    return False, f"Help Scout API returned an unexpected status ({status}) while checking access to {schema_name}."
