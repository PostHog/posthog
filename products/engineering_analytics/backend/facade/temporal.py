"""Temporal wiring exposed across the product boundary — the only import surface core may use.

Core registers these on the general-purpose worker and the schedule registry. Internals live under
``backend/logic/job_logs/``.
"""

from products.engineering_analytics.backend.logic.job_logs.schedule import create_github_job_logs_coordinator_schedule
from products.engineering_analytics.backend.logic.job_logs.temporal import (
    ACTIVITIES as JOB_LOGS_ACTIVITIES,
    WORKFLOWS as JOB_LOGS_WORKFLOWS,
)

__all__ = [
    "JOB_LOGS_ACTIVITIES",
    "JOB_LOGS_WORKFLOWS",
    "create_github_job_logs_coordinator_schedule",
]
