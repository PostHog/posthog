from datetime import timedelta

SCHEDULE_ID = "replay-vision-gemini-cleanup-sweep-schedule"
WORKFLOW_ID = "replay-vision-gemini-cleanup-sweep"
WORKFLOW_NAME = "replay-vision-gemini-cleanup-sweep"
SCHEDULE_TYPE = "replay-vision-gemini-cleanup-sweep"

SCHEDULE_INTERVAL = timedelta(minutes=5)

REDIS_KEY_PREFIX = "replay-vision:gemini-file:"
REDIS_INDEX_KEY = "replay-vision:gemini-files-index"

# Matches Gemini's ~48h retention.
REDIS_KEY_TTL = timedelta(hours=48)

# Skips describing very-recently-started workflows that may not yet be visible to Temporal.
SWEEP_MIN_AGE = timedelta(seconds=60)

MAX_FILES_PER_SWEEP = 1500
MGET_BATCH_SIZE = 200

DESCRIBE_CONCURRENCY = 20
DELETE_CONCURRENCY = 10

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=20)
SWEEP_ACTIVITY_TIMEOUT = timedelta(minutes=15)
SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
