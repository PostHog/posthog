from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    ParentRowFilter,
    ResponseAction,
)

logger = structlog.get_logger(__name__)


class FanoutEndpointLike(Protocol):
    name: str
    path: str
    incremental_fields: list[Any]
    default_incremental_field: str | None
    page_size: int


@dataclass(frozen=True)
class DependentEndpointConfig:
    parent_name: str
    resolve_param: str
    resolve_field: str
    include_from_parent: list[str]
    parent_field_renames: dict[str, str] = field(default_factory=dict)
    parent_params: dict[str, Any] = field(default_factory=dict)
    child_params: dict[str, Any] = field(default_factory=dict)
    # Applied to the CHILD request only. Use this to tolerate a per-parent-item failure (e.g. a
    # 404 for a parent row deleted/merged between the parent listing and this child fetch)
    # without failing the whole fan-out — see resource.py's response_actions "ignore" handling.
    child_response_actions: list[ResponseAction] = field(default_factory=list)
    # "api" re-fetches the parent endpoint each child sync (legacy behavior). "warehouse"
    # drives the child from the parent schema's already-synced Delta table when that table is
    # usable, and falls back to "api" for the run when it isn't — see
    # `_warehouse_parent_reuse_available` in `import_data_activity_sync`.
    parent_source: Literal["api", "warehouse"] = "api"
    # Floors a parent_source="warehouse" scan to the API path's effective row set. The snapshot
    # accumulates every parent row ever synced while the vendor's list endpoint usually windows
    # what it returns, so an unbounded scan fans out over parents the API path never would.
    # Leave None only when the parent endpoint genuinely returns the full collection.
    parent_row_filter: ParentRowFilter | None = None


def required_parents_from_endpoint_configs(endpoint_configs: Mapping[str, Any], schema_name: str) -> list[str]:
    """Parents a schema reads from the warehouse when they're available, from its fan-out config.

    Generic wiring for `get_required_parent_schemas` overrides: returns the parent for
    endpoints whose fan-out reads the parent from the warehouse, `[]` otherwise.
    """
    config = endpoint_configs.get(schema_name)
    fanout = getattr(config, "fanout", None)
    if fanout is not None and fanout.parent_source == "warehouse":
        return [fanout.parent_name]
    return []


def rename_parent_fields(parent_name: str, renames: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if not renames:
        return lambda row: row

    key_map = {f"_{parent_name}_{src}": dst for src, dst in renames.items()}

    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for prefixed_key, target_key in key_map.items():
            if prefixed_key in row:
                row[target_key] = row.pop(prefixed_key)
        return row

    return _mapper


def build_dependent_resource(
    *,
    endpoint_configs: Mapping[str, FanoutEndpointLike],
    child_endpoint: str,
    fanout: DependentEndpointConfig,
    client_config: ClientConfig,
    path_format_values: dict[str, str],
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    incremental_config_factory: Callable[[str], IncrementalConfig | None] | None = None,
    parent_endpoint_extra: Endpoint | None = None,
    child_endpoint_extra: Endpoint | None = None,
    child_params_extra: dict[str, Any] | None = None,
    page_size_param: str | None = "limit",
    resume_hook: Callable[[dict[str, Any] | None], None] | None = None,
    initial_paginator_state: dict[str, Any] | None = None,
    source_id: str | None = None,
    use_warehouse_parent: bool = False,
    parent_snapshot_at: datetime | None = None,
) -> Iterable[Any]:
    parent_config = endpoint_configs[fanout.parent_name]
    child_config = endpoint_configs[child_endpoint]

    warehouse_parent = fanout.parent_source == "warehouse" and use_warehouse_parent

    # page_size_param=None is for APIs whose list endpoints take no page-size param at all
    # (unpaginated, full-collection responses) — sending one would be an undocumented param.
    parent_params: dict[str, Any] = {} if page_size_param is None else {page_size_param: parent_config.page_size}
    parent_params.update(fanout.parent_params)

    parent_path = parent_config.path
    for key, value in path_format_values.items():
        parent_path = parent_path.replace(f"{{{key}}}", value)

    parent_endpoint_config: Endpoint = {
        "path": parent_path,
        "params": parent_params,
    }
    if parent_endpoint_extra:
        if "params" in parent_endpoint_extra:
            raise ValueError(
                "Do not pass 'params' in parent_endpoint_extra. Use fanout.parent_params or page_size_param instead."
            )
        parent_endpoint_config.update(parent_endpoint_extra)

    parent_resource: EndpointResource = {
        "name": fanout.parent_name,
        "table_name": fanout.parent_name,
        "write_disposition": "replace",
        "endpoint": parent_endpoint_config,
        "table_format": "delta",
    }

    if warehouse_parent:
        if not source_id:
            raise ValueError("source_id is required when a fan-out reads its parent from the warehouse")
        # noqa reason: keeps deltalake/pyarrow off the import path of every source module —
        # the reader stack loads only when a warehouse-parent fan-out actually runs.
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (  # noqa: PLC0415
            iter_parent_pages_from_warehouse,
            try_resolve_parent_table,
        )

        # Resolve the parent's table now, while we're in sync source-build context — the
        # iterator itself runs later on executor threads where ad-hoc ORM reads are fragile.
        # This also pins the Delta version the whole fan-out reads, and validates the columns
        # while a fallback is still possible.
        parent_columns = list(dict.fromkeys([fanout.resolve_field, *fanout.include_from_parent]))
        parent_table = try_resolve_parent_table(
            team_id=team_id,
            source_id=source_id,
            parent_name=fanout.parent_name,
            required_columns=parent_columns,
            schema_name=child_endpoint,
            row_filter=fanout.parent_row_filter,
        )
        if parent_table is None:
            # Drop back to the API parent entirely, including the snapshot-only 404 handling
            # below, so the child syncs exactly the way it does without this feature.
            warehouse_parent = False
        else:
            parent_resource["data_iterator"] = lambda: iter_parent_pages_from_warehouse(
                table=parent_table,
                parent_name=fanout.parent_name,
                columns=parent_columns,
                page_size=parent_config.page_size,
                schema_name=child_endpoint,
                row_filter=fanout.parent_row_filter,
            )

    child_path = child_config.path
    for key, value in path_format_values.items():
        child_path = child_path.replace(f"{{{key}}}", value)

    child_params: dict[str, Any] = {
        fanout.resolve_param: {
            "type": "resolve",
            "resource": fanout.parent_name,
            "field": fanout.resolve_field,
        },
    }
    if page_size_param is not None:
        child_params[page_size_param] = child_config.page_size
    # The resolve param binds child requests to their parent row. A config that reuses that key
    # would clobber the binding, so reject it loudly rather than silently dropping the value.
    if fanout.resolve_param in fanout.child_params:
        raise ValueError(
            f"child_params must not include the resolve param '{fanout.resolve_param}'; "
            "it is managed by build_dependent_resource."
        )
    child_params.update(fanout.child_params)
    if child_params_extra:
        child_params.update(child_params_extra)
    child_endpoint_config: Endpoint = {
        "path": child_path,
        "params": child_params,
    }
    if fanout.child_response_actions:
        child_endpoint_config["response_actions"] = fanout.child_response_actions
    if child_endpoint_extra:
        if "params" in child_endpoint_extra:
            raise ValueError(
                "Do not pass 'params' in child_endpoint_extra. "
                "The child resolve/page-size params are managed by build_dependent_resource."
            )
        child_endpoint_config.update(child_endpoint_extra)

    if warehouse_parent and "response_actions" not in child_endpoint_config:
        # The warehouse snapshot can contain parents deleted upstream since the parent's
        # last sync (incremental parents accumulate); their child fetch 404s. A fresh API
        # parent pull would simply not list them, so treat 404 as an empty child.
        child_endpoint_config["response_actions"] = [{"status_code": 404, "action": "ignore"}]

    use_merge = should_use_incremental_field and bool(child_config.incremental_fields)
    if use_merge:
        if incremental_config_factory is None:
            raise ValueError("incremental_config_factory is required for incremental fan-out resources")
        incremental = incremental_config_factory(incremental_field or child_config.default_incremental_field or "id")
        # A factory returns None for a child endpoint that has no server-side time filter to bind
        # the cursor to. Such a child still merges on its primary key, which is what lets a caller
        # bound the request set through the fan-out parent instead of through a request window.
        if incremental is not None:
            child_endpoint_config["incremental"] = incremental

    child_resource: EndpointResource = {
        "name": child_endpoint,
        "table_name": child_endpoint,
        "write_disposition": ({"disposition": "merge", "strategy": "upsert"} if use_merge else "replace"),
        "include_from_parent": fanout.include_from_parent,
        "endpoint": child_endpoint_config,
        "table_format": "delta",
    }

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [parent_resource, child_resource],
    }

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    child_dlt_resource = next(r for r in resources if getattr(r, "name", None) == child_endpoint)
    child = child_dlt_resource.add_map(rename_parent_fields(fanout.parent_name, fanout.parent_field_renames))

    # Capping belongs here rather than in the caller because only this function knows whether the
    # run ended up on the warehouse parent: `warehouse_parent` is false when the table turned out
    # to be unresolvable, and a caller reading its own config would still see "warehouse" and cap a
    # live API response, dropping rows that path had no reason to hold back.
    if warehouse_parent and parent_snapshot_at is not None:
        # `getattr` because a source that never merges can omit the field entirely, and the read
        # has to stay off the path those sources take.
        cursor_field = incremental_field or getattr(child_config, "default_incremental_field", None)
        if not cursor_field:
            raise ValueError(
                f"'{child_endpoint}' asks for a parent snapshot cap but declares no incremental field to "
                "cap on; capping nothing would let its watermark run past the snapshot"
            )
        child = child.add_filter(_not_newer_than(cursor_field, parent_snapshot_at))
    return child


def _not_newer_than(field: str, snapshot_at: datetime) -> Callable[[dict[str, Any]], bool]:
    """Keep rows the parent snapshot could already account for.

    A row without the field carries no recency signal and is kept, matching how the parent row
    filter treats NULLs.
    """

    def _keep(row: dict[str, Any]) -> bool:
        value = parse_datetime_value(row.get(field))
        return value is None or value <= snapshot_at

    return _keep
