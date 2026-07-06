from dataclasses import dataclass
from typing import Optional


@dataclass
class MailerLiteEndpointConfig:
    name: str
    path: str
    # Stable datetime field used for partitioning. Must be a created-style field that
    # never changes after a row is written (never updated_at). `None` disables partitioning.
    partition_key: Optional[str] = None


# MailerLite's current API (https://connect.mailerlite.com/api) exposes no server-side
# timestamp filter on any list endpoint, so every endpoint is full-refresh only. See
# api_inventory.md for the verification notes. All list responses are flat JSON objects
# wrapped in `{"data": [...], "links": {...}, "meta": {...}}` and paginate by following
# `links.next` (cursor for subscribers, page number for the rest).
MAILERLITE_ENDPOINTS: dict[str, MailerLiteEndpointConfig] = {
    "subscribers": MailerLiteEndpointConfig(
        name="subscribers",
        path="/subscribers",
        partition_key="created_at",
    ),
    "campaigns": MailerLiteEndpointConfig(
        name="campaigns",
        path="/campaigns",
        partition_key="created_at",
    ),
    "groups": MailerLiteEndpointConfig(
        name="groups",
        path="/groups",
        partition_key="created_at",
    ),
    "segments": MailerLiteEndpointConfig(
        name="segments",
        path="/segments",
        partition_key="created_at",
    ),
    "fields": MailerLiteEndpointConfig(
        name="fields",
        path="/fields",
        # Custom field definitions carry no creation timestamp, so they aren't partitioned.
        partition_key=None,
    ),
    "automations": MailerLiteEndpointConfig(
        name="automations",
        path="/automations",
        partition_key="created_at",
    ),
    "forms_popup": MailerLiteEndpointConfig(
        name="forms_popup",
        path="/forms/popup",
        partition_key="created_at",
    ),
    "forms_embedded": MailerLiteEndpointConfig(
        name="forms_embedded",
        path="/forms/embedded",
        partition_key="created_at",
    ),
    "forms_promotion": MailerLiteEndpointConfig(
        name="forms_promotion",
        path="/forms/promotion",
        partition_key="created_at",
    ),
    "webhooks": MailerLiteEndpointConfig(
        name="webhooks",
        path="/webhooks",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(MAILERLITE_ENDPOINTS.keys())
