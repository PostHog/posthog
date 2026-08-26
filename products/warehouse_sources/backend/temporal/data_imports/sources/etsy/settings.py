from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


# Every Etsy v3 timestamp is Unix epoch seconds, and the matching filters
# (min_created / min_last_modified) take epoch seconds too, so the cursor is an integer.
def _epoch_field(name: str, label: str) -> IncrementalField:
    return {
        "label": label,
        "type": IncrementalFieldType.Integer,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


_CREATED = _epoch_field("created_timestamp", "created_timestamp")
_UPDATED = _epoch_field("updated_timestamp", "updated_timestamp")

# Listing states Etsy's getListingsByShop accepts. The filter takes one state at a time, so a full
# catalog needs one pass per state.
LISTING_STATES: tuple[str, ...] = ("active", "inactive", "sold_out", "draft", "expired")


@dataclass(frozen=True)
class EtsyEndpointConfig:
    name: str
    # Appended to /shops/{shop_id}. Empty string is the shop record itself.
    path: str
    primary_keys: list[str]
    # Incremental field name -> the Etsy filter prefix that windows it, e.g. "created" drives
    # min_created/max_created. Only fields listed here can be synced incrementally.
    window_params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Filter prefix used to walk history when the schema is NOT synced incrementally. `None` means
    # the endpoint has no time filter at all, so it is paginated by offset alone.
    default_window_param: str | None = None
    # Extra query params sent on every request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Endpoint returns a bare object rather than the {count, results} envelope.
    single_object: bool = False
    # Endpoint returns {count, results} but accepts no limit/offset.
    paginated: bool = True
    # Fan out one request per listing state (Etsy filters a single state per request).
    fan_out_listing_states: bool = False
    # Rows live under this key of each result item rather than being the item itself. Used to
    # derive transactions from the receipts endpoint, which is the only place Etsy exposes them
    # behind a time filter.
    expand_key: str | None = None


ETSY_ENDPOINTS: dict[str, EtsyEndpointConfig] = {
    "shop": EtsyEndpointConfig(
        name="shop",
        path="",
        primary_keys=["shop_id"],
        single_object=True,
    ),
    "shop_sections": EtsyEndpointConfig(
        name="shop_sections",
        path="/sections",
        primary_keys=["shop_section_id"],
        paginated=False,
    ),
    "listings": EtsyEndpointConfig(
        name="listings",
        path="/listings",
        primary_keys=["listing_id"],
        # getListingsByShop exposes no created/updated filter, only a sort, so it is full refresh.
        # Sorting ascending by creation keeps offset paging stable while new listings are added.
        extra_params={"sort_on": "created", "sort_order": "asc"},
        fan_out_listing_states=True,
    ),
    "receipts": EtsyEndpointConfig(
        name="receipts",
        path="/receipts",
        primary_keys=["receipt_id"],
        window_params={"updated_timestamp": "last_modified", "created_timestamp": "created"},
        incremental_fields=[_UPDATED, _CREATED],
        default_window_param="created",
    ),
    "transactions": EtsyEndpointConfig(
        name="transactions",
        # Derived from the receipts payload: the shop-level transactions endpoint has no time
        # filter, so it cannot page past Etsy's 12,000 offset ceiling on a busy shop.
        path="/receipts",
        primary_keys=["transaction_id"],
        # The window filters the parent receipt, not the transaction, so a transaction-level
        # watermark would be wrong. Full refresh only.
        default_window_param="created",
        expand_key="transactions",
    ),
    "reviews": EtsyEndpointConfig(
        name="reviews",
        path="/reviews",
        # One review per transaction, so the transaction id is the review's identity.
        primary_keys=["transaction_id"],
        window_params={"created_timestamp": "created"},
        incremental_fields=[_CREATED],
        default_window_param="created",
    ),
    "ledger_entries": EtsyEndpointConfig(
        name="ledger_entries",
        path="/payment-account/ledger-entries",
        primary_keys=["entry_id"],
        window_params={"created_timestamp": "created"},
        incremental_fields=[_CREATED],
        # Etsy rejects this endpoint without min_created/max_created, so it is always windowed.
        default_window_param="created",
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(ETSY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ETSY_ENDPOINTS.items()
}
