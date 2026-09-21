from datetime import timedelta

SCHEDULE_ID = "replay-vision-media-backfill-schedule"
WORKFLOW_ID = "replay-vision-media-backfill"
WORKFLOW_NAME = "replay-vision-media-backfill"
SCHEDULE_TYPE = "replay-vision-media-backfill"

SCHEDULE_INTERVAL = timedelta(minutes=5)

# 3000 an hour, which clears a day of missing posters in under a day. The media fleet renders about
# as fast again on one pod, and KEDA has 19 more, so this paces storage rather than compute: each
# poster is about 120KB.
MAX_OBSERVATIONS_PER_TICK = 250
CANDIDATE_SCAN_LIMIT = 1000
# A live scan is already rendering anything newer, and would win the race for the same id anyway.
MIN_OBSERVATION_AGE = timedelta(minutes=15)
# Inside the analysis video's own lifetime on purpose. Reaching past it finds observations whose
# video is gone, which can never be filled, record no attempt, and so sit at the head of a
# newest-first walk rescanning themselves on every tick.
MAX_OBSERVATION_AGE = timedelta(days=7)
ATTEMPT_COOLDOWN = timedelta(hours=6)
# Past this the recording is broken, and retrying forever would hold the head of the walk.
MAX_RENDER_ATTEMPTS = 3

FIND_CANDIDATES_TIMEOUT = timedelta(minutes=2)
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=10)
# The bound the live path gives the same child. Abandoned children outlive this workflow, and one that
# never closes holds the deterministic id against every later tick.
MEDIA_CHILD_EXECUTION_TIMEOUT = timedelta(minutes=20)
