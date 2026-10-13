from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from jsonpath_ng import DatumInContext, JSONPath

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import IncrementalConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.settings import (
    BILLING_USAGE_AGGREGATE_BY,
    BILLING_USAGE_DEFAULT_LOOKBACK_DAYS,
    BILLING_USAGE_ENDPOINT,
    SINGLESTORE_ENDPOINTS,
    WORKSPACE_GROUPS_ENDPOINT,
    WORKSPACES_ENDPOINT,
    SinglestoreEndpointConfig,
)

SINGLESTORE_BASE_URL = "https://api.singlestore.com/v1"


def validate_credentials(api_key: str) -> tuple[bool, Optional[str]]:
    """Probe GET /v1/organizations/current — every organization API key can read its own
    organization, so this is the cheapest call that actually exercises the token. A bad key
    returns 401; SingleStore has no documented 403-but-valid-token scope split on this endpoint.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SINGLESTORE_BASE_URL}/organizations/current",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return (
            False,
            "SingleStore rejected the API key. Generate a new organization API key in the Cloud Portal and try again.",
        )
    # A rate limit, a transient 5xx, or an unreachable API is not a credential rejection — the
    # same conditions are retried during the sync itself, and a genuine auth failure still
    # surfaces there via get_non_retryable_errors().
    return True, None


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SINGLESTORE_BASE_URL,
        # Framework auth so the key is redacted from logs and raised error messages.
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "session": make_tracked_session(redact_values=(api_key,)),
    }


def _list_resource(config: SinglestoreEndpointConfig, client: ClientConfig, team_id: int, job_id: str) -> Resource:
    """A single-request endpoint. Array bodies are used as the row list directly; the one
    `is_single_object` endpoint (`organizations/current`) is a bare object, which the framework's
    no-selector path wraps into a single-row list — so neither case needs a custom data_selector.
    """
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": config.name,
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    "paginator": SinglePagePaginator(),
                    # A single JSON object is the expected (and only) shape for that endpoint, so
                    # `data_selector_required` would incorrectly fail it — only array endpoints get
                    # the fail-loud shape check.
                    "data_selector_required": not config.is_single_object,
                },
            }
        ],
    }
    return rest_api_resource(rest_config, team_id, job_id, db_incremental_field_last_value=None)


def _iter_workspaces(client: RESTClient) -> Iterator[list[dict[str, Any]]]:
    """Fan `workspaces` out over every workspace group id — SingleStore has no top-level workspace
    listing; `GET /v1/workspaces` requires `workspaceGroupID`. Each workspace already carries its
    own `workspaceGroupID` field, so no parent field needs to be stamped onto the child rows.

    Hand-rolled rather than the declarative `"resolve"` fan-out: that mechanism only binds a
    resolved parent field into a URL *path* segment (`_bind_path_params` raises
    `NotImplementedError` otherwise), and `workspaceGroupID` here is a query parameter, not a path
    segment.
    """
    for group_page in client.paginate(
        path=SINGLESTORE_ENDPOINTS[WORKSPACE_GROUPS_ENDPOINT].path,
        paginator=SinglePagePaginator(),
        data_selector_required=True,
    ):
        for group in group_page:
            group_id = group.get("workspaceGroupID")
            if not group_id:
                continue
            yield from client.paginate(
                path=SINGLESTORE_ENDPOINTS[WORKSPACES_ENDPOINT].path,
                params={"workspaceGroupID": group_id},
                paginator=SinglePagePaginator(),
                data_selector_required=True,
            )


def _workspaces_resource(api_key: str) -> Resource:
    client = RESTClient(
        base_url=SINGLESTORE_BASE_URL,
        headers={"Accept": "application/json"},
        auth=BearerTokenAuth(api_key),
        session=make_tracked_session(redact_values=(api_key,)),
    )

    def _generator() -> Iterator[list[dict[str, Any]]]:
        yield from _iter_workspaces(client)

    return Resource(_generator, name=WORKSPACES_ENDPOINT, hints={"table_format": "delta"})


class _BillingUsageSelector(JSONPath):
    """Flatten `{"billingUsage": [{"metric", "description", "usage": [...]}]}` into one row per
    usage item, stamped with its parent `metric` and `description`. A declarative `data_selector`
    can select a nested list but can't also carry fields down from that list's parent object, so
    this mirrors the per-endpoint custom-selector pattern used elsewhere in the framework (e.g.
    bland_ai's pathways selector).
    """

    def find(self, data: Any) -> list[DatumInContext]:
        rows: list[dict[str, Any]] = []
        for group in (data or {}).get("billingUsage") or []:
            metric = group.get("metric")
            description = group.get("description")
            for item in group.get("usage") or []:
                rows.append({**item, "metric": metric, "description": description})
        return [DatumInContext(rows)]


def _format_billing_timestamp(value: Any) -> str:
    """ISO 8601 UTC, matching the format the Management API's startTime/endTime filters accept."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _billing_usage_resource(
    client: ClientConfig,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    lookback_start = datetime.now(UTC) - timedelta(days=BILLING_USAGE_DEFAULT_LOOKBACK_DAYS)
    incremental: IncrementalConfig = {
        "start_param": "startTime",
        "end_param": "endTime",
        "cursor_path": "startTime",
        "initial_value": _format_billing_timestamp(lookback_start),
        "end_value": _format_billing_timestamp(datetime.now(UTC)),
        "convert": _format_billing_timestamp,
        "row_order": "asc",
    }
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [
            {
                "name": BILLING_USAGE_ENDPOINT,
                "table_format": "delta",
                "write_disposition": (
                    {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"
                ),
                "endpoint": {
                    "path": SINGLESTORE_ENDPOINTS[BILLING_USAGE_ENDPOINT].path,
                    "params": {"aggregateBy": BILLING_USAGE_AGGREGATE_BY},
                    "incremental": incremental,
                    "data_selector": _BillingUsageSelector(),
                    "paginator": SinglePagePaginator(),
                },
            }
        ],
    }
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=(db_incremental_field_last_value if should_use_incremental_field else None),
    )


def singlestore_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SINGLESTORE_ENDPOINTS[endpoint]

    if endpoint == WORKSPACES_ENDPOINT:
        resource = _workspaces_resource(api_key)
    elif endpoint == BILLING_USAGE_ENDPOINT:
        resource = _billing_usage_resource(
            _client_config(api_key), team_id, job_id, should_use_incremental_field, db_incremental_field_last_value
        )
    else:
        resource = _list_resource(config, _client_config(api_key), team_id, job_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Full-refresh endpoints have no server-side order guarantee; billing_usage requests
        # `startTime` ascending via the incremental window, so asc holds for every endpoint.
        sort_mode="asc",
    )
