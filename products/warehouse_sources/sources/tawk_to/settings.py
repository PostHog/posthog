from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class TawkToEndpointConfig:
    name: str
    # RPC-style method name appended to the base URL (e.g. "chat.list"). Every tawk.to API
    # call is a POST with a JSON body — there are no GET/PUT/DELETE verbs.
    method: str
    # Whether the endpoint requires a `propertyId` in the request body. Property-scoped
    # endpoints fan out over every property on the account (or the single configured one).
    scoped_to_property: bool
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Only set where the field is
    # verified to exist on the response objects.
    partition_key: Optional[str] = None
    # Whether the endpoint's list responses are paginated with `size`/`offset` body params.
    paginated: bool = True
    should_sync_default: bool = True


# tawk.to's full API reference is gated behind an access-approval process, so the endpoint
# behavior below is assembled from the public help-center summary, community-reported request
# bodies, and live probes of the RPC paths (401 vs 404). `chat.list` is confirmed to accept
# `size`/`offset` pagination with `{ok, total, data}` responses; `ticket.list` is assumed to
# paginate the same way (a repeated-page guard in tawk_to.py protects against the assumption
# being wrong). List endpoints also accept `startDate`/`endDate` filters, but community reports
# of those filters silently returning empty result sets mean we can't trust them for
# incremental sync — every endpoint ships full-refresh only until the filters are verified
# against a live account.
TAWK_TO_ENDPOINTS: dict[str, TawkToEndpointConfig] = {
    "properties": TawkToEndpointConfig(
        name="properties",
        method="property.list",
        scoped_to_property=False,
        primary_keys=["propertyId"],
        paginated=False,
    ),
    "chats": TawkToEndpointConfig(
        name="chats",
        method="chat.list",
        scoped_to_property=True,
        primary_keys=["id"],
        partition_key="createdOn",
    ),
    "tickets": TawkToEndpointConfig(
        name="tickets",
        method="ticket.list",
        scoped_to_property=True,
        primary_keys=["id"],
    ),
    "members": TawkToEndpointConfig(
        name="members",
        method="members.list",
        scoped_to_property=True,
        # Member ids can't be verified without an approved API key; the composite key is a
        # best guess. Harmless while the endpoint is full-refresh only (no merge happens).
        primary_keys=["propertyId", "id"],
        paginated=False,
    ),
}

ENDPOINTS = tuple(TAWK_TO_ENDPOINTS.keys())

# No endpoint advertises incremental sync: the API's startDate/endDate filters are
# community-reported to be unreliable and can't be curl-verified while API access is gated.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
