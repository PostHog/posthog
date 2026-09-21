from datetime import timedelta

SCHEDULE_ID = "replay-vision-media-backfill-schedule"
WORKFLOW_ID = "replay-vision-media-backfill"
WORKFLOW_NAME = "replay-vision-media-backfill"
SCHEDULE_TYPE = "replay-vision-media-backfill"

SCHEDULE_INTERVAL = timedelta(minutes=5)

# Renders are unpriced infra, so this paces the media fleet rather than bounding a cost.
MAX_OBSERVATIONS_PER_TICK = 25
CANDIDATE_SCAN_LIMIT = 200
# A live scan is already rendering anything newer, and would win the race for the same id anyway.
MIN_OBSERVATION_AGE = timedelta(minutes=15)
# The analysis video expires around 30 days, so older gaps can never be filled and cost a rescan.
MAX_OBSERVATION_AGE = timedelta(days=35)
ATTEMPT_COOLDOWN = timedelta(hours=6)
# Past this the recording is broken, and retrying forever would hold the head of the walk.
MAX_RENDER_ATTEMPTS = 3

FIND_CANDIDATES_TIMEOUT = timedelta(minutes=2)
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=10)
