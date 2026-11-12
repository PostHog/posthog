"""Facade re-exports for the experiments Temporal wiring.

Core registers these with the Temporal worker (``start_temporal_worker``), the schedule bootstrap
(``posthog/temporal/schedule.py``) and the worker metrics setup (``posthog/temporal/common/worker.py``).
They cross the boundary as objects, not data, so they live in their own facade submodule and keep the
``temporalio`` imports off the ``facade/api.py`` path.

The daily timeseries workflows register on a different task queue than the recalculation workflows,
so ``TIMESERIES_WORKFLOWS`` and ``TIMESERIES_ACTIVITIES`` stay separate from ``WORKFLOWS`` and ``ACTIVITIES``.
"""

from products.experiments.backend.temporal import (
    ACTIVITIES,
    EXPERIMENT_CANARY_ACTIVITIES,
    EXPERIMENT_CANARY_WORKFLOWS,
    EXPERIMENT_ENROLLMENT_CENSUS_ACTIVITIES,
    EXPERIMENT_ENROLLMENT_CENSUS_WORKFLOWS,
    EXPERIMENT_RECALCULATION_ACTIVITY_QUEUE_ACTIVITIES,
    EXPERIMENT_SCHEDULED_RECALCULATION_ACTIVITIES,
    EXPERIMENT_SCHEDULED_RECALCULATION_WORKFLOWS,
    WORKFLOWS,
)
from products.experiments.backend.temporal.recalculation_metrics import (
    EXPERIMENT_METRICS_RECALCULATION_ATTEMPT_HISTOGRAM_BUCKETS,
    EXPERIMENT_METRICS_RECALCULATION_ATTEMPT_HISTOGRAM_METRICS,
    EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_BUCKETS,
    EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS,
    EXPERIMENT_METRICS_RECALCULATION_SCHEDULE_TO_START_HISTOGRAM_BUCKETS,
    EXPERIMENT_METRICS_RECALCULATION_SCHEDULE_TO_START_HISTOGRAM_METRICS,
    ExperimentsRecalculationMetricsInterceptor,
)
from products.experiments.backend.temporal.schedule import (
    create_experiment_precompute_canary_schedule,
    create_experiment_precompute_enrollment_census_schedule,
    create_experiment_scheduled_recalculation_schedules,
)
from products.experiments.backend.temporal.timeseries import (
    ACTIVITIES as TIMESERIES_ACTIVITIES,
    WORKFLOWS as TIMESERIES_WORKFLOWS,
)
from products.experiments.backend.temporal.timeseries.models import ExperimentTimeseriesRecalculationWorkflowInputs
from products.experiments.backend.temporal.timeseries.schedule import (
    create_experiment_regular_metrics_schedules,
    create_experiment_saved_metrics_schedules,
)

__all__ = [
    "ACTIVITIES",
    "EXPERIMENT_CANARY_ACTIVITIES",
    "EXPERIMENT_CANARY_WORKFLOWS",
    "EXPERIMENT_ENROLLMENT_CENSUS_ACTIVITIES",
    "EXPERIMENT_ENROLLMENT_CENSUS_WORKFLOWS",
    "EXPERIMENT_METRICS_RECALCULATION_ATTEMPT_HISTOGRAM_BUCKETS",
    "EXPERIMENT_METRICS_RECALCULATION_ATTEMPT_HISTOGRAM_METRICS",
    "EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_BUCKETS",
    "EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS",
    "EXPERIMENT_METRICS_RECALCULATION_SCHEDULE_TO_START_HISTOGRAM_BUCKETS",
    "EXPERIMENT_METRICS_RECALCULATION_SCHEDULE_TO_START_HISTOGRAM_METRICS",
    "EXPERIMENT_RECALCULATION_ACTIVITY_QUEUE_ACTIVITIES",
    "EXPERIMENT_SCHEDULED_RECALCULATION_ACTIVITIES",
    "EXPERIMENT_SCHEDULED_RECALCULATION_WORKFLOWS",
    "TIMESERIES_ACTIVITIES",
    "TIMESERIES_WORKFLOWS",
    "WORKFLOWS",
    "ExperimentTimeseriesRecalculationWorkflowInputs",
    "ExperimentsRecalculationMetricsInterceptor",
    "create_experiment_precompute_canary_schedule",
    "create_experiment_precompute_enrollment_census_schedule",
    "create_experiment_regular_metrics_schedules",
    "create_experiment_saved_metrics_schedules",
    "create_experiment_scheduled_recalculation_schedules",
]
