from dataclasses import field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    ResponseAction,
    frozen,
)

BASE_URL = "https://api.cyberimpact.com"

# Documented maximum of `limit` on every list endpoint.
PAGE_SIZE = 10_000

# Without this, dates come back as "Y-m-d H:i:s.u" in Eastern time with no offset.
DATE_PARAMS: dict[str, Any] = {"dateReturnFormat": "ISO8601"}


@frozen
class CyberimpactEndpointConfig:
    name: str
    path: str
    # Key of the row list in the response body. None for a single-object response.
    data_selector: Optional[str]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    params: dict[str, Any] = field(default_factory=dict)
    paginated: bool = True
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


# A mailing or group deleted between the parent listing and the child fetch drops out of the sync.
_MISSING_PARENT_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


def _mailing_fanout(child_params: dict[str, Any] | None = None) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="sent_mailings",
        resolve_param="mailing_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "mailing_id"},
        parent_params={"limit": PAGE_SIZE, "sort": "date_asc", **DATE_PARAMS},
        child_params={**DATE_PARAMS, **(child_params or {})},
        child_response_actions=_MISSING_PARENT_IGNORE,
    )


_RECIPIENT_PARAMS = {"limit": PAGE_SIZE, "sort": "email_asc"}

UPDATED_ON_FIELD = "updatedOn"

CYBERIMPACT_ENDPOINTS: dict[str, CyberimpactEndpointConfig] = {
    config.name: config
    for config in (
        CyberimpactEndpointConfig(
            name="members",
            path="/members",
            data_selector="members",
            # The default status is "active", which leaves out members that are in no group.
            params={"status": "all"},
            partition_key="joinedOn",
            incremental_fields=[
                IncrementalField(
                    label=UPDATED_ON_FIELD,
                    type=IncrementalFieldType.DateTime,
                    field=UPDATED_ON_FIELD,
                    field_type=IncrementalFieldType.DateTime,
                )
            ],
            default_incremental_field=UPDATED_ON_FIELD,
        ),
        # Unsubscribed and bounced rows carry no member id, so the email is their key. Both lists
        # only filter on the unsubscribe or bounce date, and a profile edit changes a row after
        # that, so they are full refresh only.
        CyberimpactEndpointConfig(
            name="unsubscribed_members",
            path="/members/unsubscribed",
            data_selector="members",
            primary_keys=["email"],
            params={"sort": "email_asc"},
            partition_key="unsubscribedOn",
        ),
        CyberimpactEndpointConfig(
            name="bounced_members",
            path="/members/bounced",
            data_selector="members",
            primary_keys=["email"],
            params={"sort": "email_asc"},
        ),
        CyberimpactEndpointConfig(
            name="groups",
            path="/groups",
            data_selector="groups",
            params={"sort": "date_asc"},
            partition_key="createdOn",
        ),
        CyberimpactEndpointConfig(
            name="group_members",
            path="/groups/{group_id}/members",
            data_selector="members",
            primary_keys=["group_id", "id"],
            fanout=DependentEndpointConfig(
                parent_name="groups",
                resolve_param="group_id",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "group_id"},
                parent_params={"limit": PAGE_SIZE, "sort": "date_asc", **DATE_PARAMS},
                child_params={"limit": PAGE_SIZE, "sort": "email_asc", **DATE_PARAMS},
                child_response_actions=_MISSING_PARENT_IGNORE,
            ),
        ),
        CyberimpactEndpointConfig(
            name="custom_fields",
            path="/customfields",
            data_selector="customFields",
            paginated=False,
        ),
        # The sent listing leaves out archived mailings, which have their own listing.
        CyberimpactEndpointConfig(
            name="sent_mailings",
            path="/mailings/sent",
            data_selector="mailings",
            params={"sort": "date_asc"},
            partition_key="startedOn",
        ),
        CyberimpactEndpointConfig(
            name="scheduled_mailings",
            path="/mailings/scheduled",
            data_selector="mailings",
            params={"sort": "date_asc"},
        ),
        CyberimpactEndpointConfig(
            name="archived_mailings",
            path="/mailings/archived",
            data_selector="mailings",
            params={"sort": "date_asc"},
            partition_key="startedOn",
        ),
        # Delivery, open and click counts and rates only come from the single-mailing endpoint.
        CyberimpactEndpointConfig(
            name="mailing_stats",
            path="/mailings/{mailing_id}",
            data_selector=None,
            primary_keys=["id"],
            paginated=False,
            fanout=_mailing_fanout(),
        ),
        # A deleted member keeps its recipient row with a null idMember, so the email is the key.
        CyberimpactEndpointConfig(
            name="mailing_opens",
            path="/mailings/{mailing_id}/recipients/opened",
            data_selector="recipients",
            primary_keys=["mailing_id", "email"],
            fanout=_mailing_fanout(_RECIPIENT_PARAMS),
        ),
        CyberimpactEndpointConfig(
            name="mailing_clicks",
            path="/mailings/{mailing_id}/recipients/clicked",
            data_selector="recipients",
            primary_keys=["mailing_id", "email"],
            fanout=_mailing_fanout(_RECIPIENT_PARAMS),
        ),
        CyberimpactEndpointConfig(
            name="templates",
            path="/templates",
            data_selector="templates",
            params={"sort": "created_asc"},
            partition_key="createdOn",
        ),
    )
}

ENDPOINTS = tuple(CYBERIMPACT_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CYBERIMPACT_ENDPOINTS.items() if config.incremental_fields
}
