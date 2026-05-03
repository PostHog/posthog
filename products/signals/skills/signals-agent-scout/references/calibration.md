# Calibration: explore vs exploit

Memory compounds — that's its strength and its trap. Once enough entries say "this
is noise" or "already addressed", the scout starts skipping the same surfaces every
run. New issues in those surfaces never surface. Calibration is how you decide,
each run, where you sit on the explore/exploit spectrum.

Read this when you orient. The right posture for _this_ run depends on how mature
the team's memory is, what's changed since the last run, and where coverage is
thin.

## Three signal families

All three are derivable from data you can already pull. No special tool calls.

### Maturity signals (how much do prior runs already cover this team?)

From `signals-agent-runs-list`:

- **`run_count`** — total prior runs on this team.
- **`days_since_first_run`** — when the scout first ran here.
- **`days_since_last_run`** — gap since the most recent run.
- **`findings_emitted_30d`** — sum of `findings.length` across runs in the last 30
  days.

From `signals-agent-memory-list`:

- **`memory_count`** — total non-expired entries.
- **`days_since_new_memory`** — gap since the most recent `created_at`. **The
  single most useful staleness signal.** Many runs + many days since new memory =
  the agent has stopped learning.

### Change signals (is there genuinely new territory?)

From `signals-agent-project-profile-get`:

- **Products in `products_in_use` you don't have a memory entry for.** Memory tags
  are the proxy for "have I touched this domain?" — if `products_in_use` lists
  `error_tracking` but no memory entry has tag `domain:error_tracking`, that
  product is unexplored from this scout's perspective.
- **`external_data_sources` rows** with no matching `entity:<source_prefix>` memory
  entry — new warehouse syncs you've never investigated.
- **`top_events` entries** that look unusual (high `recent_24h_users` relative to
  `distinct_users`, or names you've never written memory about).
- **`product_intents` rows** — stuck onboardings; recent ones are signals of new
  team activity.
- **Recently-enabled `signal_source_configs`** — the team just turned on a source.

### Coverage signals (which lenses are stale?)

From `signals-agent-memory-list`, group entries by their `domain:<area>` tag and
read the most recent `created_at` per domain. The lens with the oldest "last
touched" is the most exploit-locked surface.

This is approximate (depends on prior runs tagging `domain:*` consistently) but
it's the cheapest coverage proxy without time-series profile diffs.

## Posture decisions

| Situation                                                                         | Posture                                                                                                                                                                                                                      |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_count < 5` or `days_since_first_run < 7`                                     | **Cold-start.** Touch every product in `products_in_use` at least lightly. Write memory liberally — even baselines (`$pageview is ~5k/day`) pay off later. Don't worry about depth this run; breadth compounds.              |
| Change signals present (new product / new source / unfamiliar `top_events` entry) | **Change-driven.** New territory wins this run regardless of memory maturity. Investigate the new thing first; the established surfaces can wait one run.                                                                    |
| `run_count ≥ 5`, `days_since_new_memory < 3`, no change signals                   | **Steady-state exploit.** Memory is fresh and dense. Trust dedupes, follow active threads from recent runs, use lenses to drill where memory points.                                                                         |
| `run_count ≥ 5`, `days_since_new_memory ≥ 7`, no change signals                   | **Steady-state-with-stale-coverage.** Memory has plateaued. Pick the staleneste lens (oldest `domain:*` memory) and **deliberately poke**. You're checking whether memory's blind spots are real.                            |
| Otherwise (mature project, normal cadence, no obvious staleness)                  | **Mostly exploit, occasional wildcard.** Roughly one run in ten, pick a domain or `top_events` entry you'd normally skip and spend 2-3 cheap reads there. Treat it as a sanity check on memory, not a serious investigation. |

These are starting heuristics. The agent is the judge — if you read the signals
and the right posture is obvious, act on it. If you're uncertain, default to
"mostly exploit, occasional wildcard."

## The wildcard move

When posture says _steady-state-with-stale-coverage_ or the every-tenth-run
wildcard, here's the move:

1. From `signals-agent-memory-list`, find the `domain:<area>` tag with the oldest
   most-recent `created_at`. That lens is your wildcard target.
2. Optionally, also look at `top_events` for an event you've never written memory
   about (filter out ones with `domain:*` memory entries).
3. Read the per-product reference for that domain (e.g.
   [`products/feature-flags.md`](products/feature-flags.md)) and run 2-3 cheap
   queries from its drill-in patterns.
4. Whatever you find — even nothing — write a memory entry tagged with the
   domain. **This is the point of the wildcard**: refresh the coverage signal.

Cap the wildcard at 2-3 reads. It's a sanity check, not a deep investigation. If
you uncover something real, follow it; otherwise close the thread and return to
the rest of the run.

## The trap to avoid

A wildcard that produces a low-confidence finding will, under default dedupe
rules, get a `noise`-tagged memory written which then **permanently blocks future
wildcards from re-checking that area**. That defeats the purpose.

Two habits to keep wildcards productive:

- **Tag wildcard-driven memories with `tag:exploration`** alongside the
  `domain:<area>` tag. Future runs reading these can tell "this was a quiet
  wildcard, not a confirmed pattern" — they should re-check on a future
  wildcard, not skip forever.
- **Don't write `noise` or `addressed` tags from a wildcard run** unless the
  evidence is rock-solid. Quiet-this-time isn't quiet-forever; default to
  `pattern` with a date anchor ("checked feature flags 2026-05-03 — no recent
  evaluation loops, baseline ~12 evals/day per flag") and let future wildcards
  refresh it.

## Worked example

Run inputs to read:

- `signals-agent-runs-list`: 12 prior runs on this team, oldest 14 days ago,
  newest 1 hour ago, total 4 findings emitted in 30d.
- `signals-agent-memory-list`: 18 entries; most recent `created_at` is 9 days
  ago. Tags include `domain:error_tracking` (most recent: 9 days), `domain:web_analytics`
  (most recent: 11 days), `domain:llm_analytics` (most recent: 12 days). No
  entries tagged `domain:warehouse` or `domain:feature_flags`.
- `signals-agent-project-profile-get`: `products_in_use` includes
  `error_tracking`, `web_analytics`, `llm_analytics`, `warehouse`,
  `feature_flags`. `external_data_sources` shows two rows, both connected
  more than a month ago. `top_events` looks normal.

Reading: `run_count = 12` (mature), `days_since_new_memory = 9` (memory
plateaued), no change signals. **Posture: steady-state-with-stale-coverage.**

Coverage gaps:

- `domain:warehouse` — listed in `products_in_use`, zero memory entries. Cold lens
  in a mature project.
- `domain:feature_flags` — same.

Move: pick `feature_flags` (random tiebreak), open
[`products/feature-flags.md`](products/feature-flags.md), run two of its drill-in
patterns: list flags evaluated in last 24h grouped by user, check for
evaluation-loop shapes. Find baseline activity and no anomalies. Write one
memory entry:

```text
2026-05-03: wildcard check on feature_flags — listed flags evaluated last 24h,
~12 evals/day per active flag, no loop shapes, no rollouts changed in last 7d.
Quiet baseline. Tags: domain:feature_flags, pattern, tag:exploration.
```

Next run reads memory, sees `feature_flags` was just touched (now `domain:feature_flags`
isn't the stalest), picks `warehouse` for the next wildcard, and so on. Coverage
rotates without the harness scheduling anything.
