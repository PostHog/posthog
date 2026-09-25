from datetime import timedelta

SCHEDULE_ID = "replay-vision-jev-watch-rank-schedule"
WORKFLOW_ID = "replay-vision-jev-watch-rank"
WORKFLOW_NAME = "replay-vision-jev-watch-rank"
SCHEDULE_TYPE = "replay-vision-jev-watch-rank"

SCHEDULE_INTERVAL = timedelta(hours=1)

# Matches the feed's default window (`date_from=-7d`), so every row the default feed can show has
# been offered to Jev.
WATCH_RANK_WINDOW = timedelta(days=7)
# Keep equal to WATCH_FEED_PER_SCANNER_CAP in api/scanners.py: rows past the feed's per-scanner
# candidate cap can never rank, so judging them buys nothing.
WINDOW_ROWS_CAP = 100
# Bound one sweep. The flag gates per team, so at experiment scale these caps are slack; they exist
# so a misconfigured flag rollout cannot turn the sweep into an unbounded flag-check or Jev fan-out.
MAX_TEAMS_PER_SWEEP = 2000
MAX_SCANNERS_PER_SWEEP = 500
# Judging stops here even under the caps: worst-case chunks x the 30s request timeout run far past
# any reasonable activity timeout, so the wall clock is the binding limit, not the counts. Scanners
# cut off by the budget wait for the next hourly run, where the unchanged-window skip makes room.
SWEEP_TIME_BUDGET = timedelta(minutes=30)

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=45)
SWEEP_ACTIVITY_TIMEOUT = timedelta(minutes=40)
SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
