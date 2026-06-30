from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# Preference order (lowercased) for auto-selecting an incremental field. Columns that
# advance on every write (`updated_at`) catch late-arriving updates that creation-only
# columns (`created_at`) miss, so they rank first. Falls back to the first candidate.
_INCREMENTAL_FIELD_PREFERENCE = [
    "updated_at",
    "updatedat",
    "modified_at",
    "modifiedat",
    "last_modified",
    "updated",
    "modified",
    "created_at",
    "createdat",
    "created",
]


@dataclass
class SourceSchema:
    name: str
    supports_incremental: bool
    supports_append: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    row_count: int | None = None
    supports_webhooks: bool = False
    # True for resources with no API list endpoint that can only be populated via webhooks
    # (e.g. Stripe `Discount`). The UI should hide non-webhook sync methods for these.
    webhook_only: bool = False
    supports_cdc: bool = False
    # Postgres-only: set by the Postgres source for heap tables / matviews (PG13+); all
    # other sources leave it False.
    supports_xmin: bool = False
    columns: list[tuple[str, str, bool]] = field(default_factory=list)
    foreign_keys: list[tuple[str, str, str]] = field(default_factory=list)
    description: str | None = None
    source_catalog: str | None = None
    source_schema: str | None = None
    source_table_name: str | None = None
    should_sync_default: bool = True
    label: str | None = None
    detected_primary_keys: list[str] | None = None
    rls_warning: str | None = None
    # Per-source default for the incremental overlap re-read window, applied at schema
    # creation when the caller doesn't set one. Sources whose recent rows get restated
    # upstream (e.g. Google Ads stats tables, which Google keeps revising for days) set
    # this so each incremental run re-reads a trailing window instead of freezing a day
    # at its first-imported value. Only consumed for schemas synced incrementally.
    default_incremental_lookback_seconds: int | None = None


def _select_incremental_field(incremental_fields: list[IncrementalField]) -> IncrementalField | None:
    """Pick the best incremental field for a table, preferring update-tracking columns."""
    candidates = [f for f in incremental_fields if f.get("field")]
    if not candidates:
        return None
    by_name = {f["field"].lower(): f for f in candidates}
    for name in _INCREMENTAL_FIELD_PREFERENCE:
        if name in by_name:
            return by_name[name]
    return candidates[0]


def build_default_schemas(source_schemas: list[SourceSchema]) -> list[dict]:
    """Build a default ``schemas`` payload for one-shot source creation.

    Enables every discovered table and picks a sync type per table: ``incremental`` when the
    source supports it and a tracking column exists (cheapest ongoing sync), else ``append``
    when supported, else ``full_refresh``. Never defaults to ``cdc`` — that needs Postgres
    prerequisites and explicit opt-in. Webhook-only tables start disabled because webhook
    registration needs the created source; the setup flow attempts it right after creation
    and, on success, switches webhook-capable tables to the webhook sync method. These
    polling defaults are also the fallback when that registration fails.
    """
    schemas: list[dict] = []
    for source_schema in source_schemas:
        if source_schema.webhook_only:
            schemas.append({"name": source_schema.name, "should_sync": False})
            continue

        chosen = _select_incremental_field(source_schema.incremental_fields)
        if source_schema.supports_incremental and chosen is not None:
            sync_type = "incremental"
        elif source_schema.supports_append and chosen is not None:
            sync_type = "append"
        else:
            sync_type = "full_refresh"

        entry: dict = {"name": source_schema.name, "should_sync": True, "sync_type": sync_type}
        if sync_type in ("incremental", "append") and chosen is not None:
            entry["incremental_field"] = chosen["field"]
            entry["incremental_field_type"] = str(chosen.get("field_type") or chosen.get("type"))
        if source_schema.detected_primary_keys:
            entry["primary_key_columns"] = source_schema.detected_primary_keys
        schemas.append(entry)
    return schemas
