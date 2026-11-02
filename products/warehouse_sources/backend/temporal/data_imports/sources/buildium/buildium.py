from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    BASE_URL,
    CREDENTIAL_PROBE_PATHS,
    CUSTOM_FIELD_ENTITY_TYPES,
    ENDPOINTS,
    EXCLUDED_COLUMNS,
    GL_ACCOUNT_BATCH_SIZE,
    GL_ACCOUNTS_PATH,
    GL_TRANSACTIONS_END_DATE,
    GL_TRANSACTIONS_START_DATE,
    INCREMENTAL_FIELDS,
    LEASE_TRANSACTIONS_PARENT,
    ORDER_BY,
    PAGE_SIZE,
    PRIMARY_KEYS,
    UNPAGINATED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import (
    Resource,
    ResumeHook,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)


@frozen
class BuildiumResumeConfig:
    offset: int
    updated_from: str | None = None
    gl_account_batch: int = 0


def validate_credentials(config: BuildiumSourceConfig, endpoint: str, api_version: str) -> None:
    path = CREDENTIAL_PROBE_PATHS.get(endpoint) or schema_for_resource(ENDPOINTS, endpoint)
    with make_tracked_session(redact_values=(config.client_secret,)) as session:
        response = session.get(
            f"{BASE_URL}/{api_version}/{path}",
            headers={"x-buildium-client-id": config.client_id},
            auth=APIKeyAuth(config.client_secret, name="x-buildium-client-secret"),
            params={"limit": 1},
            timeout=(10, 30),
        )
        response.raise_for_status()


def _client_config(config: BuildiumSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{BASE_URL}/{api_version}/",
        "request_timeout": (10, 30),
        "headers": {"x-buildium-client-id": config.client_id},
        "auth": {"type": "api_key", "name": "x-buildium-client-secret", "api_key": config.client_secret},
        "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None, "total_header": "X-Total-Count"},
    }


def _format_watermark(value: datetime | str) -> str:
    watermark = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if watermark.tzinfo is None:
        watermark = watermark.replace(tzinfo=UTC)
    return watermark.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _list_resource(
    client: ClientConfig,
    endpoint: str,
    path: str,
    params: dict[str, Any],
    team_id: int,
    job_id: str,
    resume_hook: ResumeHook | None = None,
    initial_offset: int | None = None,
) -> Resource:
    endpoint_config: Endpoint = {"path": path, "data_selector": "$", "params": params}
    if endpoint in UNPAGINATED_ENDPOINTS:
        endpoint_config["paginator"] = "single_page"
    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": endpoint_config,
        "columns": {"LastUpdatedDateTime": {"data_type": "timestamp"}} if endpoint in INCREMENTAL_FIELDS else {},
    }
    rest_config: RESTAPIConfig = {"client": client, "resources": [resource_config]}
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state={"offset": initial_offset} if initial_offset is not None else None,
    )


def _drop_columns(columns: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def drop(row: dict[str, Any]) -> dict[str, Any]:
        for column in columns:
            row.pop(column, None)
        return row

    return drop


def _lease_transactions_resource(client: ClientConfig, team_id: int, job_id: str) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": LEASE_TRANSACTIONS_PARENT,
                "endpoint": {
                    "path": ENDPOINTS[LEASE_TRANSACTIONS_PARENT],
                    "data_selector": "$",
                    "params": {"orderby": "Id asc"},
                },
            },
            {
                "name": "lease_transactions",
                "include_from_parent": ["Id"],
                "endpoint": {
                    "path": ENDPOINTS["lease_transactions"],
                    "data_selector": "$",
                    "params": {
                        "leaseId": {"type": "resolve", "resource": LEASE_TRANSACTIONS_PARENT, "field": "Id"},
                        "orderby": "Id asc",
                    },
                    # A lease deleted after the lease listing has no transactions left to read.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
            },
        ],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    return next(resource for resource in resources if resource.name == "lease_transactions")


def _custom_field_definitions_resource(client: ClientConfig, entity_type: str, team_id: int, job_id: str) -> Resource:
    path = ENDPOINTS["custom_field_definitions"].replace("{entityType}", entity_type)
    return _list_resource(client, "custom_field_definitions", path, {}, team_id, job_id)


def _iter_custom_field_definitions(client: ClientConfig, team_id: int, job_id: str) -> Iterator[list[dict[str, Any]]]:
    for entity_type in CUSTOM_FIELD_ENTITY_TYPES:
        yield from _custom_field_definitions_resource(client, entity_type, team_id, job_id)


def _gl_account_ids(client: ClientConfig, team_id: int, job_id: str) -> list[int]:
    accounts = _list_resource(
        client, "general_ledger_accounts", GL_ACCOUNTS_PATH, {"orderby": "Id asc"}, team_id, job_id
    )
    ids: set[int] = set()
    for page in accounts:
        for account in page:
            for item in [account, *(account.get("SubAccounts") or [])]:
                if item.get("Id") is not None:
                    ids.add(item["Id"])
    return sorted(ids)


def _owned_by_batch(batch_index: int, batch_of_account: dict[int, int]) -> Callable[[dict[str, Any]], bool]:
    # A transaction with lines in several account batches comes back once per batch. Only the batch
    # of its lowest known account keeps it, so each transaction lands once without a seen-id set.
    def keep(row: dict[str, Any]) -> bool:
        lines = (row.get("Journal") or {}).get("Lines") or []
        batches = [
            batch_of_account[account_id]
            for line in lines
            if (account_id := (line.get("GLAccount") or {}).get("Id")) in batch_of_account
        ]
        return not batches or min(batches) == batch_index

    return keep


def _iter_gl_transactions(
    client: ClientConfig,
    team_id: int,
    job_id: str,
    build_batch: Callable[[list[int], int, bool, int | None], Resource],
    start_batch: int,
    start_offset: int | None,
) -> Iterator[list[dict[str, Any]]]:
    account_ids = _gl_account_ids(client, team_id, job_id)
    batches = [account_ids[i : i + GL_ACCOUNT_BATCH_SIZE] for i in range(0, len(account_ids), GL_ACCOUNT_BATCH_SIZE)]
    batch_of_account = {account_id: index for index, batch in enumerate(batches) for account_id in batch}
    for index in range(start_batch, len(batches)):
        resource = build_batch(
            batches[index], index, index + 1 < len(batches), start_offset if index == start_batch else None
        )
        yield from resource.add_filter(_owned_by_batch(index, batch_of_account))


def buildium_source(
    config: BuildiumSourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuildiumResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: datetime | str | None,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    client = _client_config(config, api_version)
    incremental = should_use_incremental_field and endpoint in INCREMENTAL_FIELDS
    updated_from = None
    if incremental and db_incremental_field_last_value is not None:
        updated_from = _format_watermark(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        # Keep the original filter because changing it would shift the saved offset.
        updated_from = resume.updated_from

    # Keep offset pagination stable when an object is updated during extraction. Ordering by the
    # mutable update timestamp can move an already-read object to a later page and skip another one.
    params: dict[str, Any] = {} if endpoint in UNPAGINATED_ENDPOINTS else {"orderby": ORDER_BY.get(endpoint, "Id asc")}
    if updated_from is not None:
        params["lastupdatedfrom"] = updated_from

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                BuildiumResumeConfig(offset=int(state["offset"]), updated_from=updated_from)
            )

    resource: Resource
    if endpoint == "custom_field_definitions":
        template = _custom_field_definitions_resource(client, CUSTOM_FIELD_ENTITY_TYPES[0], team_id, job_id)
        resource = Resource(
            _iter_custom_field_definitions, name=endpoint, hints=template._hints, args=(client, team_id, job_id)
        )
    elif endpoint == "lease_transactions":
        # Fan-out resources cannot resume, so this table restarts from the first lease after a hand-off.
        resource = _lease_transactions_resource(client, team_id, job_id)
    elif endpoint == "general_ledger_transactions":
        params.update({"startdate": GL_TRANSACTIONS_START_DATE, "enddate": GL_TRANSACTIONS_END_DATE})

        def build_batch(account_ids: list[int], index: int, has_next_batch: bool, offset: int | None) -> Resource:
            def save_batch_checkpoint(state: dict[str, Any] | None) -> None:
                if state is not None:
                    resumable_source_manager.save_state(
                        BuildiumResumeConfig(
                            offset=int(state["offset"]), updated_from=updated_from, gl_account_batch=index
                        )
                    )
                elif has_next_batch:
                    resumable_source_manager.save_state(
                        BuildiumResumeConfig(offset=0, updated_from=updated_from, gl_account_batch=index + 1)
                    )

            return _list_resource(
                client,
                endpoint,
                path,
                {**params, "glaccountids": account_ids},
                team_id,
                job_id,
                resume_hook=save_batch_checkpoint,
                initial_offset=offset,
            )

        template = build_batch([], 0, False, None)
        # Wrapping the batches in a `Resource` keeps the framework's safe points and page checkpoints.
        resource = Resource(
            _iter_gl_transactions,
            name=endpoint,
            hints=template._hints,
            args=(
                client,
                team_id,
                job_id,
                build_batch,
                resume.gl_account_batch if resume else 0,
                resume.offset if resume else None,
            ),
        )
    else:
        resource = _list_resource(
            client,
            endpoint,
            path,
            params,
            team_id,
            job_id,
            resume_hook=save_checkpoint,
            initial_offset=resume.offset if resume else None,
        )
        if endpoint in EXCLUDED_COLUMNS:
            resource.add_map(_drop_columns(EXCLUDED_COLUMNS[endpoint]))

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS.get(endpoint, ["Id"]),
        column_hints=resource.column_hints,
        # Incremental rows are ID-ordered rather than timestamp-ordered, so only advance the
        # timestamp watermark after a complete extraction.
        sort_mode="desc",
    )
