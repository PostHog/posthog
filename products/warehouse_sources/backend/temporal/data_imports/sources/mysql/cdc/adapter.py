"""MySQL CDC adapter over the row-based binary log.

MySQL keeps no slot for its readers: it purges binlog files on a timer whether or not anyone has read
them. PostHog therefore holds the stream itself (the server, the replica id and the position, all in
``job_inputs``), and a stream is lost when the server no longer has the file of that position.
"""

from __future__ import annotations

import logging
import dataclasses
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

import pymysql

from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import cdc_error_info
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCLag
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import binlog
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.config import (
    POSITION_KEY,
    SERVER_ID_KEY,
    SERVER_UUID_KEY,
    MySQLCDCConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.errors import (
    classify_mysql_cdc_error,
    customer_fixable_error_message,
    is_connection_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition
from products.warehouse_sources.backend.types import CDCEngine

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorInfo
    from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCStreamReader

logger = logging.getLogger(__name__)

# Management reads are short. A server that stops answering must not hold a status request or the lag sweep
# for the five minutes a snapshot read waits.
MANAGEMENT_READ_TIMEOUT_SECONDS = 30


@dataclasses.dataclass(frozen=True)
class MySQLManagementConnection:
    """A management connection, with the stream the source stores (None before it has one)."""

    conn: pymysql.Connection
    stream: BinlogPosition | None

    @property
    def epoch(self) -> int:
        return self.stream.epoch if self.stream is not None else 0


class MySQLCDCAdapter:
    engine = CDCEngine.MYSQL

    def parse_cdc_config(self, source: ExternalDataSource) -> MySQLCDCConfig:
        return MySQLCDCConfig.from_source(source)

    def position_to_seq(self, position_serialized: str) -> int:
        return BinlogPosition.deserialize(position_serialized).seq

    def create_reader(self, source: ExternalDataSource) -> CDCStreamReader:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.stream_reader import (
            MySQLCDCStreamReader,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource

        source_impl = MySQLSource()
        config = source_impl.parse_config(SourceInputsStore.load(source))
        return MySQLCDCStreamReader(source, config, self.parse_cdc_config(source), source_impl.get_implementation)

    def current_position(self, conn: MySQLManagementConnection) -> str:
        base = conn.stream.base if conn.stream is not None else None
        return binlog.visible_position(conn.conn, conn.epoch, base).serialize()

    @contextmanager
    def management_connection(
        self, source: ExternalDataSource, connect_timeout: int = 15
    ) -> Iterator[MySQLManagementConnection]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource

        source_impl = MySQLSource()
        config = source_impl.parse_config(SourceInputsStore.load(source))
        stored = self.parse_cdc_config(source).position
        stream = BinlogPosition.deserialize(stored) if stored else None
        with source_impl.get_implementation.connect(
            config, read_timeout=MANAGEMENT_READ_TIMEOUT_SECONDS, team_id=source.team_id, autocommit=True
        ) as conn:
            yield MySQLManagementConnection(conn=conn, stream=stream)

    def validate_prerequisites(
        self,
        source: ExternalDataSource,
        management_mode: Literal["posthog", "self_managed"],
        tables: list[str],
        schema: str,
        setup: Mapping[str, Any],
    ) -> list[str]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.prerequisite_validator import (
            validate_cdc_prerequisites,
        )

        with self.management_connection(source) as management:
            return validate_cdc_prerequisites(management.conn, tables=tables, database=schema or None)

    def drop_stream(self, conn: MySQLManagementConnection, source: ExternalDataSource) -> None:
        # Nothing on the server belongs to PostHog: the position lives in `job_inputs`.
        return None

    def stream_exists(self, conn: MySQLManagementConnection, source: ExternalDataSource) -> bool:
        config = self.parse_cdc_config(source)
        if not config.position:
            return False
        try:
            binlog.require_readable(conn.conn, BinlogPosition.deserialize(config.position), config.server_uuid)
        except binlog.BinlogStreamLostError:
            return False
        return True

    def get_lag(self, conn: MySQLManagementConnection, source: ExternalDataSource) -> CDCLag | None:
        config = self.parse_cdc_config(source)
        if not config.position:
            return None
        behind = binlog.lag_bytes(conn.conn, BinlogPosition.deserialize(config.position))
        if behind is None:
            return None
        # MySQL purges by age, not by size, so there is no byte cap to report.
        return CDCLag(behind_bytes=behind, retention_cap_mb=None)

    def is_stream_lost_error(self, exc: BaseException) -> bool:
        return binlog.is_stream_lost_error(exc)

    def is_connection_error(self, exc: BaseException) -> bool:
        return is_connection_error(exc)

    def customer_fixable_error_message(self, exc: BaseException) -> str | None:
        return customer_fixable_error_message(exc)

    def classify_error(self, exc: BaseException) -> CDCErrorInfo | None:
        category = classify_mysql_cdc_error(exc)
        return cdc_error_info(category) if category is not None else None

    def recreate_stream(self, source: ExternalDataSource, tables: list[str]) -> dict[str, Any]:
        """Start a new stream at the end of the binlog of whichever server the source reaches now.

        The epoch moves on, so every position of the new stream sorts after the old one's, even when a
        failover put the source on a server whose binlog files have lower numbers.
        """
        with self.management_connection(source) as management:
            position = binlog.visible_position(management.conn, management.epoch + 1)
            return {POSITION_KEY: position.serialize(), SERVER_UUID_KEY: binlog.server_uuid(management.conn)}

    def setup_resources(self, source: ExternalDataSource, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Pin the stream to the server the source reaches, starting at the current end of its binlog."""
        try:
            with self.management_connection(source) as management:
                conn = management.conn
                fields = {
                    "cdc_management_mode": "posthog",
                    SERVER_ID_KEY: binlog.unused_server_id(conn),
                    SERVER_UUID_KEY: binlog.server_uuid(conn),
                    POSITION_KEY: binlog.visible_position(conn, epoch=0).serialize(),
                }
        except Exception as e:
            logger.exception("Failed to start the MySQL binlog stream: %s", e)
            return {}, customer_fixable_error_message(e) or f"Could not read the binary log position: {e}"
        return fields, None

    def cleanup_resources(self, source: ExternalDataSource) -> None:
        return None

    def get_status(self, source: ExternalDataSource) -> dict[str, Any]:
        config = self.parse_cdc_config(source)
        position = BinlogPosition.deserialize(config.position) if config.position else None
        with self.management_connection(source, connect_timeout=10) as management:
            current_uuid = binlog.server_uuid(management.conn)
            files = {file.name for file in binlog.binary_logs(management.conn)}
            lag = binlog.lag_bytes(management.conn, position) if position else None
        return {
            "server_uuid": config.server_uuid,
            "position": config.position,
            "same_server": not config.server_uuid or current_uuid == config.server_uuid,
            "binlog_file_exists": position is not None and position.file in files,
            "lag_bytes": lag,
        }

    def capture_resources_present(self, status: Mapping[str, Any]) -> bool:
        return status.get("same_server") is not False and status.get("binlog_file_exists") is not False

    def add_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        # The binlog carries every table, so there is no capture set to change.
        return None

    def remove_table(self, source: ExternalDataSource, schema: str, table: str) -> None:
        return None

    def manages_capture_set(self, source: ExternalDataSource) -> bool:
        return False
