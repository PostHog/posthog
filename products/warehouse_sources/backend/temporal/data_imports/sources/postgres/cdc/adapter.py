"""Postgres CDC adapter using pgoutput logical replication."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import cdc_error_info
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.errors import (
    classify_postgres_cdc_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.slot_manager import (
    add_table_to_publication,
    cdc_pg_connection,
    create_publication,
    create_slot,
    create_slot_and_publication,
    drop_publication,
    drop_slot,
    drop_slot_and_publication,
    get_max_slot_wal_keep_size_mb,
    get_publication_tables,
    get_slot_lag_bytes,
    is_slot_invalidation_error,
    publication_exists,
    remove_table_from_publication,
    slot_exists,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import source_requires_ssl

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorInfo
    from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCStreamReader

logger = logging.getLogger(__name__)


def _split_qualified_table(qualified: str, default_schema: str) -> tuple[str, str]:
    """Split a ``schema.table`` name into ``(schema, table)``, falling back to
    ``default_schema`` for a bare table name."""
    if "." in qualified:
        table_schema, table_name = qualified.split(".", 1)
        return table_schema, table_name
    return default_schema, qualified


class PostgresCDCAdapter:
    def parse_cdc_config(self, source: ExternalDataSource) -> PostgresCDCConfig:
        return PostgresCDCConfig.from_source(source)

    def create_reader(self, source: ExternalDataSource) -> CDCStreamReader:
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader import (
            PgCDCConnectionParams,
            PgCDCStreamReader,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        inputs = source.job_inputs or {}
        cdc_config = self.parse_cdc_config(source)
        # Two-arg form honors the SSH-tunnel `require_tls` opt-out, matching the management
        # path (slot_manager.cdc_pg_connection) so a tunnelled source that opted out of TLS
        # is not force-upgraded on the data path.
        config = PostgresSource().parse_config(inputs)
        params = PgCDCConnectionParams(
            host=inputs.get("host", ""),
            port=int(inputs.get("port", 5432)),
            database=inputs.get("database", ""),
            user=inputs.get("user", ""),
            password=inputs.get("password", ""),
            require_ssl=source_requires_ssl(source, config),
            slot_name=cdc_config.slot_name,
            publication_name=cdc_config.publication_name,
        )
        return PgCDCStreamReader(params, source=source)

    @contextmanager
    def management_connection(self, source: ExternalDataSource, connect_timeout: int = 15) -> Iterator[Any]:
        with cdc_pg_connection(source, connect_timeout=connect_timeout) as conn:
            yield conn

    def validate_prerequisites(
        self,
        source: ExternalDataSource,
        management_mode: Literal["posthog", "self_managed"],
        tables: list[str],
        schema: str,
        slot_name: str | None,
        publication_name: str | None,
    ) -> list[str]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.prerequisite_validator import (
            validate_cdc_prerequisites,
        )

        with self.management_connection(source) as conn:
            return validate_cdc_prerequisites(
                conn=conn,
                management_mode=management_mode,
                tables=tables,
                schema=schema,
                slot_name=slot_name,
                publication_name=publication_name,
            )

    def drop_resources(self, conn: Any, slot_name: str, pub_name: str) -> None:
        drop_slot_and_publication(conn, slot_name, pub_name)

    def get_lag_bytes(self, conn: Any, slot_name: str) -> int | None:
        return get_slot_lag_bytes(conn, slot_name)

    def get_retention_cap_mb(self, conn: Any) -> int | None:
        return get_max_slot_wal_keep_size_mb(conn)

    def is_slot_invalidation_error(self, exc: BaseException) -> bool:
        return is_slot_invalidation_error(exc)

    def classify_error(self, exc: BaseException) -> CDCErrorInfo | None:
        category = classify_postgres_cdc_error(exc)
        return cdc_error_info(category) if category is not None else None

    def recreate_slot(self, source: ExternalDataSource, tables: list[str]) -> dict[str, Any]:
        """Drop the dead replication slot and create a fresh one against the existing
        publication, recreating the publication first when PostHog owns it and it's gone.

        ``tables`` are schema-qualified ``schema.table`` names — a publication can span
        schemas, so each table keeps its own schema rather than inheriting the source's
        default. Returns the job_inputs updates (new consistent point). Raises when
        recreation isn't possible (no slot configured, customer-owned publication missing).
        """
        cdc_config = self.parse_cdc_config(source)
        if not cdc_config.slot_name:
            raise RuntimeError("Cannot recreate CDC replication slot: no slot name configured for this source")

        default_schema = self._resolve_schema(source)
        with cdc_pg_connection(source) as conn:
            drop_slot(conn, cdc_config.slot_name)
            if cdc_config.publication_name and not publication_exists(conn, cdc_config.publication_name):
                if cdc_config.management_mode != "posthog":
                    raise RuntimeError(
                        f"Publication '{cdc_config.publication_name}' does not exist on the source database. "
                        "Recreate it (see the CDC setup instructions), then resync the source."
                    )
                consistent_point = create_slot_and_publication(
                    conn,
                    cdc_config.slot_name,
                    cdc_config.publication_name,
                    tables=[_split_qualified_table(t, default_schema) for t in tables],
                )
            else:
                consistent_point = create_slot(conn, cdc_config.slot_name)

        return {"cdc_consistent_point": consistent_point}

    def setup_resources(
        self,
        source: ExternalDataSource,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        """Create the logical replication slot (and the publication, for PostHog-managed
        mode) on the source database. Returns the cdc_* fields the caller should merge
        into ``source.job_inputs``, or an error string. Cleans up partial state on failure.
        """
        management_mode: Literal["posthog", "self_managed"] = (
            "self_managed" if payload.get("cdc_management_mode") == "self_managed" else "posthog"
        )
        default_slot_name = f"posthog_{source.id.hex[:12]}"
        slot_name = payload.get("cdc_slot_name") or default_slot_name
        default_pub_name = "posthog_pub" if management_mode == "self_managed" else f"posthog_pub_{source.id.hex[:12]}"
        pub_name = payload.get("cdc_publication_name") or default_pub_name
        uses_default_posthog_resources = (
            management_mode == "posthog" and slot_name == default_slot_name and pub_name == default_pub_name
        )

        resource_fields: dict[str, Any] = {
            "cdc_management_mode": management_mode,
            "cdc_slot_name": slot_name,
            "cdc_publication_name": pub_name,
        }

        if management_mode == "posthog":
            created_publication = False
            created_slot = False
            try:
                with cdc_pg_connection(source) as conn:
                    slot_present = slot_exists(conn, slot_name)
                    publication_present = publication_exists(conn, pub_name)
                    # Default names are source-id derived, so pre-existing resources are recoverable
                    # PostHog state from this source. Custom-name conflicts still belong to the user/DBA.
                    if uses_default_posthog_resources and slot_present:
                        if not publication_present:
                            create_publication(conn, pub_name, tables=[])
                        logger.info("Adopted existing CDC slot/publication for source_id=%s", source.id)
                        return resource_fields, None
                    if slot_present:
                        return {}, f"A replication slot named '{slot_name}' already exists on your database."
                    if uses_default_posthog_resources and publication_present:
                        resource_fields["cdc_consistent_point"] = create_slot(conn, slot_name)
                        logger.info("Adopted existing CDC publication for source_id=%s", source.id)
                        return resource_fields, None
                    if publication_present:
                        return {}, f"A publication named '{pub_name}' already exists on your database."
                    create_publication(conn, pub_name, tables=[])
                    created_publication = True
                    resource_fields["cdc_consistent_point"] = create_slot(conn, slot_name)
                    created_slot = True
            except Exception as e:
                logger.exception("Failed to create CDC slot and publication: %s", e)
                try:
                    with cdc_pg_connection(source, connect_timeout=10) as conn:
                        if created_slot and created_publication:
                            drop_slot_and_publication(conn, slot_name, pub_name)
                        elif created_slot:
                            drop_slot(conn, slot_name)
                        elif created_publication:
                            drop_publication(conn, pub_name)
                except Exception as rollback_error:
                    logger.exception("Failed to roll back partial CDC slot/publication: %s", rollback_error)
                return {}, f"Failed to create replication slot: {e}"
            return resource_fields, None

        # self_managed: the publication is customer-owned; PostHog only creates the slot.
        try:
            with cdc_pg_connection(source) as conn:
                if slot_exists(conn, slot_name):
                    return {}, f"A replication slot named '{slot_name}' already exists on your database."
                if not publication_exists(conn, pub_name):
                    return (
                        {},
                        (
                            f"Publication '{pub_name}' does not exist. Run the CREATE PUBLICATION "
                            f"statement we showed you, then retry."
                        ),
                    )
                resource_fields["cdc_consistent_point"] = create_slot(conn, slot_name)
        except Exception as e:
            logger.exception("Failed to set up self-managed CDC slot: %s", e)
            # Slot only — the publication is customer-owned.
            try:
                with cdc_pg_connection(source, connect_timeout=10) as conn:
                    drop_slot(conn, slot_name)
            except Exception as rollback_error:
                logger.exception("Failed to roll back partial self-managed CDC slot: %s", rollback_error)
            return {}, f"Failed to create replication slot: {e}"
        return resource_fields, None

    def cleanup_resources(self, source: ExternalDataSource) -> None:
        """Drop the PostHog-managed replication slot (and publication, for PostHog-managed
        mode) on the source database. Self-managed mode drops only the slot — the
        publication is customer-owned. Best-effort: logs and continues on errors.
        """
        cdc_config = self.parse_cdc_config(source)
        if not cdc_config.enabled or not cdc_config.slot_name:
            return
        try:
            with cdc_pg_connection(source, connect_timeout=10) as conn:
                if cdc_config.management_mode == "self_managed":
                    drop_slot(conn, cdc_config.slot_name)
                elif cdc_config.publication_name:
                    drop_slot_and_publication(conn, cdc_config.slot_name, cdc_config.publication_name)
        except Exception:
            logger.exception(
                "Failed to drop CDC slot/publication on source DB (best-effort), source_id=%s slot=%s",
                source.id,
                cdc_config.slot_name,
            )

    def get_status(self, source: ExternalDataSource) -> dict[str, Any]:
        """Read live slot/publication existence and WAL lag from the source DB."""
        cdc_config = self.parse_cdc_config(source)
        with cdc_pg_connection(source, connect_timeout=10) as conn:
            slot_present = slot_exists(conn, cdc_config.slot_name) if cdc_config.slot_name else False
            pub_present = (
                publication_exists(conn, cdc_config.publication_name) if cdc_config.publication_name else False
            )
            lag_bytes = get_slot_lag_bytes(conn, cdc_config.slot_name) if cdc_config.slot_name else None
            published_tables = (
                get_publication_tables(conn, cdc_config.publication_name)
                if cdc_config.publication_name and pub_present
                else []
            )
        return {
            "slot_exists": slot_present,
            "publication_exists": pub_present,
            "lag_bytes": lag_bytes,
            "published_tables": published_tables,
        }

    def add_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        """Best-effort ALTER PUBLICATION ADD TABLE. No-op for self-managed / no publication."""
        self._alter_publication_membership(source, schema, table, add=True)

    def remove_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        """Best-effort ALTER PUBLICATION DROP TABLE. No-op for self-managed / no publication."""
        self._alter_publication_membership(source, schema, table, add=False)

    def _alter_publication_membership(self, source: ExternalDataSource, schema: str, table: str, add: bool) -> None:
        cdc_config = self.parse_cdc_config(source)
        # PostHog only manages the publication in posthog-managed mode.
        if cdc_config.management_mode != "posthog" or not cdc_config.publication_name:
            return
        try:
            with cdc_pg_connection(source) as conn:
                if add:
                    add_table_to_publication(conn, cdc_config.publication_name, schema, table)
                else:
                    remove_table_from_publication(conn, cdc_config.publication_name, schema, table)
        except Exception:
            logger.exception(
                "Failed to %s table %s.%s %s CDC publication '%s' (best-effort), source_id=%s",
                "add" if add else "remove",
                schema,
                table,
                "to" if add else "from",
                cdc_config.publication_name,
                source.id,
            )

    def _resolve_schema(self, source: ExternalDataSource) -> str:
        raw = (source.job_inputs or {}).get("schema")
        return raw.strip() if isinstance(raw, str) and raw.strip() else "public"
