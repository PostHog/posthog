import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_chained_resource,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.settings import (
    FRESHDESK_ENDPOINTS,
    IGNORE_DELETED_PARENT,
    PER_PAGE,
    FreshdeskEndpointConfig,
)

VALIDATE_TIMEOUT = 10


@dataclasses.dataclass
class FreshdeskResumeConfig:
    next_url: str


def normalize_subdomain(domain: str) -> str:
    """Accept either a bare subdomain ("acme") or a full host ("acme.freshdesk.com")."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    return domain.removesuffix(".freshdesk.com")


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.freshdesk.com"


def _format_updated_since(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC string Freshdesk expects."""
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_params(
    config: FreshdeskEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}
    params.update(config.extra_params)

    if should_use_incremental_field and config.updated_since_param and db_incremental_field_last_value:
        params[config.updated_since_param] = _format_updated_since(db_incremental_field_last_value)

    return params


def _client_config(subdomain: str, api_key: str) -> ClientConfig:
    return {
        "base_url": _base_url(subdomain),
        "headers": {"Content-Type": "application/json"},
        # Freshdesk uses HTTP Basic auth with the API key as the username and any
        # non-empty string as the password. Supplied via framework auth so the value
        # is redacted from logs.
        "auth": {"type": "http_basic", "username": api_key, "password": "X"},
        # Freshdesk paginates with an RFC 5988 `Link: ...; rel="next"` header.
        "paginator": HeaderLinkPaginator(),
    }


def _windowed_fanout(
    fanout: DependentEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> DependentEndpointConfig:
    """Bound the parent walk of a child endpoint that has no timestamp filter of its own.

    Without this the child re-fetches every parent's full history each sync. Filtering the
    parent on its own `updated_since` cannot hide a child we still need: Freshdesk touches a
    parent's `updated_at` whenever one of its children changes, so a child newer than the
    watermark only ever hangs off a parent the filter keeps.
    """
    parent = FRESHDESK_ENDPOINTS[fanout.parent_name]
    if not (should_use_incremental_field and parent.updated_since_param and db_incremental_field_last_value):
        return fanout

    return dataclasses.replace(
        fanout,
        parent_params={
            **fanout.parent_params,
            parent.updated_since_param: _format_updated_since(db_incremental_field_last_value),
        },
    )


def _fanout_resource(
    endpoint: str,
    config: FreshdeskEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterable[Any]:
    assert config.fanout is not None
    return cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=FRESHDESK_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=_windowed_fanout(config.fanout, should_use_incremental_field, db_incremental_field_last_value),
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            # No Freshdesk sub-resource takes a timestamp filter, so the cursor binds to no
            # request param. The child still merges on its primary key.
            incremental_config_factory=lambda _field: None,
            page_size_param="per_page",
            resume_hook=resume_hook,
            initial_paginator_state=initial_paginator_state,
        ),
    )


def _chained_fanout_resource(
    endpoint: str,
    config: FreshdeskEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
) -> Iterable[Any]:
    """Build a solution categories -> folders -> articles chain and return the articles child."""
    chained = config.chained_fanout
    assert chained is not None
    middle_config = FRESHDESK_ENDPOINTS[chained.parent_name]
    middle_fanout = middle_config.fanout
    if middle_fanout is None:
        raise ValueError(f"'{chained.parent_name}' does not fan out from a top-level endpoint")
    root_config = FRESHDESK_ENDPOINTS[middle_fanout.parent_name]

    def _resource(
        cfg: FreshdeskEndpointConfig,
        params: dict[str, Any],
        include_from_parent: list[str] | None = None,
    ) -> EndpointResource:
        endpoint_config: Endpoint = {"path": cfg.path, "params": params, "data_selector": cfg.data_key}
        if include_from_parent is not None:
            endpoint_config["response_actions"] = IGNORE_DELETED_PARENT
        resource: EndpointResource = {
            "name": cfg.name,
            "table_name": cfg.name,
            "write_disposition": "replace",
            "endpoint": endpoint_config,
            "table_format": "delta",
        }
        if include_from_parent is not None:
            resource["include_from_parent"] = include_from_parent
        return resource

    root = _resource(root_config, {"per_page": root_config.page_size})
    middle = _resource(
        middle_config,
        {
            "per_page": middle_config.page_size,
            middle_fanout.resolve_param: {
                "type": "resolve",
                "resource": root_config.name,
                "field": middle_fanout.resolve_field,
            },
        },
    )
    child = _resource(
        config,
        {
            "per_page": config.page_size,
            chained.resolve_param: {
                "type": "resolve",
                "resource": middle_config.name,
                "field": chained.resolve_field,
            },
        },
        # Article rows already carry `folder_id` and `category_id`.
        include_from_parent=[],
    )

    return build_chained_resource(
        resources=[root, middle, child],
        child_name=endpoint,
        parent_name=middle_config.name,
        parent_field_renames={},
        client_config=client_config,
        team_id=team_id,
        job_id=job_id,
    )


def freshdesk_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshdeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = FRESHDESK_ENDPOINTS[endpoint]
    client_config = _client_config(subdomain, api_key)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(FreshdeskResumeConfig(next_url=state["next_url"]))

    resource: Iterable[Any]
    if config.chained_fanout is not None:
        resource = _chained_fanout_resource(endpoint, config, client_config, team_id, job_id)
    elif config.fanout is not None:
        resource = _fanout_resource(
            endpoint,
            config,
            client_config,
            team_id,
            job_id,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
            save_checkpoint,
            initial_paginator_state,
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": _build_params(config, should_use_incremental_field, db_incremental_field_last_value),
                        # Most list endpoints return a bare array; a few (e.g. skills) wrap it in an object.
                        "data_selector": config.data_key,
                    },
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value if should_use_incremental_field else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_key: str) -> Optional[int]:
    """Probe the Freshdesk API. Returns the HTTP status code, or ``None`` on a connection error."""
    url = f"{_base_url(subdomain)}/api/v2/tickets?per_page=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        auth=HTTPBasicAuth(api_key, "X"),
        timeout=VALIDATE_TIMEOUT,
    )
    return status
