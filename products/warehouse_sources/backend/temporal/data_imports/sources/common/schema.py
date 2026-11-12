from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

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

_TEMPORAL_FIELD_TYPES = {IncrementalFieldType.Timestamp, IncrementalFieldType.DateTime, IncrementalFieldType.Date}
_TYPE_RANK = {
    IncrementalFieldType.Timestamp: 2,
    IncrementalFieldType.DateTime: 2,
    IncrementalFieldType.Integer: 1,
    IncrementalFieldType.Numeric: 1,
    IncrementalFieldType.ObjectID: 1,
}

_TRACKS_UPDATES_NOTE = "Changes when a row is updated, so edited rows sync again."
_TRACKS_INSERTS_ONLY_NOTE = "Only marks new rows. Edits to existing rows don't sync."
_NOT_INDEXED_NOTE = "Not indexed, so each sync scans the whole table."
_NULLABLE_NOTE = "Can be empty. Rows where it's empty never sync."


@dataclass(frozen=False)
class SourceSchema:
    name: str
    supports_incremental: bool
    supports_append: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    row_count: int | None = None
    supports_webhooks: bool = False
    # True for resources whose only valid sync method is webhooks: either no API list endpoint
    # exists at all (e.g. Stripe `Discount`), or a non-webhook sync would destroy captured data
    # (e.g. Stripe `CustomerPaymentMethodHistory`, which seeds once from an API sweep and then
    # appends webhook events). The UI should hide non-webhook sync methods for these.
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
    # Source-specific keys merged into the persisted `sync_type_config.schema_metadata` at
    # schema creation, for sources that namespace tables by something other than a SQL
    # schema (e.g. GitHub stores {"source_repository", "source_endpoint"} per repo table).
    # The SQL sources' location keys above (source_catalog/source_schema/source_table_name)
    # stay separate: their persistence is gated on column-selection/direct-query paths.
    schema_metadata: dict[str, Any] | None = None
    # Keeps full refresh as the default sync type for a table that also supports incremental or
    # append. Sources set it when only a full refresh keeps the table equal to the origin, for
    # example file imports, where the other sync types keep the rows of files deleted upstream.
    prefers_full_refresh: bool = False


def _change_tracking_tier(field: IncrementalField) -> int:
    """2 when the field advances on updates, 1 when only on inserts, 0 when the name tells nothing."""
    name = field.get("field") or ""
    field_type = field.get("field_type") or field.get("type")
    # A numeric column counts only by an exact name, so an epoch `updated_at` matches and
    # `modified_by` (a user id) does not.
    if field_type in _TEMPORAL_FIELD_TYPES or name.lower() in _INCREMENTAL_FIELD_PREFERENCE:
        compact = "".join(ch for ch in name.lower() if ch.isalnum())
        if "updat" in compact or "modif" in compact:
            return 2
        if "creat" in compact or "insert" in compact:
            return 1
        return 0
    # A Mongo ObjectID and an integer `id` grow with each insert and never change on update.
    if field_type == IncrementalFieldType.ObjectID or name.lower() == "id":
        return 1
    return 0


def tracks_updates(field: IncrementalField) -> bool:
    return _change_tracking_tier(field) == 2


def name_is_silent(field: IncrementalField) -> bool:
    """True when the column name says neither "updated" nor "created", so only reading it can tell."""
    return _change_tracking_tier(field) == 0


def _rank_score(field: IncrementalField) -> int:
    """Higher is better. Each criterion outweighs all the criteria after it."""
    return (
        _change_tracking_tier(field) * 1000
        + (100 if field.get("is_indexed", True) else 0)
        + (0 if field.get("nullable", False) else 10)
        + _TYPE_RANK.get(field.get("field_type") or field["type"], 0)
    )


def _exact_name_preference(field: IncrementalField) -> int:
    name = (field.get("field") or "").lower()
    if name in _INCREMENTAL_FIELD_PREFERENCE:
        return _INCREMENTAL_FIELD_PREFERENCE.index(name)
    return len(_INCREMENTAL_FIELD_PREFERENCE)


def rank_incremental_fields(incremental_fields: list[IncrementalField]) -> list[IncrementalField]:
    """Sort candidate cursor fields best first, and mark the first one as recommended.

    For sources with arbitrary user columns. Several surfaces default to the first candidate
    (the schema picker response, the sync settings modal, the MCP), so it must be the field a
    data engineer would pick, not whichever column comes first in the table definition.

    The order of precedence: whether the field advances on updates, whether it is indexed,
    whether it is non-nullable, then its type. The name check goes first because a field that
    misses updates loses data without any error, while a full scan is only slow. Each field
    gets `notes` that explain the trade-offs to the user or to an agent.
    """

    # The synthetic Postgres xmin cursor only works as its own sync method, so it never leads.
    synthetic = [f for f in incremental_fields if (f.get("field_type") or f["type"]) == IncrementalFieldType.XID]
    real = [f for f in incremental_fields if (f.get("field_type") or f["type"]) != IncrementalFieldType.XID]

    ranked: list[IncrementalField] = []
    by_preferred_name = sorted(real, key=_exact_name_preference)
    for position, candidate in enumerate(sorted(by_preferred_name, key=_rank_score, reverse=True)):
        notes = []
        tier = _change_tracking_tier(candidate)
        if tier == 2:
            notes.append(_TRACKS_UPDATES_NOTE)
        elif tier == 1:
            notes.append(_TRACKS_INSERTS_ONLY_NOTE)
        if candidate.get("is_indexed") is False:
            notes.append(_NOT_INDEXED_NOTE)
        if candidate.get("nullable"):
            notes.append(_NULLABLE_NOTE)
        ranked.append({**candidate, "recommended": position == 0, "notes": notes})
    return ranked + synthetic


def _select_incremental_field(incremental_fields: list[IncrementalField]) -> IncrementalField | None:
    """Pick the best incremental field for a table, preferring update-tracking columns."""
    candidates = [f for f in incremental_fields if f.get("field")]
    if not candidates:
        return None
    recommended = next((f for f in candidates if f.get("recommended")), None)
    if recommended is not None:
        return recommended
    by_name = {f["field"].lower(): f for f in candidates}
    for name in _INCREMENTAL_FIELD_PREFERENCE:
        if name in by_name:
            return by_name[name]
    return candidates[0]


def build_default_sync_settings(source_schema: SourceSchema) -> dict[str, Any]:
    """Default sync settings for one discovered table.

    Picks ``incremental`` when the source supports it and a tracking column exists (cheapest
    ongoing sync), else ``append`` when supported, else ``full_refresh``. A table that sets
    ``prefers_full_refresh`` always gets ``full_refresh``. Never picks ``cdc``
    or ``webhook`` — both need prerequisites (Postgres setup, webhook registration) and
    explicit opt-in.
    """
    chosen = _select_incremental_field(source_schema.incremental_fields)
    if source_schema.prefers_full_refresh:
        sync_type = "full_refresh"
    elif source_schema.supports_incremental and chosen is not None:
        sync_type = "incremental"
    elif source_schema.supports_append and chosen is not None:
        sync_type = "append"
    else:
        sync_type = "full_refresh"

    settings: dict[str, Any] = {"sync_type": sync_type}
    if sync_type in ("incremental", "append") and chosen is not None:
        settings["incremental_field"] = chosen["field"]
        settings["incremental_field_type"] = str(chosen.get("field_type") or chosen.get("type"))
    if sync_type == "incremental" and source_schema.default_incremental_lookback_seconds is not None:
        settings["incremental_field_lookback_seconds"] = source_schema.default_incremental_lookback_seconds
    if source_schema.detected_primary_keys:
        settings["primary_key_columns"] = source_schema.detected_primary_keys
    return settings


def build_default_schemas(
    source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None] | None = None
) -> list[dict]:
    """Build a default ``schemas`` payload for one-shot source creation.

    Enables every discovered table the source marks as default-on, with each table's sync
    settings from ``build_default_sync_settings``. Webhook-only tables start disabled because
    webhook registration needs the created source; the setup flow attempts it right after
    creation and, on success, switches webhook-capable tables to the webhook sync method.
    These polling defaults are also the fallback when that registration fails. Tables with
    ``should_sync_default=False`` also start disabled: sources use it for tables whose sync
    needs grants beyond what source creation validated, and the schema picker already honors
    it, so one-shot setup must not force-enable what the picker would leave off.

    ``permission_errors`` maps table name to the reason its credentials can't read it (the same
    per-table probe the schema picker renders). A table with a reason starts disabled however it
    is otherwise defaulted: enabling it would queue a sync that can only ever 403.
    """
    denied = {name for name, reason in (permission_errors or {}).items() if reason}
    schemas: list[dict] = []
    for source_schema in source_schemas:
        if source_schema.webhook_only or not source_schema.should_sync_default or source_schema.name in denied:
            schemas.append({"name": source_schema.name, "should_sync": False})
            continue

        schemas.append({"name": source_schema.name, "should_sync": True, **build_default_sync_settings(source_schema)})
    return schemas


def incremental_field(
    field: str,
    field_type: IncrementalFieldType = IncrementalFieldType.DateTime,
    label: str | None = None,
) -> IncrementalField:
    """Build an ``IncrementalField`` for a settings.py endpoint catalog.

    Replaces the hand-written 4-key dict (``label``/``type``/``field``/``field_type``) that most
    sources repeat per endpoint, where ``type`` and ``field_type`` are almost always the same value
    and ``label`` defaults to the field name — a frequent copy-paste bug source.
    """
    return {"label": label or field, "type": field_type, "field": field, "field_type": field_type}


def build_endpoint_schemas(
    endpoints: Iterable[str],
    incremental_fields: Mapping[str, list[IncrementalField]],
    names: list[str] | None = None,
    *,
    append_only: Collection[str] = (),
    merge_only: Collection[str] = (),
    descriptions: Mapping[str, str] | None = None,
    should_sync_default: Mapping[str, bool] | None = None,
    supports_webhooks: Collection[str] = (),
    default_incremental_lookback_seconds: Mapping[str, int] | None = None,
) -> list[SourceSchema]:
    """Build the ``SourceSchema`` list for a static endpoint-catalog source's ``get_schemas``.

    Collapses the near-universal ``for endpoint in ENDPOINTS: SourceSchema(...)`` loop plus the
    identical ``names`` filter tail. An endpoint with incremental fields defaults to
    ``supports_incremental=True`` and ``supports_append=True`` (the dominant pattern). Overrides:

    - ``append_only``: endpoints that support append but not incremental merge.
    - ``merge_only``: endpoints that support incremental merge but not append.
    - ``descriptions`` / ``should_sync_default`` / ``supports_webhooks``: per-endpoint metadata.
    - ``default_incremental_lookback_seconds``: per-endpoint default overlap re-read window, for
      endpoints whose recent rows get restated upstream (see ``SourceSchema``'s field doc).

    ``names`` (the schema-picker filter) keeps only the requested endpoints when set.
    """
    descriptions = descriptions or {}
    should_sync_default = should_sync_default or {}
    default_incremental_lookback_seconds = default_incremental_lookback_seconds or {}
    schemas = []
    for name in endpoints:
        fields = incremental_fields.get(name) or []
        # An endpoint counts as incremental only when it actually has tracking fields; an empty
        # (or missing) list means full-refresh.
        has_incremental = bool(fields)
        schemas.append(
            SourceSchema(
                name=name,
                supports_incremental=has_incremental and name not in append_only,
                supports_append=has_incremental and name not in merge_only,
                incremental_fields=fields,
                description=descriptions.get(name),
                should_sync_default=should_sync_default.get(name, True),
                supports_webhooks=name in supports_webhooks,
                default_incremental_lookback_seconds=default_incremental_lookback_seconds.get(name),
            )
        )

    if names is not None:
        names_set = set(names)
        schemas = [s for s in schemas if s.name in names_set]

    return schemas


_ResourceSchema = TypeVar("_ResourceSchema")

# Marks a resource the running worker has no schema definition for. Matched by
# `import_data_sync` to classify the failure as retryable.
UNKNOWN_RESOURCE_PREFIX = "This table is not available on this worker yet:"


class UnknownResourceError(Exception):
    """The worker's resource catalog holds no schema for the table being synced."""


def schema_for_resource(schemas: Mapping[str, _ResourceSchema], resource_name: str) -> _ResourceSchema:
    """Look up a resource's schema definition, with a clear error when the worker doesn't know it.

    The web pods and the data-import workers deploy separately, so for up to about an hour after a
    new resource ships the schema picker offers a table the worker cannot resolve yet. A bare
    ``KeyError`` there reports as a bug and shows the customer a raw Python error; this named error
    is classified retryable instead, so the sync recovers once the rollout finishes.
    """
    try:
        return schemas[resource_name]
    except KeyError:
        raise UnknownResourceError(f"{UNKNOWN_RESOURCE_PREFIX} {resource_name}") from None
