from datetime import timedelta

SCHEDULE_ID = "replay-vision-jev-watch-rank-schedule"
WORKFLOW_ID = "replay-vision-jev-watch-rank"
WORKFLOW_NAME = "replay-vision-jev-watch-rank"
SCHEDULE_TYPE = "replay-vision-jev-watch-rank"

SCHEDULE_INTERVAL = timedelta(hours=1)

# Matches the feed's default window (`date_from=-7d`), so every row the default feed can show has
# been offered to Jev.
WATCH_RANK_WINDOW = timedelta(days=7)
# Ids listed per scanner per sweep. This bounds the cache size and the id query, and it is the
# coverage ceiling on a very-high-volume scanner: rows past it stay unjudged filler.
WINDOW_SCAN_CAP = 1000
# New rows judged per scanner per sweep. Judgments accumulate in the cache, so this caps the hourly
# Jev spend, not the coverage: a backlog drains at this rate across later sweeps, newest first.
MAX_JUDGED_PER_SCANNER = 100
# The newest-first pick would retry a deterministically failing batch every hour and starve older
# rows for the whole window. After this many batch-attributable failures (an invalid answer, a
# gateway refusal the batch caused) a row is recorded as judged with no score, so it
# settles into the recency filler tier like a prose-less row — for the life of the cache entry,
# since every sweep over an active scanner refreshes the TTL. Environmental failures (an outage,
# a rate limit, a misconfigured gateway) charge no attempt, so a bad hour parks nothing.
MAX_JUDGE_ATTEMPTS = 3
# Team 2 is PostHog's own team, swept first so the internal arm never waits behind the experiment.
PINNED_TEAM_IDS = (2,)
# Bound one sweep, so a misconfigured flag rollout cannot turn it into an unbounded flag-check or Jev
# fan-out. Sized above every team with a scanner and every scanner in a half rollout, so at
# experiment scale the time budget, not these counts, decides how far a run gets.
MAX_TEAMS_PER_SWEEP = 50_000
MAX_SCANNERS_PER_SWEEP = 20_000
# Scanners judged at once. A turn mostly waits on Jev, so this multiplies throughput. Eight at once
# kept hitting the gateway's rate limit, which every product's Jev calls share, so it stays low.
JUDGE_CONCURRENCY = 2
# Rate-limited scanner turns after which the rest of the run waits for the next sweep.
RATE_LIMIT_BACKOFF_AFTER = 3
# Judging stops here even under the caps: worst-case chunks x the 30s request timeout run far past
# any reasonable activity timeout, so the wall clock is the binding limit, not the counts. Scanners
# cut off by the budget wait for the next hourly run, where already-judged rows cost nothing.
SWEEP_TIME_BUDGET = timedelta(minutes=30)

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=45)
SWEEP_ACTIVITY_TIMEOUT = timedelta(minutes=40)
SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
