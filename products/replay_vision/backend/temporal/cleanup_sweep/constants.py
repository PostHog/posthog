"""Constants for the daily Replay Vision cleanup sweep."""

import datetime as dt

SCHEDULE_ID = "replay-vision-cleanup-sweep-schedule"
SCHEDULE_TYPE = "replay-vision-cleanup-sweep"
WORKFLOW_ID = "replay-vision-cleanup-sweep"
WORKFLOW_NAME = "replay-vision-cleanup-sweep"

SCHEDULE_INTERVAL = dt.timedelta(days=1)
WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(hours=1)

PRUNE_ACTIVITY_TIMEOUT = dt.timedelta(minutes=15)
PRUNE_HEARTBEAT_TIMEOUT = dt.timedelta(minutes=2)
REAP_ACTIVITY_TIMEOUT = dt.timedelta(minutes=10)
REAP_HEARTBEAT_TIMEOUT = dt.timedelta(minutes=2)

# Terminal observation rows older than this get deleted.
DEFAULT_RETENTION_DAYS = 90
# Cap per DB roundtrip; next-day sweep picks up the rest if more remain.
PRUNE_BATCH_SIZE = 1000
PRUNE_MAX_BATCHES = 50

# Pending/running rows older than this are checked against Temporal for stranding.
DEFAULT_STRANDED_HOURS = 6
REAP_DESCRIBE_CONCURRENCY = 10
REAP_MAX_CANDIDATES = 500

# Stamped on `error_reason` for rows reaped by the sweep; format matches the workflow's `kind:message`.
REAP_ERROR_REASON = "internal_error:workflow_terminated_before_completion"
