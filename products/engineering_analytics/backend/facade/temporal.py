"""Temporal wiring exposed across the product boundary.

Core registers these on the general-purpose worker and the schedule registry — see
``posthog/management/commands/start_temporal_worker.py`` and ``posthog/temporal/schedule.py``. The
internals live under ``backend/logic/job_logs/`` (isolated); this facade is the only import surface
core may use.
"""

from products.engineering_analytics.backend.logic.job_logs.schedule import create_github_job_logs_coordinator_schedule
from products.engineering_analytics.backend.logic.job_logs.temporal import (
    ACTIVITIES as JOB_LOGS_ACTIVITIES,
    WORKFLOWS as JOB_LOGS_WORKFLOWS,
)
from products.engineering_analytics.backend.logic.signals.schedule import create_ci_signals_coordinator_schedule
from products.engineering_analytics.backend.logic.signals.temporal import (
    ACTIVITIES as CI_SIGNALS_ACTIVITIES,
    WORKFLOWS as CI_SIGNALS_WORKFLOWS,
)

__all__ = [
    "JOB_LOGS_ACTIVITIES",
    "JOB_LOGS_WORKFLOWS",
    "create_github_job_logs_coordinator_schedule",
    "CI_SIGNALS_ACTIVITIES",
    "CI_SIGNALS_WORKFLOWS",
    "create_ci_signals_coordinator_schedule",
]
