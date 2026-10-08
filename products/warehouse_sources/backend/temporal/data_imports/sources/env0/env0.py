import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import (
    ENV0_ENDPOINTS,
    Env0EndpointConfig,
)

ENV0_BASE_URL = "https://api.env0.com"
# Environments/deployments/teams list endpoints cap pages at 100 items.
PAGE_SIZE = 100


@dataclasses.dataclass
class Env0ResumeConfig:
    # Legacy fields from the hand-rolled fan-out (a parent bookmark plus a per-parent offset). Kept
    # (now with defaults) so state written by the previous implementation still deserializes via
    # `ResumableSourceManager._load_json`.
    parent_id: str | None = None
    offset: str | None = None
    # Framework paginator / fan-out resume snapshot for the current endpoint. When only the legacy
    # fields are present (old saved state) this is None and the sync restarts from the first page —
    # a re-fetch, which the merge dedupes on the primary key.
    paginator_state: Optional[dict[str, Any]] = None


def _format_date_window_value(value: Any) -> Optional[str]:
    """Format an incremental cursor as YYYY-MM-DDTHH:mm:ss.sssZ, the format env0's
    fromDate/toDate params require."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _build_date_window_params(
    config: Env0EndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Build the fromDate/toDate server-side window for incremental syncs.

    env0 requires both params together, so the window runs from the watermark (minus the
    endpoint's lookback, letting rows that mutated after first fetch be re-pulled and merged)
    up to now.
    """
    if not config.supports_date_window or not should_use_incremental_field:
        return {}

    if db_incremental_field_last_value is None:
        return {}

    from_value = db_incremental_field_last_value
    if config.incremental_lookback is not None and isinstance(from_value, datetime | date):
        if isinstance(from_value, datetime):
            from_value = from_value - config.incremental_lookback
        else:
            from_value = datetime.combine(from_value, datetime.min.time(), tzinfo=UTC) - config.incremental_lookback

    from_date = _format_date_window_value(from_value)
    if from_date is None:
        return {}

    return {"fromDate": from_date, "toDate": _format_date_window_value(datetime.now(UTC)) or ""}


def _paginator_for(config: Env0EndpointConfig) -> BasePaginator:
    if config.data_key and config.paginated:
        # Teams returns {"teams": [...], "nextPageKey": ...}; the next request sends the returned
        # nextPageKey back as the `offset` query param. Other wrapped endpoints (organization
        # costs, drift causes) return the whole collection in one object.
        return JSONResponseCursorPaginator(cursor_path="nextPageKey", cursor_param="offset")
    if config.paginated:
        # env0 has no top-level total; termination is a short/empty page (OffsetPaginator default).
        return OffsetPaginator(limit=PAGE_SIZE, total_path=None)
    return SinglePagePaginator()


def _row_transform(
    config: Env0EndpointConfig, parent_resource_name: Optional[str]
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Per-item reshape: drop huge free-text blobs and secret-bearing fields, lift a nested object
    into the row root, rename injected parent fields to their documented columns, and fill blank
    primary key parts."""
    strip = set(config.strip_fields)
    flatten = config.flatten_field
    injected = (
        {
            f"_{parent_resource_name}_{parent_field}": column
            for parent_field, column in config.inject_parent_fields.items()
        }
        if parent_resource_name
        else {}
    )
    # A NULL primary key part never matches on merge, so the row would be inserted again on every
    # sync instead of updated. Injected columns always carry a parent value, so they are excluded.
    nullable_key_fields = [key for key in config.primary_keys if key not in injected.values()]

    def _transform(row: dict[str, Any]) -> dict[str, Any]:
        out = {key: value for key, value in row.items() if key not in strip}
        nested = out.pop(flatten, None) if flatten else None
        if isinstance(nested, dict):
            out = {**nested, **out}
        for injected_key, column in injected.items():
            if injected_key in out:
                out[column] = out.pop(injected_key)
        for key in nullable_key_fields:
            if out.get(key) is None:
                out[key] = ""
        return out

    return _transform


def _organizations_parent() -> EndpointResource:
    """Organizations list used only to resolve org ids. Every fan-out chain starts here."""
    return {
        "name": "organizations",
        "endpoint": {"path": ENV0_ENDPOINTS["organizations"].path, "paginator": SinglePagePaginator()},
    }


def _environments_parent() -> EndpointResource:
    """Environments list (one request chain per organization) used only to resolve environment ids
    for the environment-level fan-out. The nested latest deployment is excluded to keep enumeration
    light, mirroring the old `_list_environment_ids`."""
    env_config = ENV0_ENDPOINTS["environments"]
    return {
        "name": "environments",
        "endpoint": {
            "path": f"{env_config.path}?{env_config.org_id_param}={{org_id}}",
            "params": {
                "org_id": {"type": "resolve", "resource": "organizations", "field": "id"},
                **env_config.params,
            },
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
    }


def _projects_parent() -> EndpointResource:
    """Projects list (one request chain per organization) used only to resolve project ids for the
    project-level fan-out."""
    projects_config = ENV0_ENDPOINTS["projects"]
    return {
        "name": "projects",
        "endpoint": {
            "path": f"{projects_config.path}?{projects_config.org_id_param}={{org_id}}",
            "params": {"org_id": {"type": "resolve", "resource": "organizations", "field": "id"}},
            "paginator": SinglePagePaginator(),
        },
    }


def _deployments_parent(date_window_params: dict[str, str]) -> EndpointResource:
    """Deployments list (one request chain per environment) used only to resolve deployment ids for
    the deployment-level fan-out. The incremental window lands here rather than on the child, so a
    run only visits deployments that started inside it. Otherwise every sync would re-walk every
    deployment the account has ever made."""
    deployments_config = ENV0_ENDPOINTS["deployments"]
    return {
        "name": "deployments",
        "endpoint": {
            "path": deployments_config.path,
            "params": {
                "parent_id": {"type": "resolve", "resource": "environments", "field": "id"},
                **date_window_params,
            },
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
    }


def _target_resource(
    config: Env0EndpointConfig, parent_resource_name: Optional[str], extra_params: dict[str, str]
) -> EndpointResource:
    params: dict[str, Any] = {**config.params, **extra_params}

    if parent_resource_name == "organizations" and config.org_id_param:
        # Org id rides in a query param; embed the placeholder in the path so the resolve binding
        # lands in the query string (the resolve mechanism only substitutes into the path).
        path = f"{config.path}?{config.org_id_param}={{org_id}}"
        params["org_id"] = {"type": "resolve", "resource": "organizations", "field": "id"}
    elif parent_resource_name is not None:
        # The parent id is embedded directly in the path (/teams/organizations/{parent_id},
        # /costs/projects/{parent_id}, /environments/deployments/{parent_id}/resources).
        path = config.path
        params["parent_id"] = {"type": "resolve", "resource": parent_resource_name, "field": "id"}
    else:
        path = config.path

    endpoint: Endpoint = {"path": path, "params": params, "paginator": _paginator_for(config)}
    if config.data_key:
        endpoint["data_selector"] = config.data_key
    if config.scope in ("project", "environment", "deployment"):
        # A 404 deep in the fan-out means the parent was deleted mid-sync or (for costs) cost
        # monitoring isn't configured, so skip it rather than failing the sync.
        endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]

    resource: EndpointResource = {"name": config.name, "endpoint": endpoint}
    if config.inject_parent_fields and parent_resource_name:
        resource["include_from_parent"] = list(config.inject_parent_fields)
    resource["data_map"] = _row_transform(config, parent_resource_name)
    return resource


def _build_resources(config: Env0EndpointConfig, date_window_params: dict[str, str]) -> list[EndpointResource | str]:
    if config.scope == "organization":
        return [_organizations_parent(), _target_resource(config, "organizations", {})]
    if config.scope == "project":
        return [_organizations_parent(), _projects_parent(), _target_resource(config, "projects", {})]
    if config.scope == "environment":
        return [
            _organizations_parent(),
            _environments_parent(),
            _target_resource(config, "environments", date_window_params),
        ]
    if config.scope == "deployment":
        return [
            _organizations_parent(),
            _environments_parent(),
            _deployments_parent(date_window_params),
            _target_resource(config, "deployments", {}),
        ]
    return [_target_resource(config, None, {})]


def env0_source(
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Env0ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ENV0_ENDPOINTS[endpoint]

    date_window_params = _build_date_window_params(
        config, should_use_incremental_field, db_incremental_field_last_value
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ENV0_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Auth (Basic) is supplied via the framework config so the secret is redacted from raised
            # errors; only the non-secret Accept header is set above.
            "auth": {"type": "http_basic", "username": api_key_id, "password": api_key_secret},
            "paginator": SinglePagePaginator(),
            # capture=False: response bodies carry deployment secrets (variable `value`s, injected
            # oidcToken/vcsAccessToken) that the name-based scrubbers don't recognise, and the
            # environments enumeration can carry the same secrets nested under latestDeploymentLog.
            # Keep them out of sample capture; requests stay metered and logged.
            "session": make_tracked_session(capture=False),
        },
        "resource_defaults": {},
        "resources": _build_resources(config, date_window_params),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework saves AFTER a page is yielded so a crash re-yields the last page (merge
        # dedupes on the primary key) rather than skipping it. Multi-level (environment) fan-out
        # disables resume entirely, so this is never called for those endpoints.
        if state:
            resumable_source_manager.save_state(Env0ResumeConfig(paginator_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    target = next(resource for resource in resources if resource.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: target,
        primary_keys=config.primary_keys,
        # env0 doesn't document list ordering and the deployments endpoint fans out per
        # environment, so the incremental watermark must only persist at successful job end —
        # "desc" gives exactly that. Full-refresh endpoints have no watermark to protect.
        sort_mode="desc" if config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=target.column_hints,
    )


def validate_credentials(api_key_id: str, api_key_secret: str) -> bool:
    """Confirm the API key pair is valid. /organizations is a cheap authenticated probe that
    works for both organization and personal API keys."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key_secret,)),
        f"{ENV0_BASE_URL}/organizations",
        auth=HTTPBasicAuth(api_key_id, api_key_secret),
    )
    return ok
