from datetime import timedelta

from temporalio.common import RetryPolicy

# Workflow
WORKFLOW_NAME = "logs-volume-tick"

# Schedule
SCHEDULE_ID = "logs-volume-tick-schedule"
SCHEDULE_CRON = "* * * * *"

# Activity
ACTIVITY_TIMEOUT = timedelta(minutes=1)
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)
