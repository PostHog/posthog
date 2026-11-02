from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class FlexmailEndpointConfig:
    # `name` repeats the FLEXMAIL_ENDPOINTS key because `build_dependent_resource` reads it off
    # the config rather than the mapping key.
    name: str
    path: str
    # `paginated` marks endpoints that accept `limit`/`offset` and wrap results in the HAL
    # collection envelope (`total`/`limit`/`offset`); the rest return the full collection at once.
    paginated: bool = True
    # Flexmail identifiers are account-unique (integers or UUIDs depending on the resource), so
    # `id` is a safe primary key for every top-level endpoint. A per-contact sub-resource repeats
    # the same sub-resource id once per contact, so it keys on the contact as well.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Set on endpoints fetched once per row of a parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    # Nothing here is incremental: no Flexmail list endpoint exposes a server-side timestamp
    # filter. Both fields exist for `build_dependent_resource`'s endpoint-config protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Never read: every paginator here sends its own `limit`, so the fan-out builder is told to
    # add no page-size param. Present for the same protocol.
    page_size: int = 0


# Both per-contact sub-resources are addressed the same way, and the config is frozen, so one
# instance serves both. A contact deleted between the contact listing and the sub-resource fetch
# answers 404 — skip that contact rather than failing the whole table.
CONTACT_FANOUT = DependentEndpointConfig(
    parent_name="contacts",
    resolve_param="id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "contact_id"},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


# Flexmail REST API (https://api.flexmail.eu) endpoints. All are full-refresh only: no endpoint
# accepts a server-side timestamp filter (contacts only filter on `email`/`interest`, custom
# fields on `type`/`language`), so there is no incremental cursor to advance.
#
# The two `contact_*` tables fan out one request per contact: a sync costs the contact listing
# plus one request per contact, against a 60 requests/minute per-account rate limit. They are
# separately selectable schemas, and joining contacts to their sources or interests is not
# possible from any other endpoint, so the cost is the user's call to make.
FLEXMAIL_ENDPOINTS: dict[str, FlexmailEndpointConfig] = {
    "contact_interest_subscriptions": FlexmailEndpointConfig(
        name="contact_interest_subscriptions",
        path="/contacts/{id}/interest-subscriptions",
        # Takes no `limit`/`offset`; answers with the contact's whole subscription collection.
        paginated=False,
        primary_keys=["contact_id", "interest_id"],
        fanout=CONTACT_FANOUT,
    ),
    "contact_sources": FlexmailEndpointConfig(
        name="contact_sources",
        path="/contacts/{id}/sources",
        primary_keys=["contact_id", "id"],
        fanout=CONTACT_FANOUT,
    ),
    "contacts": FlexmailEndpointConfig(name="contacts", path="/contacts"),
    "custom_fields": FlexmailEndpointConfig(name="custom_fields", path="/custom-fields", paginated=False),
    "interests": FlexmailEndpointConfig(name="interests", path="/interests"),
    "opt_in_forms": FlexmailEndpointConfig(name="opt_in_forms", path="/opt-in-forms", paginated=False),
    "preferences": FlexmailEndpointConfig(name="preferences", path="/preferences"),
    "segments": FlexmailEndpointConfig(name="segments", path="/segments", paginated=False),
    "sources": FlexmailEndpointConfig(name="sources", path="/sources"),
}

ENDPOINTS = tuple(FLEXMAIL_ENDPOINTS.keys())
