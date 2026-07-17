"""Generic API Source"""

import graphlib  # type: ignore[import,unused-ignore]
from collections.abc import Callable, Iterator
from typing import Any, Optional, cast

from dateutil import parser

from .config_setup import (
    Incremental,
    IncrementalParam,
    build_resource_dependency_graph,
    create_auth,
    create_paginator,
    create_response_hooks,
    process_parent_data_item,
    setup_incremental_object,
)
from .jsonpath_utils import TJsonPath
from .paginators import BasePaginator
from .resource import Resource
from .rest_client import DEFAULT_RETRY_ATTEMPTS, RESTClient
from .typing import ClientConfig, Endpoint, EndpointResource, HTTPMethodBasic, ResolvedParam, RESTAPIConfig
from .utils import exclude_keys  # noqa: F401


def convert_types(
    data: Iterator[Any] | list[Any], types: Optional[dict[str, dict[str, Any]]]
) -> Iterator[dict[str, Any]]:
    if types is None:
        yield from data
        return

    for item in data:
        for key, column in types.items():
            data_type = column.get("data_type")

            if key in item:
                current_value = item.get(key)
                if data_type == "timestamp" and isinstance(current_value, str):
                    item[key] = parser.parse(current_value)
                elif data_type == "date" and isinstance(current_value, str):
                    item[key] = parser.parse(current_value).date()

        yield item


def rest_api_resource(
    config: RESTAPIConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
    initial_paginator_state: Optional[dict[str, Any]] = None,
) -> Resource:
    """Creates a single resource from a REST API configuration.

    Most sources define exactly one resource. Use ``rest_api_resources``
    (plural) only when the config contains multiple resources (e.g. date
    chunked report endpoints or parent/child fanout).

    ``resume_hook`` and ``initial_paginator_state`` enable integration with
    ``ResumableSourceManager``. They are only supported for non-dependent
    resources (no ``data_from`` parent/child fanout).
    """
    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    assert len(resources) == 1, f"Expected 1 resource, got {len(resources)}"
    return resources[0]


def rest_api_resources(
    config: RESTAPIConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
    initial_paginator_state: Optional[dict[str, Any]] = None,
) -> list[Resource]:
    """Creates a list of resources from a REST API configuration.

    Prefer ``rest_api_resource`` (singular) for the common single-resource
    case. This function is needed for multi-resource configs like date-chunked
    report endpoints or parent/child fanout.
    """
    client_config = config["client"]
    resource_defaults = config.get("resource_defaults") or {}
    resource_list = config["resources"]

    (
        dependency_graph,
        endpoint_resource_map,
        resolved_param_map,
    ) = build_resource_dependency_graph(
        resource_defaults,
        resource_list,
    )

    resources = create_resources(
        client_config,
        dependency_graph,
        endpoint_resource_map,
        resolved_param_map,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )

    return list(resources.values())


def _make_paginate_dependent_resource(
    *,
    client: RESTClient,
    resolved_param: ResolvedParam | list[ResolvedParam],
    include_from_parent: list[str],
    default_columns_config: Optional[Any],
    incremental_object: Optional[Incremental],
    incremental_param: Optional[IncrementalParam],
    incremental_cursor_transform: Optional[Callable[..., Any]],
    db_incremental_field_last_value: Optional[Any],
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
    initial_state: Optional[dict[str, Any]] = None,
    data_selector_required: bool = False,
) -> Callable[..., Iterator[list[Any]]]:
    """Build the generator for a dependent (child) resource.

    When ``resume_hook`` is set the fan-out is resumable: each parent's child pagination is
    checkpointed under that parent's resolved child path, so a restart skips parents already fully
    synced and resumes the one that was in progress. Parent pagination itself is not resumed — the
    (usually small) parent list is re-fetched each run and already-completed parents are skipped by
    path. Resume state shape:
    ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``.
    """
    # Closure state persists across parent-page invocations within a single run.
    seed: dict[str, Any] = dict(initial_state) if initial_state else {}
    completed: set[str] = set(seed.get("completed") or [])
    current_path: Optional[str] = seed.get("current")
    current_child_state: Optional[dict[str, Any]] = seed.get("child_state")

    def checkpoint(current: Optional[str], child_state: Optional[dict[str, Any]]) -> None:
        # resume_hook is non-None here (only called from the resumable path).
        resume_hook({"completed": sorted(completed), "current": current, "child_state": child_state})  # type: ignore[misc]

    def paginate_dependent_resource(
        items: list[dict[str, Any]],
        method: HTTPMethodBasic,
        path: str,
        params: dict[str, Any],
        paginator: Optional[BasePaginator],
        data_selector: Optional[TJsonPath],
        hooks: Optional[dict[str, Any]],
        columns_config: Optional[Any] = None,
    ) -> Iterator[list[Any]]:
        nonlocal current_path, current_child_state
        effective_columns_config = columns_config if columns_config is not None else default_columns_config

        if incremental_object:
            params = _set_incremental_params(
                params,
                incremental_object,
                incremental_param,
                incremental_cursor_transform,
                db_incremental_field_last_value,
            )

        for item in items:
            formatted_path, parent_record = process_parent_data_item(path, item, resolved_param, include_from_parent)

            if resume_hook is not None and formatted_path in completed:
                continue

            # Resume this parent's child cursor only if it's the one we were mid-way through.
            child_initial = (
                current_child_state if (resume_hook is not None and current_path == formatted_path) else None
            )

            def child_resume_hook(paginator_state: Optional[dict[str, Any]], _path: str = formatted_path) -> None:
                nonlocal current_path, current_child_state
                current_path = _path
                current_child_state = paginator_state
                checkpoint(_path, paginator_state)

            for child_page in client.paginate(
                method=method,
                path=formatted_path,
                params=dict(params),
                paginator=paginator,
                data_selector=data_selector,
                hooks=hooks,
                resume_hook=child_resume_hook if resume_hook is not None else None,
                initial_paginator_state=child_initial,
                data_selector_required=data_selector_required,
            ):
                if parent_record:
                    for child_record in child_page:
                        child_record.update(parent_record)

                yield list(convert_types(child_page, effective_columns_config))

            if resume_hook is not None:
                completed.add(formatted_path)
                current_path = None
                current_child_state = None
                checkpoint(None, None)

    return paginate_dependent_resource


def create_resources(
    client_config: ClientConfig,
    dependency_graph: graphlib.TopologicalSorter,
    endpoint_resource_map: dict[str, EndpointResource],
    resolved_param_map: dict[str, Optional[list[ResolvedParam]]],
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any] = None,
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
    initial_paginator_state: Optional[dict[str, Any]] = None,
) -> dict[str, Resource]:
    resources: dict[str, Resource] = {}

    # Resume is routed to the dependent (child) resource in a fan-out; the parent list is re-fetched
    # each run (see _make_paginate_dependent_resource). So when any resource is dependent, the
    # non-dependent resources in the same config don't consume the resume hook. With MULTIPLE
    # dependent resources (a chained/multi-level fan-out), no resource gets resume — one shared
    # hook consumed at several levels would corrupt the saved state; retries re-fetch and the
    # merge dedupes.
    dependent_count = sum(1 for rp in resolved_param_map.values() if rp is not None)
    has_dependent_resource = dependent_count > 0
    dependent_resume_hook = resume_hook if dependent_count == 1 else None
    dependent_initial_state = initial_paginator_state if dependent_count == 1 else None

    for resource_name in dependency_graph.static_order():
        resource_name = cast(str, resource_name)
        endpoint_resource = endpoint_resource_map[resource_name]
        endpoint_config = cast(Endpoint, endpoint_resource.get("endpoint"))
        request_params = endpoint_config.get("params") or {}
        request_json = endpoint_config.get("json", None)
        paginator = create_paginator(endpoint_config.get("paginator"))

        resolved_params: list[ResolvedParam] | None = resolved_param_map[resource_name]

        include_from_parent: list[str] = endpoint_resource.get("include_from_parent") or []
        if not resolved_params and include_from_parent:
            raise ValueError(
                f"Resource {resource_name} has include_from_parent but is not dependent on another resource"
            )

        (
            incremental_object,
            incremental_param,
            incremental_cursor_transform,
        ) = setup_incremental_object(request_params, endpoint_config.get("incremental"))

        client = RESTClient(
            base_url=client_config.get("base_url"),
            headers=client_config.get("headers"),
            auth=create_auth(client_config.get("auth")),
            paginator=create_paginator(client_config.get("paginator")),
            session=client_config.get("session"),
            max_retry_attempts=client_config.get("max_retries", DEFAULT_RETRY_ATTEMPTS),
            allowed_hosts=client_config.get("allowed_hosts"),
            allow_redirects=client_config.get("allow_redirects", True),
        )

        hooks = create_response_hooks(endpoint_config.get("response_actions"))

        resource_kwargs = exclude_keys(endpoint_resource, {"endpoint", "include_from_parent", "data_map"})

        columns_config = endpoint_resource.get("columns")

        hints = {
            k: v
            for k, v in resource_kwargs.items()
            if k
            in (
                "columns",
                "write_disposition",
                "table_name",
                "table_format",
                "merge_key",
                "schema_contract",
            )
        }

        if resolved_params is None:

            def paginate_resource(
                method: HTTPMethodBasic,
                path: str,
                params: dict[str, Any],
                json: Optional[dict[str, Any]],
                paginator: Optional[BasePaginator],
                data_selector: Optional[TJsonPath],
                hooks: Optional[dict[str, Any]],
                client: RESTClient = client,
                columns_config: Optional[Any] = None,
                incremental_object: Optional[Incremental] = incremental_object,
                incremental_param: Optional[IncrementalParam] = incremental_param,
                incremental_cursor_transform: Optional[Callable[..., Any]] = incremental_cursor_transform,
                resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = (
                    None if has_dependent_resource else resume_hook
                ),
                initial_paginator_state: Optional[dict[str, Any]] = (
                    None if has_dependent_resource else initial_paginator_state
                ),
                data_selector_required: bool = bool(endpoint_config.get("data_selector_required")),
            ) -> Iterator[list[Any]]:
                if incremental_object:
                    params = _set_incremental_params(
                        params,
                        incremental_object,
                        incremental_param,
                        incremental_cursor_transform,
                        db_incremental_field_last_value,
                    )

                for page in client.paginate(
                    method=method,
                    path=path,
                    params=params,
                    json=json,
                    paginator=paginator,
                    data_selector=data_selector,
                    hooks=hooks,
                    resume_hook=resume_hook,
                    initial_paginator_state=initial_paginator_state,
                    data_selector_required=data_selector_required,
                ):
                    yield list(convert_types(page, columns_config))

            resources[resource_name] = Resource(
                paginate_resource,
                name=resource_name,
                hints=hints,
                kwargs={
                    "method": endpoint_config.get("method", "get"),
                    "path": endpoint_config.get("path"),
                    "params": request_params,
                    "json": request_json,
                    "paginator": paginator,
                    "data_selector": endpoint_config.get("data_selector"),
                    "hooks": hooks,
                    "columns_config": columns_config,
                },
            )

        else:
            predecessor = resources[resolved_params[0].resolve_config["resource"]]

            base_params = exclude_keys(request_params, {rp.param_name for rp in resolved_params})

            paginate_fn = _make_paginate_dependent_resource(
                client=client,
                resolved_param=resolved_params,
                include_from_parent=include_from_parent,
                default_columns_config=columns_config,
                incremental_object=incremental_object,
                incremental_param=incremental_param,
                incremental_cursor_transform=incremental_cursor_transform,
                db_incremental_field_last_value=db_incremental_field_last_value,
                resume_hook=dependent_resume_hook,
                initial_state=dependent_initial_state,
                data_selector_required=bool(endpoint_config.get("data_selector_required")),
            )

            resources[resource_name] = Resource(
                paginate_fn,
                name=resource_name,
                hints=hints,
                kwargs={
                    # ``items`` is injected per parent page by Resource.__iter__
                    # when ``data_from`` is set.
                    "method": endpoint_config.get("method", "get"),
                    "path": endpoint_config.get("path"),
                    "params": base_params,
                    "paginator": paginator,
                    "data_selector": endpoint_config.get("data_selector"),
                    "hooks": hooks,
                    "columns_config": columns_config,
                },
                data_from=predecessor,
            )

        # Declarative per-item transform (e.g. flatten JSON:API attributes), applied after
        # type coercion during iteration. dict -> dict; use data_selector for extraction first.
        data_map = endpoint_resource.get("data_map")
        if data_map is not None:
            resources[resource_name].add_map(data_map)

    return resources


def _set_incremental_params(
    params: dict[str, Any],
    incremental_object: Incremental,
    incremental_param: Optional[IncrementalParam],
    transform: Optional[Callable[..., Any]],
    db_incremental_field_last_value: Optional[Any] = None,
) -> dict[str, Any]:
    def identity_func(x: Any) -> Any:
        return x

    if transform is None:
        transform = identity_func

    if incremental_param is None:
        return params

    last_value = (
        db_incremental_field_last_value
        if db_incremental_field_last_value is not None
        else incremental_object.last_value
    )

    params[incremental_param.start] = transform(last_value)
    if incremental_param.end:
        params[incremental_param.end] = transform(incremental_object.end_value)
    return params
