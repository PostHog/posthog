from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests.auth import HTTPBasicAuth

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.settings import (
    FRESHSERVICE_ENDPOINTS,
    FreshserviceEndpointConfig,
)

VALIDATE_TIMEOUT = 10

# Freshservice uses HTTP Basic auth with the API key as the username and any non-empty
# string as the password.
_BASIC_AUTH_PASSWORD = "X"


@frozen
class FreshserviceResumeConfig:
    # Top-level endpoints resume from the opaque Link-header `next` URL.
    next_url: Optional[str] = None
    # Fan-out endpoints resume by parent: the child paths already swept, the one in progress,
    # and that path's paginator state — see `common.rest_source.__init__`.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def normalize_domain(domain: str) -> str:
    """Accept either a bare subdomain ("acme") or a full host ("acme.freshservice.com")."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    return domain.removesuffix(".freshservice.com")


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}.freshservice.com"


def _format_updated_since(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC string Freshservice expects."""
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _client_config(domain: str, api_key: str) -> ClientConfig:
    return {
        "base_url": _base_url(domain),
        "headers": {"Content-Type": "application/json"},
        # Auth (HTTP Basic) is supplied via the framework auth config so the credential is
        # redacted from logs rather than hand-built into an Authorization header.
        "auth": {"type": "http_basic", "username": api_key, "password": _BASIC_AUTH_PASSWORD},
        # Freshservice v2 paginates via RFC 5988 Link headers (rel="next").
        "paginator": HeaderLinkPaginator(),
    }


def _make_source_response(
    config: FreshserviceEndpointConfig,
    items: Any,
    column_hints: Optional[dict[str, Any]] = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def _top_level_source(
    config: FreshserviceEndpointConfig,
    domain: str,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshserviceResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    params: dict[str, Any] = {"per_page": config.page_size}
    params.update(config.extra_params)
    # Server-side incremental filter: only endpoints with a documented `updated_since` param
    # narrow the window, and only once a watermark exists.
    if should_use_incremental_field and config.updated_since_param and db_incremental_field_last_value:
        params[config.updated_since_param] = _format_updated_since(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": _client_config(domain, api_key),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Every Freshservice v2 list endpoint wraps its results under a resource-named
                    # key (e.g. {"tickets": [...]}). A response missing that key yields 0 rows.
                    "data_selector": config.data_key,
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
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(FreshserviceResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, lambda: resource, column_hints=resource.column_hints)


def _fanout_source(
    config: FreshserviceEndpointConfig,
    domain: str,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshserviceResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = FRESHSERVICE_ENDPOINTS[config.fanout.parent_name]

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
                FreshserviceResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=FRESHSERVICE_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(domain, api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": parent_config.data_key},
            child_endpoint_extra={"data_selector": config.data_key},
            page_size_param="per_page",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _make_source_response(config, lambda: dependent_resource)


def freshservice_source(
    api_key: str,
    domain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshserviceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FRESHSERVICE_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, domain, api_key, team_id, job_id, resumable_source_manager)

    return _top_level_source(
        config,
        domain,
        api_key,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )


def validate_credentials(domain: str, api_key: str) -> Optional[int]:
    """Probe the Freshservice API. Returns the HTTP status code, or ``None`` on a connection error."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_base_url(domain)}/api/v2/tickets?per_page=1",
        auth=HTTPBasicAuth(api_key, _BASIC_AUTH_PASSWORD),
        timeout=VALIDATE_TIMEOUT,
    )
    return status
