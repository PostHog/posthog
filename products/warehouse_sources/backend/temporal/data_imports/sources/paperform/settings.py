from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# `created_at` / `updated_at` are rendered in the account's local timezone; the `_utc` variants are
# proper UTC ISO 8601 strings, so those are what we cursor and partition on.
CREATED_AT_UTC_INCREMENTAL: IncrementalField = {
    "label": "created_at_utc",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at_utc",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class PaperformEndpointConfig:
    name: str
    # Path under the v1 base URL. Form-scoped endpoints carry a `{form_id}` placeholder that the
    # transport fills in per form while fanning out.
    path: str
    # Key inside the response's `results` object that holds the row array,
    # e.g. {"results": {"submissions": [...]}, "has_more": true}.
    results_key: str = ""
    # Form-scoped endpoints live under /forms/{slug_or_id}/... and must be iterated once per form.
    form_scoped: bool = False
    # Whether the endpoint accepts limit/after_id/sort pagination params. Fields, products, and
    # coupons return the whole collection in one response (their only query param is `search`).
    paginated: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Only submissions expose a server-side creation-time filter (`after_date`) worth cursoring on.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning; None disables partitioning.
    partition_key: str | None = None


# Paperform v1 API (https://paperform.readme.io). Most resources hang off a form, so the transport
# lists forms once and fans the form-scoped endpoints out per form, injecting `form_id` into every
# row to keep composite keys unique across the whole table.
#
# Incremental sync: list endpoints filter with `after_date` on creation time only, so it's a safe
# cursor solely for immutable rows. Submissions never change once made -> incremental. Partial
# submissions keep mutating after creation (`last_answered`, `updated_at`, `submitted_at`) and forms
# are edited in place, so a creation-time cursor would freeze their updates -> full refresh only.
PAPERFORM_ENDPOINTS: dict[str, PaperformEndpointConfig] = {
    "forms": PaperformEndpointConfig(
        name="forms",
        path="/forms",
        results_key="forms",
        partition_key="created_at_utc",
    ),
    "form_fields": PaperformEndpointConfig(
        name="form_fields",
        path="/forms/{form_id}/fields",
        results_key="fields",
        form_scoped=True,
        paginated=False,
        # A field's `key` is only unique within its form.
        primary_keys=["form_id", "key"],
    ),
    "submissions": PaperformEndpointConfig(
        name="submissions",
        path="/forms/{form_id}/submissions",
        results_key="submissions",
        form_scoped=True,
        # Submission ids are UUIDs but the docs don't state global uniqueness, so keep the parent
        # form id in the key.
        primary_keys=["form_id", "id"],
        incremental_fields=[CREATED_AT_UTC_INCREMENTAL],
        partition_key="created_at_utc",
    ),
    "partial_submissions": PaperformEndpointConfig(
        name="partial_submissions",
        path="/forms/{form_id}/partial-submissions",
        results_key="partial-submissions",
        form_scoped=True,
        primary_keys=["form_id", "id"],
        partition_key="created_at_utc",
    ),
    "products": PaperformEndpointConfig(
        name="products",
        path="/forms/{form_id}/products",
        results_key="products",
        form_scoped=True,
        paginated=False,
        # A product's SKU is only unique within its form.
        primary_keys=["form_id", "SKU"],
    ),
    "coupons": PaperformEndpointConfig(
        name="coupons",
        path="/forms/{form_id}/coupons",
        results_key="coupons",
        form_scoped=True,
        paginated=False,
        # A coupon's code is only unique within its form.
        primary_keys=["form_id", "code"],
    ),
    "spaces": PaperformEndpointConfig(
        name="spaces",
        path="/spaces",
        results_key="spaces",
        partition_key="created_at_utc",
    ),
}

ENDPOINTS = tuple(PAPERFORM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PAPERFORM_ENDPOINTS.items()
}
