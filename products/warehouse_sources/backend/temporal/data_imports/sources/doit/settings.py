from typing import Any

from posthog.dataclasses import frozen


@frozen
class DoItEndpoint:
    path: str
    # Key of the row array in the response envelope.
    data_selector: str
    # Where the next-page token sits in the response body.
    cursor_path: str
    primary_keys: list[str]
    params: dict[str, Any]


# Fixed list endpoints synced alongside the account's reports. The names are PascalCase so they can
# never equal a report schema name, which is always a normalized lowercase identifier.
# All of them are full refresh: budgets, insights, anomalies, and invoices change in place
# (utilization, status, balance), and DoiT has no updated-since filter to pick those changes up.
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
}
