from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Xendit's public API only exposes two list endpoints that enumerate a merchant's own records:
# `GET /transactions` (the unified money-movement ledger) and `GET /v2/accounts` (xenPlatform
# sub-accounts). Everything else in the current API reference is either a single-object lookup
# (payments, payouts, sessions, balance), a search that requires an exact identifier
# (`GET /customers` requires `reference_id`), or a child collection with no way to enumerate its
# parents (`GET /recurring/plans/{id}/cycles`), so none of them can be synced as a table.
#
# Both list endpoints share the same contract: cursor pagination via `after_id` + `has_more`, and
# server-side `created[gte]` / `updated[gte]` range filters.

XENDIT_BASE_URL = "https://api.xendit.co"

# `limit` is documented as capped at 50 on /v2/accounts. /transactions documents a default of 10 but
# no maximum, so use the one cap Xendit publishes for this pagination style rather than guessing higher.
PAGE_SIZE = 50


@dataclass
class XenditEndpointConfig:
    name: str
    path: str
    # Timestamp fields the endpoint filters on server-side, as `<field>[gte]` query params.
    filterable_timestamps: tuple[str, ...] = ()
    partition_key: str | None = "created"
    # Sub-account listing only returns data for xenPlatform accounts, so it is off by default.
    should_sync_default: bool = True
    permission: str = ""
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [
            {
                "label": name,
                "type": IncrementalFieldType.DateTime,
                "field": name,
                "field_type": IncrementalFieldType.DateTime,
            }
            for name in self.filterable_timestamps
        ]


XENDIT_ENDPOINTS: dict[str, XenditEndpointConfig] = {
    "transactions": XenditEndpointConfig(
        name="transactions",
        path="/transactions",
        filterable_timestamps=("updated", "created"),
        permission="Transaction Read",
    ),
    "accounts": XenditEndpointConfig(
        name="accounts",
        path="/v2/accounts",
        filterable_timestamps=("updated", "created"),
        should_sync_default=False,
        permission="Accounts Read",
    ),
}

ENDPOINTS = tuple(XENDIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in XENDIT_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in XENDIT_ENDPOINTS.items()}

# Default cursor field when a schema has no explicit selection.
DEFAULT_INCREMENTAL_FIELD = "updated"
