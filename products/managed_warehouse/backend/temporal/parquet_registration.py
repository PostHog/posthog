from __future__ import annotations

import threading
from collections.abc import Sequence

import psycopg
from psycopg import sql
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen


@frozen
class ParquetRegistration:
    schema_name: str
    table_name: str
    shadow_name: str
    previous_name: str
    parquet_glob: str

    @staticmethod
    def check_cancellation(cancel_requested: threading.Event | None) -> None:
        if cancel_requested is not None and cancel_requested.is_set():
            raise TimeoutError("Duckgres registration reached the Temporal activity deadline")

    def prepare(
        self,
        conn: psycopg.Connection,
        path_batches: Sequence[Sequence[str]],
        partition_columns: Sequence[str],
        cancel_requested: threading.Event | None = None,
    ) -> None:
        self.check_cancellation(cancel_requested)
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema_name)))
        self.check_cancellation(cancel_requested)
        conn.execute(
            sql.SQL(
                "CREATE TABLE {}.{} AS SELECT * FROM "
                "read_parquet({}, union_by_name=true, hive_partitioning=true) LIMIT 0"
            ).format(sql.Identifier(self.schema_name), sql.Identifier(self.shadow_name), sql.Literal(self.parquet_glob))
        )
        if partition_columns:
            self.check_cancellation(cancel_requested)
            conn.execute(
                sql.SQL("ALTER TABLE {}.{} SET PARTITIONED BY ({})").format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier(self.shadow_name),
                    sql.SQL(", ").join(sql.Identifier(column) for column in partition_columns),
                )
            )
        for paths in path_batches:
            self.check_cancellation(cancel_requested)
            conn.execute(
                sql.SQL(
                    "CALL ducklake_add_data_files({}, {}, [{}], schema => {}, "
                    "allow_missing => true, hive_partitioning => true)"
                ).format(
                    sql.Literal("ducklake"),
                    sql.Literal(self.shadow_name),
                    sql.SQL(", ").join(sql.Literal(path) for path in paths),
                    sql.Literal(self.schema_name),
                )
            )

    def verify(self, conn: psycopg.Connection, cancel_requested: threading.Event | None = None) -> int:
        self.check_cancellation(cancel_requested)
        source_row = conn.execute(
            sql.SQL("SELECT count(*) FROM read_parquet({}, union_by_name=true, hive_partitioning=true)").format(
                sql.Literal(self.parquet_glob)
            )
        ).fetchone()
        self.check_cancellation(cancel_requested)
        registered_row = conn.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(self.schema_name), sql.Identifier(self.shadow_name)
            )
        ).fetchone()
        source_count = int(source_row[0]) if source_row else 0
        registered_count = int(registered_row[0]) if registered_row else 0
        if source_count != registered_count:
            raise ApplicationError(
                f"DuckLake prepared-file registration row count mismatch: source={source_count}, registered={registered_count}",
                non_retryable=True,
            )
        return registered_count

    def publish(self, conn: psycopg.Connection, cancel_requested: threading.Event | None = None) -> None:
        self.check_cancellation(cancel_requested)
        conn.execute(
            sql.SQL("ALTER TABLE IF EXISTS {}.{} RENAME TO {}").format(
                sql.Identifier(self.schema_name), sql.Identifier(self.table_name), sql.Identifier(self.previous_name)
            )
        )
        self.check_cancellation(cancel_requested)
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                sql.Identifier(self.schema_name), sql.Identifier(self.shadow_name), sql.Identifier(self.table_name)
            )
        )
