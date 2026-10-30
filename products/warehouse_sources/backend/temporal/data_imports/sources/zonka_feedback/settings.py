from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class ZonkaFeedbackEndpointConfig:
    name: str
    path: str
    # Zonka Feedback object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    # False for list endpoints with no documented `page` parameter: a page-number walk that stops on
    # an empty page would request the same full list forever.
    paginated: bool = True


# Zonka Feedback v2.1 account-level list endpoints. All except `distribution_logs` are full-refresh
# only: their list endpoints expose page/page_size pagination but no documented server-side
# `updated_after` date cursor, so there is no genuine incremental cursor to advance.
ZONKA_FEEDBACK_ENDPOINTS: dict[str, ZonkaFeedbackEndpointConfig] = {
    "responses": ZonkaFeedbackEndpointConfig(name="responses", path="/responses"),
    "surveys": ZonkaFeedbackEndpointConfig(name="surveys", path="/surveys"),
    "contacts": ZonkaFeedbackEndpointConfig(name="contacts", path="/contacts"),
    # Snake_case schema name, hyphenated vendor path — the shareable link objects returned by the
    # Survey Links API. Zonka object IDs live in the `id` field, so the default primary key applies.
    "survey_links": ZonkaFeedbackEndpointConfig(name="survey_links", path="/survey-links"),
    "workspaces": ZonkaFeedbackEndpointConfig(name="workspaces", path="/workspaces", paginated=False),
    "locations": ZonkaFeedbackEndpointConfig(name="locations", path="/locations"),
    "users": ZonkaFeedbackEndpointConfig(name="users", path="/users"),
    # Log rows carry no ID. One row is one send of a survey on one channel to one recipient, so the
    # send time completes the key.
    "distribution_logs": ZonkaFeedbackEndpointConfig(
        name="distribution_logs",
        path="/distribution-logs",
        primary_keys=["surveyId", "channel", "to", "sentDateTime"],
        partition_key="sentDateTime",
    ),
}

ENDPOINTS = tuple(ZONKA_FEEDBACK_ENDPOINTS.keys())

# `distribution-logs` requires a `startDate`/`endDate` window, which doubles as a server-side filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "distribution_logs": [incremental_field("sentDateTime")],
}

# The send channels `distribution-logs` accepts; the endpoint requires one per request.
DISTRIBUTION_LOG_CHANNELS: tuple[str, ...] = ("email", "sms", "whatsapp")
