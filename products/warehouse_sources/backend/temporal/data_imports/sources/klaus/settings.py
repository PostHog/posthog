from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class KlausEndpointConfig:
    name: str
    # Path under https://{subdomain}.zendesk.com/qa. Fan-out paths carry a {workspace} placeholder.
    path: str
    # Top-level key the list of records lives under in the response body
    # (each collection is wrapped, e.g. {"conversations": [...], "pagination": {...}}).
    data_selector: str
    # Whether the endpoint accepts page/pageSize params. The catalog endpoints
    # (users, workspaces, quizzes, scorecards) return everything in one response.
    paginated: bool = True
    # Whether the API marks fromDate as required. Full-refresh syncs of these
    # endpoints pass DEFAULT_FROM_DATE to cover all history.
    requires_from_date: bool = False
    # The single advertised incremental option per endpoint is deliberately the
    # earliest stable timestamp on the row (creation-time, never updated-time):
    # Zendesk QA doesn't document exactly which timestamp fromDate filters on, and
    # a watermark tracked on the earliest field can only under-advance — re-fetching
    # an overlap that merge dedupes on the primary key — never skip rows.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by, or None to skip partitioning.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fan out one request stream per workspace (listed via /api/export/workspaces).
    # Rows get a `workspace_id` column injected so primary keys stay unique table-wide.
    fan_out_over_workspaces: bool = False
    page_size: int = 100


KLAUS_ENDPOINTS: dict[str, KlausEndpointConfig] = {
    "reviews": KlausEndpointConfig(
        name="reviews",
        path="/api/export/reviews",
        data_selector="conversations",
        requires_from_date=True,
        incremental_fields=[_datetime_incremental_field("createdAtISO")],
        partition_key="createdAtISO",
        # Rows are conversation-grain (reviews nested inside). externalId is the
        # helpdesk ticket id, unique only within its workspace.
        primary_keys=["workspaceId", "externalId"],
    ),
    "autoqa_reviews": KlausEndpointConfig(
        name="autoqa_reviews",
        path="/api/export/autoqa/reviews",
        data_selector="rows",
        requires_from_date=True,
        incremental_fields=[_datetime_incremental_field("conversationCreatedAt")],
        partition_key="conversationCreatedAt",
        primary_keys=["autoqaReviewId"],
    ),
    "autoqa_ratings": KlausEndpointConfig(
        name="autoqa_ratings",
        path="/api/export/autoqa/ratings",
        data_selector="rows",
        requires_from_date=True,
        incremental_fields=[_datetime_incremental_field("conversationCreatedAt")],
        partition_key="conversationCreatedAt",
        primary_keys=["autoqaRatingId"],
    ),
    "csat": KlausEndpointConfig(
        name="csat",
        path="/api/export/csat",
        data_selector="tickets",
        requires_from_date=True,
        incremental_fields=[_datetime_incremental_field("ticketCreatedAt")],
        partition_key="ticketCreatedAt",
        # CSAT rows have no dedicated id; a ticket can be surveyed more than once,
        # so the survey creation time disambiguates.
        primary_keys=["externalTicketId", "csatCreatedAt"],
    ),
    "users": KlausEndpointConfig(
        name="users",
        path="/api/export/users",
        data_selector="users",
        paginated=False,
    ),
    "workspaces": KlausEndpointConfig(
        name="workspaces",
        path="/api/export/workspaces",
        data_selector="workspaces",
        paginated=False,
    ),
    "quizzes": KlausEndpointConfig(
        name="quizzes",
        path="/api/export/quizzes",
        data_selector="quizzes",
        paginated=False,
    ),
    "scorecards": KlausEndpointConfig(
        name="scorecards",
        path="/api/export/workspace/{workspace}/scorecards",
        data_selector="data",
        paginated=False,
        fan_out_over_workspaces=True,
        primary_keys=["workspace_id", "id"],
    ),
    "disputes": KlausEndpointConfig(
        name="disputes",
        path="/api/export/workspace/{workspace}/disputes",
        data_selector="disputes",
        # fromDate is optional on disputes; without a live account to verify the
        # filter actually narrows results server-side, disputes ship full refresh.
        fan_out_over_workspaces=True,
        primary_keys=["workspace_id", "disputeId"],
    ),
    "calibration_sessions": KlausEndpointConfig(
        name="calibration_sessions",
        path="/api/export/workspace/{workspace}/calibration-sessions",
        data_selector="calibrationSessions",
        requires_from_date=True,
        incremental_fields=[_datetime_incremental_field("createdAt")],
        fan_out_over_workspaces=True,
        primary_keys=["workspace_id", "id"],
    ),
}

ENDPOINTS = tuple(KLAUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KLAUS_ENDPOINTS.items() if config.incremental_fields
}
