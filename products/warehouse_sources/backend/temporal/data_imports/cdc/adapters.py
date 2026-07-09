"""Source-type adapters for CDC.

Each database engine needs its own adapter that knows how to:
- Create a stream reader (WAL / binlog / change stream)
- Open a management connection (for slot/publication lifecycle)
- Validate prerequisites (wal_level, permissions, PKs)
- Clean up resources (drop slot, drop publication)
- Check replication lag

Postgres (and Supabase, which is Postgres on the wire) are implemented. When adding
MySQL or another engine, create an adapter in ``sources/<engine>/cdc/adapter.py`` and
register it in ``_cdc_adapters`` below.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorInfo
    from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCStreamReader


CDCConfigT_co = TypeVar("CDCConfigT_co", bound=CDCConfig, covariant=True)


class CDCSourceAdapter(Protocol[CDCConfigT_co]):
    """Interface that each CDC-capable database engine must implement.

    Generic over the engine's concrete CDC config type so that ``parse_cdc_config``
    is typed precisely without forcing callers to do ``isinstance`` checks.
    """

    def create_reader(self, source: ExternalDataSource) -> CDCStreamReader: ...

    @contextmanager
    def management_connection(self, source: ExternalDataSource, connect_timeout: int = 15) -> Iterator[Any]: ...

    def validate_prerequisites(
        self,
        source: ExternalDataSource,
        management_mode: Literal["posthog", "self_managed"],
        tables: list[str],
        schema: str,
        slot_name: str | None,
        publication_name: str | None,
    ) -> list[str]: ...

    def drop_resources(self, conn: Any, slot_name: str, pub_name: str) -> None: ...

    def get_lag_bytes(self, conn: Any, slot_name: str) -> int | None: ...

    def get_retention_cap_mb(self, conn: Any) -> int | None:
        """Engine-enforced cap on retained change-stream backlog in MB (PG:
        max_slot_wal_keep_size). None when unlimited or unknown. Once the backlog
        crosses this cap the engine invalidates the slot itself, so safety nets
        must act below it."""
        ...

    def is_slot_invalidation_error(self, exc: BaseException) -> bool:
        """Whether the exception means the engine invalidated or dropped the
        change-stream resource (PG: replication slot lost to max_slot_wal_keep_size)
        such that it cannot be resumed and must be recreated."""
        ...

    def classify_error(self, exc: BaseException) -> CDCErrorInfo | None:
        """Interpret a single engine-specific exception as a CDC error category, or None
        when unrecognized (the caller falls back to the engine-agnostic default). Mirrors
        ``is_slot_invalidation_error``: keeps psycopg/engine specifics out of the shared layer."""
        ...

    def recreate_slot(self, source: ExternalDataSource, tables: list[str]) -> dict[str, Any]:
        """Drop and recreate the change-stream resource after invalidation, against the
        existing capture definition (recreating it when PostHog owns it). ``tables`` is
        the schema-qualified (``schema.table``) capture set used if the definition must be
        recreated. Returns ``cdc_*`` job_inputs updates (e.g. the new consistent point).
        Raises when recreation isn't possible (e.g. a customer-owned publication is
        missing)."""
        ...

    def parse_cdc_config(self, source: ExternalDataSource) -> CDCConfigT_co: ...

    def setup_resources(
        self,
        source: ExternalDataSource,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """Provision engine-side CDC resources for the source.

        Reads management mode, identifiers (slot/publication, binlog channel, …),
        and any engine-specific knobs from ``payload``. Returns either
        ``(resource_dict, None)`` where ``resource_dict`` contains the CDC
        identifiers + metadata to merge into ``source.job_inputs`` (already keyed
        with ``cdc_*`` prefixes), or ``({}, error_message)`` describing what
        failed. On failure the adapter best-effort rolls back partial state.
        """
        ...

    def cleanup_resources(self, source: ExternalDataSource) -> None:
        """Drop engine-side CDC resources owned by PostHog for the source.

        Best-effort: logs and continues on errors. Must NOT touch resources owned
        by the customer (e.g. self-managed publications). No-op when the source
        has no CDC config or no PostHog-owned resources to drop.
        """
        ...

    def get_status(self, source: ExternalDataSource) -> dict[str, Any]:
        """Live engine-side CDC health for the source, read from the source DB.

        Opens a short management connection and returns at minimum
        ``{"slot_exists": bool, "publication_exists": bool, "lag_bytes": int | None}``.
        Engines may add extra fields. Raises on connection failure — the caller
        surfaces that as a 400 / unreachable state.
        """
        ...

    def add_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        """Best-effort include a table in the change-capture set (PG: ALTER PUBLICATION ADD TABLE).
        No-op when PostHog doesn't own the capture definition (e.g. self-managed)."""
        ...

    def remove_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        """Best-effort exclude a table from the change-capture set. Inverse of ``add_table``."""
        ...


def _cdc_adapters() -> dict[ExternalDataSourceType, CDCSourceAdapter[CDCConfig]]:
    """Registry of CDC adapters keyed by source type. Adding a new CDC-capable source
    is a single entry here — everything else derives from this map."""
    # Supabase is Postgres on the wire, so it reuses the Postgres adapter verbatim.
    postgres_adapter = PostgresCDCAdapter()
    return {
        ExternalDataSourceType.POSTGRES: postgres_adapter,
        ExternalDataSourceType.SUPABASE: postgres_adapter,
    }


def get_cdc_adapter(source: ExternalDataSource) -> CDCSourceAdapter[CDCConfig]:
    """Return the CDC adapter for the given source's type.

    Raises ValueError if the source type doesn't support CDC.
    """
    try:
        source_type = ExternalDataSourceType(source.source_type)
    except ValueError as e:
        raise ValueError(f"CDC is not supported for source type: {source.source_type}") from e

    adapter = _cdc_adapters().get(source_type)
    if adapter is None:
        raise ValueError(f"CDC is not supported for source type: {source.source_type}")
    return adapter


def cdc_supported_source_types() -> list[ExternalDataSourceType]:
    """Source types that support CDC. Use for queries (e.g. ``source_type__in=...``)."""
    return list(_cdc_adapters().keys())


def source_type_supports_cdc(source_type: ExternalDataSourceType | str | None) -> bool:
    """Whether the given source type (enum or raw string) supports CDC."""
    if source_type is None:
        return False
    try:
        resolved = ExternalDataSourceType(source_type)
    except ValueError:
        return False
    return resolved in _cdc_adapters()
