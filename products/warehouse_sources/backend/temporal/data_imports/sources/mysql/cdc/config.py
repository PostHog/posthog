"""Typed MySQL CDC config parsed from ``ExternalDataSource.job_inputs``.

MySQL keeps no replication slot for its readers, so PostHog holds the stream state itself: the server it
reads, the replica id it reads with, and the position it has read up to.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from posthog.utils import str_to_bool

from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore, UnreadableSourceInputsError
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import (
    CDCConfig,
    CDCJobInputsUnreadableError,
    decode_job_inputs,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

DEFAULT_LAG_WARNING_THRESHOLD_MB = 512
DEFAULT_LAG_CRITICAL_THRESHOLD_MB = 2048

POSITION_KEY = "cdc_binlog_position"
SERVER_UUID_KEY = "cdc_server_uuid"
SERVER_ID_KEY = "cdc_server_id"


@dataclasses.dataclass(frozen=True, kw_only=True)
class MySQLCDCConfig(CDCConfig):
    # `@@server_uuid` of the server whose binlog the position belongs to. Another server means a failover.
    server_uuid: str
    server_id: int | None
    position: str | None

    @property
    def stream_name(self) -> str:
        return self.server_uuid

    @property
    def stream_resources_configured(self) -> bool:
        # The stream lives in these fields, and there is nothing on the server to drop.
        return bool(self.server_uuid and self.position)

    @classmethod
    def from_dict(cls, job_inputs: Mapping[str, Any] | str | None) -> MySQLCDCConfig:
        ji = decode_job_inputs(job_inputs)
        server_id = ji.get(SERVER_ID_KEY)
        return cls(
            enabled=str_to_bool(ji.get("cdc_enabled", False)),
            # Every binlog reader is a client of the server, so there is nothing for a DBA to own.
            management_mode="posthog",
            lag_warning_threshold_mb=int(ji.get("cdc_lag_warning_threshold_mb", DEFAULT_LAG_WARNING_THRESHOLD_MB)),
            lag_critical_threshold_mb=int(ji.get("cdc_lag_critical_threshold_mb", DEFAULT_LAG_CRITICAL_THRESHOLD_MB)),
            auto_drop_slot=False,
            server_uuid=ji.get(SERVER_UUID_KEY) or "",
            server_id=int(server_id) if server_id not in (None, "") else None,
            position=ji.get(POSITION_KEY) or None,
        )

    @classmethod
    def from_source(cls, source: ExternalDataSource) -> MySQLCDCConfig:
        try:
            inputs = SourceInputsStore.load_settings(source)
        except UnreadableSourceInputsError as e:
            raise CDCJobInputsUnreadableError(str(e)) from e
        return cls.from_dict(inputs)
