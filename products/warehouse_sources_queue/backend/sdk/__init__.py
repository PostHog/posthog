"""Public surface of the warehouse sources queue engine.

Workloads import from here. The modules under ``core/`` are internal: their
SQL builders, sweep mechanics, and lease internals can change without notice.
Adapters that implement ``BatchConsumerAdapter`` may import ``core`` directly.
"""

from products.warehouse_sources_queue.backend.core.batch_consumer import (
    MAX_ATTEMPTS,
    RECOVERY_GRACE_SECONDS,
    BatchConsumer,
    BatchConsumerAdapter,
    BatchConsumerConfig,
    OwnershipLostError,
    PermanentBatchApplyError,
)
from products.warehouse_sources_queue.backend.core.generic_jobs import Job, JobsTable
from products.warehouse_sources_queue.backend.core.health import HealthState, start_health_server
from products.warehouse_sources_queue.backend.core.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    PARTITION_PRUNING_INTERVAL,
    STATUS_TABLE,
    TAKEOVER_STALE_THRESHOLD_SECONDS,
    ActiveRunRef,
    BatchQueue,
    PendingBatch,
    RunActivitySummary,
    latest_status_lateral,
)
from products.warehouse_sources_queue.backend.core.metrics import (
    DELTA_CONSUMER_METRICS,
    ConsumerMetrics,
    make_consumer_metrics,
)
from products.warehouse_sources_queue.backend.core.scheduler_state import (
    DecisionRecord,
    DueSchedule,
    SchedulerStateTable,
)
from products.warehouse_sources_queue.backend.sdk.jobs import (
    Fail,
    FollowerSpec,
    GenericJobAdapter,
    JobConsumer,
    JobContext,
    JobHandler,
    Outcome,
    Retry,
    Success,
)

__all__ = [
    "BATCH_TABLE",
    "DELTA_CONSUMER_METRICS",
    "LEASE_TABLE",
    "MAX_ATTEMPTS",
    "PARTITION_PRUNING_INTERVAL",
    "RECOVERY_GRACE_SECONDS",
    "STATUS_TABLE",
    "TAKEOVER_STALE_THRESHOLD_SECONDS",
    "ActiveRunRef",
    "BatchConsumer",
    "BatchConsumerAdapter",
    "BatchConsumerConfig",
    "BatchQueue",
    "ConsumerMetrics",
    "DecisionRecord",
    "DueSchedule",
    "Fail",
    "FollowerSpec",
    "GenericJobAdapter",
    "HealthState",
    "Job",
    "JobConsumer",
    "JobContext",
    "JobHandler",
    "JobsTable",
    "Outcome",
    "OwnershipLostError",
    "PendingBatch",
    "PermanentBatchApplyError",
    "Retry",
    "RunActivitySummary",
    "SchedulerStateTable",
    "Success",
    "latest_status_lateral",
    "make_consumer_metrics",
    "start_health_server",
]
