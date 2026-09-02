from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

FetchMethod = Literal["get", "post"]

# (connect, read) timeout for sync requests against the user-configured host. Bounds how long a
# stalled or slow-responding custom host can occupy an import worker; the credential probe in
# bigeye.py uses its own shorter timeout.
REQUEST_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)


@frozen
class BigeyeEndpointConfig:
    name: str
    table_name: str
    path: str
    method: FetchMethod
    # Key in the JSON response body that holds the list of rows.
    data_selector: str
    # True for the `POST .../fetch` endpoints that page via a `pageCursor` in the JSON body.
    # False for the small GET endpoints that return their full result in one response.
    paginated: bool
    primary_key: str = "id"


# Bigeye's v1 API has no documented "updated since" filter on any list endpoint (see
# INCREMENTAL_FIELDS below), so every table here is full refresh. The `.../fetch` endpoints are
# still resumable via their `pageCursor`, which matters for large workspaces (many sources/tables/
# issues) surviving a heartbeat timeout mid-sync.
BIGEYE_ENDPOINTS: dict[str, BigeyeEndpointConfig] = {
    "Workspaces": BigeyeEndpointConfig(
        name="Workspaces",
        table_name="workspaces",
        path="/api/v1/workspaces",
        method="get",
        data_selector="workspaces",
        paginated=False,
    ),
    "Sources": BigeyeEndpointConfig(
        name="Sources",
        table_name="sources",
        path="/api/v1/sources/fetch",
        method="post",
        data_selector="sources",
        paginated=True,
    ),
    "Tables": BigeyeEndpointConfig(
        name="Tables",
        table_name="tables",
        path="/api/v1/tables/fetch",
        method="post",
        data_selector="tables",
        paginated=True,
    ),
    "Metrics": BigeyeEndpointConfig(
        name="Metrics",
        table_name="metrics",
        path="/api/v1/metrics",
        method="get",
        data_selector="metrics",
        paginated=False,
    ),
    "Collections": BigeyeEndpointConfig(
        name="Collections",
        table_name="collections",
        path="/api/v1/collections/info",
        method="get",
        data_selector="collectionInfos",
        paginated=False,
        # Rows nest their id under `collectionConfiguration.id`; `_flatten_collection` copies it
        # to the top level before this primary key is applied.
        primary_key="id",
    ),
    "Issues": BigeyeEndpointConfig(
        name="Issues",
        table_name="issues",
        path="/api/v1/issues/fetch",
        method="post",
        # Bigeye's issue-list response wraps rows under the singular key `issue`, not `issues`.
        data_selector="issue",
        paginated=True,
    ),
}

ENDPOINTS = tuple(BIGEYE_ENDPOINTS.keys())

# No endpoint exposes a server-side "updated since" / "modified after" filter in the published
# API reference, so nothing here can be a true incremental sync (see the module docstring in
# bigeye.py for what was checked). Every table syncs full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
