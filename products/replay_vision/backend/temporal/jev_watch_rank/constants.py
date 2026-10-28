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
# Estimated prompt tokens per second one run (one region) may send, enforced across its concurrent
# turns. The concurrency cap bounds how many requests are in flight, not how fast they go out, so
# without this the hour's work lands on the decision service in the run's first minutes. About 30%
# of one L4 host's ~7,000 tokens/s, a peak the service owners asked us to stay under.
JUDGE_TOKENS_PER_SECOND = 2_000
# A rate-limited turn pauses new turns this long. The decision service frees capacity within
# seconds, so a pause lets the run continue without taking capacity from other products' calls.
RATE_LIMIT_PAUSE = timedelta(seconds=30)
# Rate-limited turns in a row, with no clean turn between, after which the rest of the run waits for
# the next sweep.
RATE_LIMIT_GIVE_UP_AFTER = 5
# Judging stops here even under the caps: the wall clock is the binding limit, not the counts, and
# paced runs are meant to use most of the hour. Capped under the shortest gap between one run and
# the next (hourly ticks carry up to 10 minutes of jitter, so a late run and an early next tick can
# sit 50 minutes apart). The activity and workflow timeouts below run past that gap, so a run that
# pathologically overshoots its budget can make the SKIP overlap policy drop one tick — accepted,
# because its rows just retry. Scanners cut off by the budget wait for the next hourly run, where
# already-judged rows cost nothing.
SWEEP_TIME_BUDGET = timedelta(minutes=45)

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=55)
SWEEP_ACTIVITY_TIMEOUT = timedelta(minutes=50)
SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
