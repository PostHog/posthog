from datetime import date, datetime, time
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.warehouse_object_reads import SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE, ReadKind
from posthog.dataclasses import frozen

from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionSubjectKind

INSERT_READ_SQL = f"""
INSERT INTO {SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE}
SELECT
    %(team_id)s, %(day)s, %(read_kind)s, %(subject_kind)s, %(subject_id)s, %(workflow_id)s,
    %(lc_kind)s, %(lc_product)s, %(lc_feature)s, %(lc_access_method)s, %(source)s, %(scene)s,
    %(user_id)s > 0, %(read_alone)s,
    initializeAggregation('uniqState', %(request_id)s),
    initializeAggregation('uniqState', toInt64(%(user_id)s)),
    1,
    toUInt64(%(duration_ms)s),
    toUInt64(%(read_bytes)s),
    initializeAggregation('quantilesState(0.5, 0.9)', toUInt64(%(duration_ms)s)),
    initializeAggregation('quantilesState(0.5, 0.9)', toUInt64(%(read_bytes)s)),
    toDateTime(%(event_time)s)
"""


@frozen
class RollupRead:
    subject_id: UUID
    day: date
    request_id: str
    user_id: int = 1
    subject_kind: WarehouseSuggestionSubjectKind = WarehouseSuggestionSubjectKind.SAVED_QUERY
    read_kind: ReadKind = ReadKind.READ
    workflow_id: str = ""
    lc_kind: str = ""
    lc_product: str = ""
    lc_feature: str = ""
    lc_access_method: str = ""
    source: str = ""
    scene: str = "SQLEditor"
    read_alone: bool = False
    duration_ms: int = 1000
    read_bytes: int = 1000


def seed_reads(team_id: int, reads: list[RollupRead]) -> None:
    for read in reads:
        sync_execute(
            INSERT_READ_SQL,
            {
                "team_id": team_id,
                "day": read.day,
                "read_kind": read.read_kind.value,
                "subject_kind": read.subject_kind.value,
                "subject_id": str(read.subject_id),
                "workflow_id": read.workflow_id,
                "lc_kind": read.lc_kind,
                "lc_product": read.lc_product,
                "lc_feature": read.lc_feature,
                "lc_access_method": read.lc_access_method,
                "source": read.source,
                "scene": read.scene,
                "user_id": read.user_id,
                "read_alone": read.read_alone,
                "request_id": read.request_id,
                "duration_ms": read.duration_ms,
                "read_bytes": read.read_bytes,
                "event_time": datetime.combine(read.day, time(hour=12)),
            },
        )
