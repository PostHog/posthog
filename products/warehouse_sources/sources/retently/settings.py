from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

# Documented maximum page size; the largest page minimises round trips against the ~150 req/min
# rate limit.
PAGE_SIZE = 1000


@dataclass(frozen=True)
class RetentlyEndpointConfig:
    name: str
    path: str
    # jsonpath to the record array in the response. Most endpoints nest it under the `data` object
    # (e.g. {"data": {"responses": [...]}} -> "data.responses"), campaigns/templates document the
    # array at the top level ("campaigns"/"templates"), and /reports returns a bare list under
    # `data` ("data").
    data_selector: str
    primary_keys: Optional[list[str]] = None
    # Whether the endpoint accepts `page`/`limit` query params. Campaigns, templates and reports
    # are documented without pagination and return the full collection in one response.
    paginated: bool = True
    # Ascending sort field requested explicitly so page-number pagination stays stable while new
    # rows are appended during a sync (Retently sorts descending by default).
    sort_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style field.
    partition_key: Optional[str] = None
    # The /{metric}/score endpoints return one object under `data`, not a list of rows.
    single_object: bool = False
    fanout: Optional[DependentEndpointConfig] = None
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


def _created_date_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "createdDate",
            "type": IncrementalFieldType.DateTime,
            "field": "createdDate",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Retently v2 REST API endpoints (https://www.retently.com/api/). Incremental sync is only enabled
# on feedback, where the documented `startDate` query param filters responses server-side by their
# creation date. Customers also documents `startDate`/`endDate`, but the filtered field is not
# specified and customer records are mutable (properties, tags), so a creation-window incremental
# would silently miss updates — customers stays full refresh. Companies expose no date filter, and
# outbox rows carry no consistently documented unique identifier (`surveyId` is absent from some
# example rows), so there is no safe merge key and outbox stays full refresh too. The score, trend
# and suppression endpoints take no date filter or pagination and return the full collection (or a
# point-in-time snapshot) in one response, so they are full refresh as well.
RETENTLY_ENDPOINTS: dict[str, RetentlyEndpointConfig] = {
    "customers": RetentlyEndpointConfig(
        name="customers",
        path="/customers",
        data_selector="data.subscribers",
        primary_keys=["id"],
        sort_param="createdDate",
        partition_key="createdDate",
    ),
    "companies": RetentlyEndpointConfig(
        name="companies",
        path="/companies",
        data_selector="data.companies",
        primary_keys=["id"],
        sort_param="createdDate",
        partition_key="createdDate",
    ),
    "feedback": RetentlyEndpointConfig(
        name="feedback",
        path="/feedback",
        data_selector="data.responses",
        primary_keys=["id"],
        sort_param="createdDate",
        incremental_fields=_created_date_incremental_field(),
        partition_key="createdDate",
    ),
    "outbox": RetentlyEndpointConfig(
        name="outbox",
        path="/outbox",
        data_selector="data.surveys",
        primary_keys=None,
        sort_param="surveyCreatedDate",
    ),
    "campaigns": RetentlyEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
        primary_keys=["id"],
        paginated=False,
    ),
    "templates": RetentlyEndpointConfig(
        name="templates",
        path="/templates",
        data_selector="templates",
        primary_keys=["id"],
        paginated=False,
    ),
    "reports": RetentlyEndpointConfig(
        name="reports",
        path="/reports",
        data_selector="data",
        primary_keys=["campaignId"],
        paginated=False,
    ),
    # One table per metric: each metric's score payload has its own keys (e.g. `nps`, `promoters`).
    **{
        f"{metric}_score": RetentlyEndpointConfig(
            name=f"{metric}_score",
            path=f"/{metric}/score",
            data_selector="data",
            paginated=False,
            single_object=True,
        )
        for metric in ("nps", "csat", "ces", "star")
    },
    "trend_groups": RetentlyEndpointConfig(
        name="trend_groups",
        path="/trends",
        data_selector="groups",
        primary_keys=["_id"],
        paginated=False,
    ),
    "trends": RetentlyEndpointConfig(
        name="trends",
        path="/trends/{groupId}",
        data_selector="trends",
        primary_keys=["groupId", "_id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="trend_groups",
            resolve_param="groupId",
            resolve_field="_id",
            include_from_parent=["_id"],
            parent_field_renames={"_id": "groupId"},
            # A group deleted between the group listing and this fetch 404s; skip it instead of
            # failing the whole fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "suppressed_emails": RetentlyEndpointConfig(
        name="suppressed_emails",
        path="/suppressions/emails",
        data_selector="data",
        primary_keys=["id"],
        paginated=False,
    ),
    "suppressed_domains": RetentlyEndpointConfig(
        name="suppressed_domains",
        path="/suppressions/domains",
        data_selector="data",
        primary_keys=["id"],
        paginated=False,
    ),
}

ENDPOINTS = tuple(RETENTLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RETENTLY_ENDPOINTS.items() if config.incremental_fields
}
