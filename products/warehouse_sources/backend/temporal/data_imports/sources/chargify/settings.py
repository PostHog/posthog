import dataclasses

from products.warehouse_sources.backend.types import IncrementalField


@dataclasses.dataclass(frozen=True)
class ChargifyEndpoint:
    """Declarative metadata for a Chargify (Maxio Advanced Billing) list endpoint.

    Chargify list endpoints return a bare JSON array of single-key-wrapped objects
    (e.g. ``[{"customer": {...}}, ...]``), so ``data_selector`` unwraps the payload
    key. Pagination is page-number based (``page`` + ``per_page``, max 200).
    """

    name: str
    path: str
    data_selector: str
    primary_key: list[str]
    # A stable creation timestamp used for datetime partitioning. Every core Chargify
    # object exposes ``created_at`` (ISO 8601), which never changes after creation.
    partition_key: str | None
    # Extra query params merged onto the request (e.g. an explicit stable sort direction).
    params: dict[str, str | int] = dataclasses.field(default_factory=dict)


# Per-page maximum documented by the Chargify API (defaults to 20, caps at 200).
PER_PAGE = 200

CHARGIFY_ENDPOINTS: dict[str, ChargifyEndpoint] = {
    "Customers": ChargifyEndpoint(
        name="Customers",
        path="/customers.json",
        data_selector="[*].customer",
        primary_key=["id"],
        partition_key="created_at",
        # Customers list supports an explicit sort direction; oldest-first keeps page
        # boundaries stable across a full-refresh sync.
        params={"per_page": PER_PAGE, "direction": "asc"},
    ),
    "Subscriptions": ChargifyEndpoint(
        name="Subscriptions",
        path="/subscriptions.json",
        data_selector="[*].subscription",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE, "direction": "asc"},
    ),
    "Products": ChargifyEndpoint(
        name="Products",
        path="/products.json",
        data_selector="[*].product",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE},
    ),
    "ProductFamilies": ChargifyEndpoint(
        name="ProductFamilies",
        path="/product_families.json",
        data_selector="[*].product_family",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE},
    ),
    "Components": ChargifyEndpoint(
        name="Components",
        path="/components.json",
        data_selector="[*].component",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE},
    ),
    "Transactions": ChargifyEndpoint(
        name="Transactions",
        path="/transactions.json",
        data_selector="[*].transaction",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE, "direction": "asc"},
    ),
    "Events": ChargifyEndpoint(
        name="Events",
        path="/events.json",
        data_selector="[*].event",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE, "direction": "asc"},
    ),
    "Invoices": ChargifyEndpoint(
        name="Invoices",
        path="/invoices.json",
        # The Invoices API wraps its list under an ``invoices`` key alongside a ``meta``
        # object (unlike the bare-array endpoints above), so the selector targets it.
        data_selector="invoices",
        primary_key=["id"],
        partition_key="created_at",
        params={"per_page": PER_PAGE, "direction": "asc"},
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(CHARGIFY_ENDPOINTS.keys())

# Chargify documents server-side date filtering (``date_field`` + ``start_date``/``end_date``)
# on some list endpoints and id-based filtering (``since_id``) on events/transactions, but the
# filter behaviour and result ordering could not be verified against a live site, so every
# endpoint ships as full refresh for now. Incremental sync is a deliberate follow-up once the
# filters and sort semantics can be confirmed with a live smoke test — declaring an unverified
# watermark risks silently skipping rows. Keeping this map empty means every schema advertises
# no incremental fields and syncs via full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
