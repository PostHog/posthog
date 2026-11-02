"""Generic API Source"""

import graphlib  # type: ignore[import,unused-ignore]
from collections.abc import Callable, Iterator
from typing import Any, Optional, cast

import structlog
from dateutil import parser

from products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_telemetry import (
    FanoutParentSource,
    log_fanout_parent_rows_consumed,
)

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
from .paginators import BasePaginator, set_json_param
from .resource import PageCheckpoints, Resource
from .rest_client import DEFAULT_RETRY_ATTEMPTS, DEFAULT_RETRY_BACKOFF_MAX_SECONDS, RESTClient, RESTClientRetryableError
from .typing import ClientConfig, Endpoint, EndpointResource, HTTPMethodBasic, ResolvedParam, RESTAPIConfig
from .utils import exclude_keys  # noqa: F401

logger = structlog.get_logger(__name__)


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

    ``resume_hook`` receives the state that fetches the page after the current one. When
    ``SourceResponse.items`` returns the resource itself, the hook runs before the page reaches the
    pipeline, so the pipeline commits a page and its state together. When a source wraps the
    resource, the hook runs when the wrapper asks for the next page.
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
    on_parent_error: Optional[Callable[[str, Exception], None]] = None,
) -> list[Resource]:
    """Creates a list of resources from a REST API configuration.

    Prefer ``rest_api_resource`` (singular) for the common single-resource
    case. This function is needed for multi-resource configs like date-chunked
    report endpoints or parent/child fanout.

    ``on_parent_error`` opts a parent/child fanout into per-parent fault tolerance: when a parent's
    child pagination raises ``RESTClientRetryableError`` (a transient failure the client's own
    retries could not clear), the fanout hands the parent path and error to this callback and moves
    on to the next parent instead of failing the whole resource. Without it, that error propagates.
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
        on_parent_error=on_parent_error,
    )

    return list(resources.values())


class ParentPosition:
    """Where the parent listing of a resumable fan-out stands.

    The parent paginator reports the state of its next page before it hands a page on. This keeps the
    state that fetches the page being fanned out and the page before it. A resume starts one page
    back, so a parent that a deletion moved into the earlier page is read again rather than skipped.
    """

    def __init__(self, start: Optional[dict[str, Any]]) -> None:
        self.start = start
        self._next: Optional[dict[str, Any]] = start
        self._current: Optional[dict[str, Any]] = start
        self._previous: Optional[dict[str, Any]] = start
        self.tracked = True

    def on_page_state(self, next_state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        self._previous, self._current, self._next = self._current, self._next, next_state
        if has_next_page and next_state is None:
            # The paginator cannot save its place, so the fan-out keeps every finished parent instead.
            self.tracked = False

    def resume_state(self) -> Optional[dict[str, Any]]:
        return self._previous


class _FinishedParents:
    """Child paths of the parents a fan-out has finished.

    Without a tracked parent position, a resume reads the parent listing from the start, so every
    finished path is kept. With one, a resume starts at the page before the current one, so only the
    paths of those two pages are kept, plus the saved paths this run has not reached yet. Saving
    every path after each parent costs more with each parent, so a large fan-out would slow down as
    it runs.
    """

    def __init__(self, seed: list[str], position: Optional[ParentPosition]) -> None:
        self._position = position
        self._seed = set(seed)
        # A state saved without a parent position resumes from the first parent page. Its paths stay
        # saved until the listing reaches them, because a parent added at the front makes this run
        # save a state before it reaches the parents it skips.
        self._unreached_seed = set(seed)
        self._everything = set(seed)
        self._window: list[set[str]] = []

    @property
    def windowed(self) -> bool:
        return self._position is not None and self._position.tracked

    def start_parent_page(self) -> None:
        self._window.append(set())
        del self._window[:-2]

    def __contains__(self, path: str) -> bool:
        if self.windowed:
            return path in self._seed or any(path in page for page in self._window)
        return path in self._everything

    def add(self, path: str) -> None:
        self._unreached_seed.discard(path)
        if self.windowed:
            self._window[-1].add(path)
        else:
            self._everything.add(path)

    def paths(self) -> list[str]:
        if self.windowed:
            return sorted(self._unreached_seed.union(*self._window))
        return sorted(self._everything)


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
    data_selector_empty_ok: bool = False,
    data_selector_malformed_retryable: bool = False,
    on_parent_error: Optional[Callable[[str, Exception], None]] = None,
    parent_source: FanoutParentSource = "api",
    parent_position: Optional[ParentPosition] = None,
) -> Callable[..., Iterator[list[Any]]]:
    """Build the generator for a dependent (child) resource.

    When ``resume_hook`` is set the fan-out is resumable: each parent's child pagination is
    checkpointed under that parent's resolved child path, so a restart skips parents already fully
    synced and resumes the one that was in progress. Without ``parent_position`` the parent list is
    re-fetched from the start each run and already-completed parents are skipped by path. With it,
    the state also holds ``parent``, the paginator state a resume starts the parent listing from.
    Resume state shape:
    ``{"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}``,
    plus ``"parent": {...} | None`` when the parent position is tracked.
    """
    # Closure state persists across parent-page invocations within a single run.
    parent_rows_consumed = 0
    seed: dict[str, Any] = dict(initial_state) if initial_state else {}
    completed = _FinishedParents(seed.get("completed") or [], parent_position)
    current_path: Optional[str] = seed.get("current")
    current_child_state: Optional[dict[str, Any]] = seed.get("child_state")
    resumed = bool(seed.get("completed") or current_path)

    def checkpoint(current: Optional[str], child_state: Optional[dict[str, Any]]) -> None:
        state: dict[str, Any] = {"completed": completed.paths(), "current": current, "child_state": child_state}
        if parent_position is not None and completed.windowed:
            state["parent"] = parent_position.resume_state()
        # resume_hook is non-None here (only called from the resumable path).
        resume_hook(state)  # type: ignore[misc]

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
        nonlocal current_path, current_child_state, parent_rows_consumed
        effective_columns_config = columns_config if columns_config is not None else default_columns_config

        page_rows = 0
        completed.start_parent_page()

        if incremental_object:
            params, _ = _set_incremental_params(
                params,
                None,
                incremental_object,
                incremental_param,
                incremental_cursor_transform,
                db_incremental_field_last_value,
            )

        for item in items:
            formatted_path, parent_record = process_parent_data_item(path, item, resolved_param, include_from_parent)

            if resume_hook is not None and formatted_path in completed:
                # Kept on this page, so it is still skipped after the resume one page back.
                completed.add(formatted_path)
                continue

            page_rows += 1
            parent_rows_consumed += 1

            # Resume this parent's child cursor only if it's the one we were mid-way through.
            child_initial = (
                current_child_state if (resume_hook is not None and current_path == formatted_path) else None
            )

            def child_page_state_hook(
                paginator_state: Optional[dict[str, Any]], has_next_page: bool, _path: str = formatted_path
            ) -> None:
                nonlocal current_path, current_child_state
                if not has_next_page:
                    # The state of a parent's last page is staged before that page is handed on. An
                    # in-progress checkpoint would make a resumed run read the whole parent again,
                    # so the parent is recorded as complete here.
                    completed.add(_path)
                    current_path = None
                    current_child_state = None
                    checkpoint(None, None)
                    return
                current_path = _path
                current_child_state = paginator_state
                checkpoint(_path, paginator_state)

            try:
                for child_page in client.paginate(
                    method=method,
                    path=formatted_path,
                    params=dict(params),
                    paginator=paginator,
                    data_selector=data_selector,
                    hooks=hooks,
                    page_state_hook=child_page_state_hook if resume_hook is not None else None,
                    initial_paginator_state=child_initial,
                    data_selector_required=data_selector_required,
                    data_selector_empty_ok=data_selector_empty_ok,
                    data_selector_malformed_retryable=data_selector_malformed_retryable,
                ):
                    if parent_record:
                        for child_record in child_page:
                            child_record.update(parent_record)

                    yield list(convert_types(child_page, effective_columns_config))
            except RESTClientRetryableError as exc:
                # One parent whose child resource keeps failing after the client exhausts its own
                # retries must not sink the whole fan-out. When the caller opts in, skip that parent,
                # hand the failure to the handler, and move on so every other parent's rows land.
                if on_parent_error is None:
                    raise
                on_parent_error(formatted_path, exc)
                if resume_hook is not None:
                    # Clear the in-progress pointer so a later retry re-attempts this parent from the
                    # start; leave it off `completed` so it is never permanently skipped.
                    current_path = None
                    current_child_state = None
                    checkpoint(None, None)
                continue

            # A parent whose child endpoint answered nothing never reached the hook.
            if resume_hook is not None and formatted_path not in completed:
                completed.add(formatted_path)
                current_path = None
                current_child_state = None
                checkpoint(None, None)

        # Counted after the page so parents a resume skips don't inflate it. A running total,
        # since there's no end-of-parent signal: the last line of a run carries the fan-out's
        # size, for either parent kind, which the API path never surfaced anywhere.
        log_fanout_parent_rows_consumed(
            logger,
            parent_source=parent_source,
            rows_total=parent_rows_consumed,
            resumed=resumed,
            page_rows=page_rows,
        )

    return paginate_dependent_resource


def _retry_limit_overrides(client_config: ClientConfig) -> dict[str, float]:
    # Passed only when a source sets them, so a client built with neither keeps the settings.
    return {
        key: client_config[key]  # type: ignore[literal-required]
        for key in ("retry_budget_seconds", "retry_after_max_seconds")
        if key in client_config
    }


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
    on_parent_error: Optional[Callable[[str, Exception], None]] = None,
) -> dict[str, Resource]:
    resources: dict[str, Resource] = {}

    # Resume is routed to the dependent (child) resource in a fan-out; the parent list is re-fetched
    # each run unless the child sets ``resume_parent_pagination`` (see
    # _make_paginate_dependent_resource). So when any resource is dependent, the
    # non-dependent resources in the same config don't consume the resume hook. With MULTIPLE
    # dependent resources (a chained/multi-level fan-out), no resource gets resume — one shared
    # hook consumed at several levels would corrupt the saved state; retries re-fetch and the
    # merge dedupes.
    dependent_count = sum(1 for rp in resolved_param_map.values() if rp is not None)
    has_dependent_resource = dependent_count > 0
    dependent_resume_hook = resume_hook if dependent_count == 1 else None
    dependent_initial_state = initial_paginator_state if dependent_count == 1 else None

    parent_position: Optional[ParentPosition] = None
    position_parent_name: Optional[str] = None
    if dependent_resume_hook is not None:
        child_name, child_params = next((name, rp) for name, rp in resolved_param_map.items() if rp is not None)
        parent_name = child_params[0].resolve_config["resource"]
        # A parent skipped through `on_parent_error` is retried only when a resume reads it again, and a
        # resume that starts at the saved page never reaches the earlier pages.
        if (
            endpoint_resource_map[child_name].get("resume_parent_pagination")
            and endpoint_resource_map[parent_name].get("data_iterator") is None
            and on_parent_error is None
        ):
            parent_position = ParentPosition((dependent_initial_state or {}).get("parent"))
            position_parent_name = parent_name

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
        # A dependent resource sends no request body, so a JSON-body cursor would be silently dropped.
        if resolved_params and incremental_param is not None and incremental_param.location == "json":
            raise ValueError(
                f"Resource {resource_name} depends on another resource, so its incremental cursor can't go in the JSON body"
            )

        client = RESTClient(
            base_url=client_config.get("base_url"),
            headers=client_config.get("headers"),
            auth=create_auth(client_config.get("auth")),
            paginator=create_paginator(client_config.get("paginator")),
            session=client_config.get("session"),
            max_retry_attempts=client_config.get("max_retries", DEFAULT_RETRY_ATTEMPTS),
            retry_backoff_max_seconds=client_config.get("retry_backoff_max_seconds", DEFAULT_RETRY_BACKOFF_MAX_SECONDS),
            allowed_hosts=client_config.get("allowed_hosts"),
            allow_redirects=client_config.get("allow_redirects", True),
            presigned_redirect_host_pattern=client_config.get("presigned_redirect_host_pattern"),
            request_timeout=client_config.get("request_timeout"),
            capture=client_config.get("capture", True),
            **_retry_limit_overrides(client_config),
        )

        hooks = create_response_hooks(endpoint_config.get("response_actions"), resource_name=resource_name)

        # The resource applies resume states itself, so that a page and its state reach the pipeline
        # together (see `Resource._iter_generator`).
        if resolved_params is not None:
            own_resume_hook = dependent_resume_hook
        elif has_dependent_resource:
            own_resume_hook = None
        else:
            own_resume_hook = resume_hook
        page_checkpoints = PageCheckpoints(own_resume_hook) if own_resume_hook is not None else None

        resource_kwargs = exclude_keys(
            endpoint_resource, {"endpoint", "include_from_parent", "data_map", "data_iterator"}
        )

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

        data_iterator = endpoint_resource.get("data_iterator")
        if data_iterator is not None:
            # Iterator-backed resource: pages come from the callable (e.g. an already-synced
            # warehouse parent table) instead of HTTP pagination. Downstream dependents consume
            # it via ``data_from`` exactly like an HTTP-backed parent.
            resources[resource_name] = Resource(
                data_iterator,
                name=resource_name,
                hints=hints,
            )

        elif resolved_params is None:
            own_parent_position = parent_position if resource_name == position_parent_name else None
            own_page_state_hook: Optional[Callable[[Optional[dict[str, Any]], bool], None]]
            if own_parent_position is not None:
                own_initial_state = own_parent_position.start
                own_page_state_hook = own_parent_position.on_page_state
            else:
                own_initial_state = None if has_dependent_resource else initial_paginator_state
                own_page_state_hook = page_checkpoints.defer_page_state if page_checkpoints is not None else None

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
                page_state_hook: Optional[Callable[[Optional[dict[str, Any]], bool], None]] = own_page_state_hook,
                initial_paginator_state: Optional[dict[str, Any]] = own_initial_state,
                data_selector_required: bool = bool(endpoint_config.get("data_selector_required")),
                data_selector_empty_ok: bool = bool(endpoint_config.get("data_selector_empty_ok")),
                data_selector_malformed_retryable: bool = bool(
                    endpoint_config.get("data_selector_malformed_retryable")
                ),
            ) -> Iterator[list[Any]]:
                if incremental_object:
                    params, json = _set_incremental_params(
                        params,
                        json,
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
                    page_state_hook=page_state_hook,
                    initial_paginator_state=initial_paginator_state,
                    data_selector_required=data_selector_required,
                    data_selector_empty_ok=data_selector_empty_ok,
                    data_selector_malformed_retryable=data_selector_malformed_retryable,
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
                page_checkpoints=page_checkpoints,
            )

        else:
            parent_name = resolved_params[0].resolve_config["resource"]
            predecessor = resources[parent_name]

            # Set by `build_dependent_resource` only once the warehouse table resolves, so an
            # unresolvable table leaves this "api" and the telemetry names the parent the run
            # actually read.
            parent_source: FanoutParentSource = endpoint_resource_map[parent_name].get("parent_source") or "api"

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
                resume_hook=page_checkpoints.defer if page_checkpoints is not None else None,
                initial_state=dependent_initial_state,
                data_selector_required=bool(endpoint_config.get("data_selector_required")),
                data_selector_empty_ok=bool(endpoint_config.get("data_selector_empty_ok")),
                data_selector_malformed_retryable=bool(endpoint_config.get("data_selector_malformed_retryable")),
                on_parent_error=on_parent_error,
                parent_source=parent_source,
                parent_position=parent_position,
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
                page_checkpoints=page_checkpoints,
            )

        # Declarative per-item transform (e.g. flatten JSON:API attributes), applied after
        # type coercion during iteration. dict -> dict; use data_selector for extraction first.
        data_map = endpoint_resource.get("data_map")
        if data_map is not None:
            resources[resource_name].add_map(data_map)

    return resources


def _set_incremental_params(
    params: dict[str, Any],
    json: Optional[dict[str, Any]],
    incremental_object: Incremental,
    incremental_param: Optional[IncrementalParam],
    transform: Optional[Callable[..., Any]],
    db_incremental_field_last_value: Optional[Any] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    def identity_func(x: Any) -> Any:
        return x

    if transform is None:
        transform = identity_func

    if incremental_param is None:
        return params, json

    last_value = (
        db_incremental_field_last_value
        if db_incremental_field_last_value is not None
        else incremental_object.last_value
    )

    values = {incremental_param.start: transform(last_value)}
    if incremental_param.end:
        values[incremental_param.end] = transform(incremental_object.end_value)

    if incremental_param.location == "json":
        if json is None:
            json = {}
        for name, value in values.items():
            set_json_param(json, name, value)
    else:
        params.update(values)
    return params, json
