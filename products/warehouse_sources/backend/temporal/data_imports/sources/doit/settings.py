from typing import Any

from posthog.dataclasses import frozen


@frozen
class DoItParent:
    # Key of the parent endpoint in `DOIT_ENDPOINTS`.
    name: str
    # Path param -> parent row field bound into it.
    resolve_fields: dict[str, str]
    # Parent row field -> child column it is copied into.
    include_fields: dict[str, str]


@frozen
class DoItEndpoint:
    path: str
    # Key of the row array in the response envelope.
    data_selector: str
    # Where the next-page token sits in the response body.
    cursor_path: str
    primary_keys: list[str]
    params: dict[str, Any]
    parent: DoItParent | None = None


# Fixed list endpoints synced alongside the account's reports. The names are PascalCase so they can
# never equal a report schema name, which is always a normalized lowercase identifier.
# All of them are full refresh: their rows change in place (utilization, status, balance, ticket
# status), and DoiT has no updated-since filter to pick those changes up. Support tickets only filter
# on creation time, which would leave the status of older tickets stale.
DOIT_ENDPOINTS: dict[str, DoItEndpoint] = {
    "Budgets": DoItEndpoint(
        path="/analytics/v1/budgets",
        data_selector="budgets",
        cursor_path="pageToken",
        primary_keys=["id"],
        params={"maxResults": 50},
    ),
    "Insights": DoItEndpoint(
        path="/insights/v1/results",
        data_selector="results",
        cursor_path="pagination.pageToken",
        # The resource-results path addresses an insight by source and key, so a key alone is not
        # documented as unique.
        primary_keys=["source", "key"],
        params={"maxResults": 500},
    ),
    "Anomalies": DoItEndpoint(
        path="/anomalies/v1",
        data_selector="anomalies",
        cursor_path="pageToken",
        primary_keys=["id"],
        # Without `maxResults` DoiT returns every anomaly in a single response.
        params={"maxResults": 50},
    ),
    "Invoices": DoItEndpoint(
        path="/billing/v1/invoices",
        data_selector="invoices",
        cursor_path="pageToken",
        # The id is the invoice number, which each billing platform issues on its own.
        primary_keys=["platform", "id"],
        params={"maxResults": 50},
    ),
    "Assets": DoItEndpoint(
        path="/billing/v1/assets",
        data_selector="assets",
        cursor_path="pageToken",
        primary_keys=["id"],
        params={"maxResults": 50},
    ),
    "Annotations": DoItEndpoint(
        path="/analytics/v1/annotations",
        data_selector="annotations",
        cursor_path="pageToken",
        primary_keys=["id"],
        # A fixed order keeps page boundaries stable if annotations are added during the sync.
        params={"maxResults": 50, "sortBy": "timeCreated", "sortOrder": "asc"},
    ),
    "SupportTickets": DoItEndpoint(
        path="/support/v1/tickets",
        data_selector="tickets",
        cursor_path="pageToken",
        primary_keys=["id"],
        params={"maxResults": 100},
    ),
    "InsightResourceResults": DoItEndpoint(
        path="/insights/v1/results/source/{sourceID}/insight/{insightKey}/resource-results",
        data_selector="resourceResults",
        cursor_path="pageToken",
        # A resource can carry a result for several insights, so the insight is part of the key.
        primary_keys=["insight_source", "insight_key", "resourceId"],
        params={"maxResults": 1000},
        parent=DoItParent(
            name="Insights",
            resolve_fields={"sourceID": "source", "insightKey": "key"},
            include_fields={"source": "insight_source", "key": "insight_key"},
        ),
    ),
}
