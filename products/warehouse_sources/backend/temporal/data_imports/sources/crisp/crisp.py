from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.settings import (
    CONVERSATION_PARAMS,
    ENDPOINTS,
    CrispEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crisp import CrispSourceConfig

# A window that one list page holds cannot lose a conversation to a page shift during the run.
WINDOW_PAGE_SIZE = int(CONVERSATION_PARAMS["per_page"])
# An incremental message sync stops after this many conversations with messages, so that the run
# completes and keeps its watermark. A website token allows 10,000 requests a day, and a backfill
# that needs more would otherwise start again from zero every run.
CONVERSATIONS_PER_RUN = 3000
EARLIEST_UPDATE = datetime(2000, 1, 1, tzinfo=UTC)
ONE_MILLISECOND = timedelta(milliseconds=1)


@frozen
class CrispResumeConfig:
    paginator_state: dict[str, Any]
    started_at: str | None = None
    conversations_loaded: int = 0


class CrispPathPaginator(PageNumberPaginator):
    def __init__(self, page_size: int | None = None) -> None:
        super().__init__(base_page=1)
        self.page_size = page_size

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if self.page_size is not None and data is not None and len(data) < self.page_size:
            self._has_next_page = False
            return
        super().update_state(response, data)

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_request(self, request: Request) -> None:
        if request.url is None:
            raise ValueError("Crisp pagination requires a request URL")
        request.url = f"{request.url.rsplit('/', 1)[0]}/{self.page}"


class CrispMessagesPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self.timestamp_before: int | None = None

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not data:
            self._has_next_page = False
            return
        oldest = min(int(row["timestamp"]) for row in data)
        if self.timestamp_before is not None and oldest >= self.timestamp_before:
            raise ValueError("Crisp message pagination did not advance")
        self.timestamp_before = oldest

    def update_request(self, request: Request) -> None:
        if self.timestamp_before is not None:
            if request.params is None:
                request.params = {}
            request.params["timestamp_before"] = self.timestamp_before

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"timestamp_before": self.timestamp_before} if self.has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self.timestamp_before = int(state["timestamp_before"])


def client_config(config: CrispSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://api.crisp.chat/{api_version}/",
        "auth": {"type": "http_basic", "username": config.token_identifier, "password": config.token_key},
        "headers": {"X-Crisp-Tier": "website", "Accept": "application/json"},
        # operators/list returns pending-invitation credentials that the sample scrubbers do not redact.
        "capture": False,
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
        # Crisp sends no Retry-After with a 429, and the default five tries end before its
        # rate limit clears. Nine tries keep one request waiting inside the retry budget.
        "max_retries": 9,
        "retry_budget_seconds": 240,
        "retry_after_max_seconds": 120,
    }


def endpoint_config(endpoint: CrispEndpoint, website_id: str) -> Endpoint:
    response_actions: list[ResponseAction] = [
        {
            "status_code": 200,
            "json_field": "error",
            "json_values": [True],
            "action": "raise",
            "message": "Crisp returned an API error",
        }
    ]
    if endpoint.name in ("conversations", "people"):
        response_actions.append({"status_code": 416, "action": "ignore"})
    paginator: BasePaginator
    if endpoint.pagination == "messages":
        paginator = CrispMessagesPaginator()
    elif endpoint.pagination == "single":
        paginator = SinglePagePaginator()
    else:
        # Other lists have no documented page size, so a short page cannot prove that they ended.
        per_page = endpoint.params.get("per_page")
        paginator = CrispPathPaginator(page_size=int(per_page) if per_page is not None else None)
    return {
        "path": endpoint.path.replace("{website_id}", quote(website_id, safe="")),
        "params": dict(endpoint.params),
        "paginator": paginator,
        "data_selector": "data",
        "data_selector_required": True,
        "response_actions": response_actions,
    }


def format_updated_since(value: datetime) -> str:
    utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def list_params(endpoint: CrispEndpoint, inputs: SourceInputs) -> dict[str, Any]:
    if not (inputs.should_use_incremental_field and endpoint.updated_since_param):
        return dict(endpoint.params)
    params: dict[str, Any] = dict(endpoint.incremental_params)
    if inputs.db_incremental_field_last_value is not None:
        params[endpoint.updated_since_param] = format_updated_since(inputs.db_incremental_field_last_value)
    return params


def resource_config(endpoint: CrispEndpoint, website_id: str, inputs: SourceInputs) -> EndpointResource:
    config = endpoint_config(endpoint, website_id)
    config["params"] = list_params(endpoint, inputs)
    return {
        "name": endpoint.name,
        "table_name": endpoint.name,
        "write_disposition": "replace",
        "endpoint": config,
    }


def parent_path_map(
    field: str, included: list[str], updated_before: datetime | None = None
) -> Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]:
    cutoff_ms = updated_before.timestamp() * 1000 if updated_before is not None else None

    def encode_path(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        # A resumed attempt skips the conversations that an earlier attempt finished, even when they
        # changed since then. Messages of a conversation that changed after the run started could move
        # the watermark past that change, so the next run reads the conversation instead.
        updated_at = row.get("updated_at")
        if cutoff_ms is not None and isinstance(updated_at, int | float) and updated_at > cutoff_ms:
            return []
        # The fan-out fails on a parent row that lacks an included field.
        return {**dict.fromkeys(included), **row, "_path_id": quote(str(row[field]), safe="")}

    return encode_path


def conversation_windows(
    list_window: Callable[[datetime, datetime, bool], list[dict[str, Any]]],
    start: datetime,
    end: datetime,
    done: Callable[[], bool],
    safe_point: Callable[[], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield the conversations updated in [start, end], oldest window first.

    A full page can hide more conversations, so its window splits in two until one page holds it.
    The halves share their middle millisecond, because Crisp does not document whether its date
    filter includes the bounds. The fan-out skips a conversation that it already finished.
    """
    pending = [(start, end)]
    while pending and not done():
        low, high = pending.pop()
        rows = list_window(low, high, False)
        if len(rows) >= WINDOW_PAGE_SIZE:
            # The left half is one millisecond wider than half the window, so only a window wider
            # than two milliseconds splits into strictly smaller halves.
            if high - low > 2 * ONE_MILLISECOND:
                middle = low + (high - low) / 2
                pending.append((middle, high))
                pending.append((low, middle + ONE_MILLISECOND))
                safe_point()
                continue
            # More conversations than a page share the same few milliseconds, so only page numbers reach them.
            rows = list_window(low, high, True)
        yield rows


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    for name in ("created_at", "updated_at", "conversation_updated_at", "timestamp", "dispatched_at", "waiting_since"):
        value = row.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[name] = datetime.fromtimestamp(value / 1000, tz=UTC)
    return row


def normalize_operator(row: dict[str, Any]) -> dict[str, Any]:
    # Pending invitations include credentials, so only joined operators enter the warehouse.
    return {"type": row["type"], **row["details"]}


def windowed_messages_resource(
    config: CrispSourceConfig,
    inputs: SourceInputs,
    api_version: str,
    settings: CrispEndpoint,
    started_at: datetime,
    manager: ResumableSourceManager[CrispResumeConfig],
    save_state: Callable[[dict[str, Any] | None], None],
    initial_state: dict[str, Any] | None,
    loaded_before: int,
    with_messages: set[str],
) -> Resource:
    fanout = settings.fanout
    assert fanout is not None
    parent = ENDPOINTS[fanout.parent_name]
    last_value = inputs.db_incremental_field_last_value
    start = (
        (last_value.replace(tzinfo=UTC) if last_value.tzinfo is None else last_value) - ONE_MILLISECOND
        if isinstance(last_value, datetime)
        else EARLIEST_UPDATE
    )

    def list_window(low: datetime, high: datetime, all_pages: bool) -> list[dict[str, Any]]:
        endpoint = endpoint_config(parent, config.website_id)
        endpoint["params"] = {
            **CONVERSATION_PARAMS,
            "order_date_created": "1",
            "filter_date_start": format_updated_since(low),
            "filter_date_end": format_updated_since(high),
        }
        if not all_pages:
            endpoint["paginator"] = SinglePagePaginator()
        window: RESTAPIConfig = {
            "client": client_config(config, api_version),
            "resources": [{"name": parent.name, "endpoint": endpoint}],
        }
        rows: list[dict[str, Any]] = []
        for page in rest_api_resource(window, inputs.team_id, inputs.job_id, None):
            rows.extend(page if isinstance(page, list) else [page])
        return rows

    def count_conversation(row: dict[str, Any]) -> dict[str, Any]:
        with_messages.add(str(row.get("session_id")))
        return row

    child_endpoint = endpoint_config(settings, config.website_id)
    child_endpoint["params"] = {
        fanout.resolve_param: {"type": "resolve", "resource": parent.name, "field": fanout.resolve_field}
    }
    child_endpoint["response_actions"] = [
        *fanout.child_response_actions,
        *(child_endpoint.get("response_actions") or []),
    ]

    finished_before = set((initial_state or {}).get("completed") or [])
    child_path = child_endpoint["path"]
    assert child_path is not None
    cutoff_ms = started_at.timestamp() * 1000

    def unread(row: dict[str, Any]) -> bool:
        updated_at = row.get("updated_at")
        if isinstance(updated_at, int | float) and updated_at > cutoff_ms:
            # parent_path_map defers this conversation, so the fan-out reads nothing for it.
            return False
        return child_path.format(session_id=quote(str(row.get("session_id")), safe="")) not in finished_before

    # An earlier attempt can stop inside a window. If this attempt stopped before it finished that
    # window, the watermark of the run would skip the window's unread conversations. So a resumed
    # attempt may stop only after it reaches a window with a conversation that it has to read.
    caught_up = not finished_before

    def done() -> bool:
        return caught_up and loaded_before + len(with_messages) >= CONVERSATIONS_PER_RUN

    def windows() -> Iterator[list[dict[str, Any]]]:
        nonlocal caught_up
        for rows in conversation_windows(list_window, start, started_at, done, manager.safe_point):
            caught_up = caught_up or any(unread(row) for row in rows)
            yield rows

    rest_config: RESTAPIConfig = {
        "client": client_config(config, api_version),
        "resources": [
            {
                "name": parent.name,
                "table_name": parent.name,
                "write_disposition": "replace",
                "endpoint": endpoint_config(parent, config.website_id),
                "data_iterator": windows,
                "data_map": parent_path_map(fanout.resolve_param, fanout.include_from_parent, started_at),
            },
            {
                "name": settings.name,
                "table_name": settings.name,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"},
                "include_from_parent": fanout.include_from_parent,
                "endpoint": child_endpoint,
                "table_format": "delta",
            },
        ],
    }
    resources = rest_api_resources(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_state,
        initial_paginator_state=initial_state,
    )
    child = next(resource for resource in resources if resource.name == settings.name)
    child.add_map(rename_parent_fields(parent.name, fanout.parent_field_renames))
    return child.add_map(count_conversation)


def credential_resource(config: CrispSourceConfig, team_id: int, api_version: str, schema_name: str | None) -> Resource:
    if schema_name is None:
        endpoint: Endpoint = {
            "path": f"website/{quote(config.website_id, safe='')}",
            "paginator": "single_page",
            "data_selector": "data",
            "data_selector_required": True,
        }
    else:
        settings = schema_for_resource(ENDPOINTS, schema_name)
        if settings.fanout is not None:
            settings = ENDPOINTS[settings.fanout.parent_name]
        endpoint = endpoint_config(settings, config.website_id)
        endpoint["paginator"] = "single_page"
    client = client_config(config, api_version)
    # The probe runs inside a web request, so it keeps the default retries to answer before the gateway timeout.
    client.pop("max_retries")
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [{"name": "credential_probe", "endpoint": endpoint}],
    }
    return rest_api_resource(rest_config, team_id, "crisp_credential_probe", None)


def crisp_source(
    config: CrispSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[CrispResumeConfig],
    api_version: str,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state()
    incremental = inputs.should_use_incremental_field and bool(settings.incremental_fields)
    defer_changed = incremental and settings.fanout is not None
    started_at = (
        datetime.fromisoformat(resume.started_at)
        if resume is not None and resume.started_at is not None
        else datetime.now(UTC)
    )

    loaded_before = resume.conversations_loaded if resume is not None else 0
    with_messages: set[str] = set()

    def save_state(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                CrispResumeConfig(
                    paginator_state=state,
                    started_at=started_at.isoformat() if defer_changed else None,
                    conversations_loaded=loaded_before + len(with_messages) if defer_changed else 0,
                )
            )

    initial_state = resume.paginator_state if resume is not None else None
    if defer_changed:
        resource = windowed_messages_resource(
            config,
            inputs,
            api_version,
            settings,
            started_at,
            manager,
            save_state,
            initial_state,
            loaded_before,
            with_messages,
        )
    elif settings.fanout is not None:
        parent = ENDPOINTS[settings.fanout.parent_name]
        parent_endpoint = endpoint_config(parent, config.website_id)
        parent_endpoint.pop("params", None)
        child_endpoint = endpoint_config(settings, config.website_id)
        child_endpoint.pop("params", None)
        child_endpoint["response_actions"] = [
            *settings.fanout.child_response_actions,
            *(child_endpoint.get("response_actions") or []),
        ]
        dependent = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=settings.name,
            fanout=settings.fanout,
            client_config=client_config(config, api_version),
            path_format_values={"website_id": quote(config.website_id, safe="")},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=parent_endpoint,
            child_endpoint_extra=child_endpoint,
            parent_data_map=parent_path_map(settings.fanout.resolve_param, settings.fanout.include_from_parent),
            page_size_param=None,
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
        assert isinstance(dependent, Resource)
        resource = dependent
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config(config, api_version),
            "resources": [resource_config(settings, config.website_id, inputs)],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
    if settings.name == "operators":
        resource.add_filter(lambda row: row.get("type") in ("operator", "sandbox"))
        resource.add_map(normalize_operator)
    resource.add_map(normalize_row)
    return SourceResponse(
        name=settings.name,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        # "desc" moves the watermark only when the run completes. Crisp does not document the
        # direction of its date order, so a watermark from a partial run could skip rows.
        sort_mode="desc" if settings.pagination == "messages" or inputs.should_use_incremental_field else None,
        on_complete=manager.clear_state,
    )
