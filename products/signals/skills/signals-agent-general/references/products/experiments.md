# Lens: experiments

The profile doesn't surface experiments directly — it surfaces them
_indirectly_ through `popular_insights` (experiment metric insights are heavily
viewed during a launch), `recent_dashboards` (experiment dashboards), and
`top_events` (the primary metric event for the team's most-active experiments).
The scout's job is to find experiments that are running but invisible: stale,
mis-instrumented, drifting, or already done.

## Quick scan from the profile alone

`experiment-list` is cheap; call it early on any project where `popular_insights`
or `recent_dashboards` look experiment-shaped. Then look at the running set:

| Pattern                                                   | What it usually means                              |
| --------------------------------------------------------- | -------------------------------------------------- |
| Experiment `status = running` for > 4 weeks, no winner    | Stale — team likely forgot or is afraid to ship    |
| Variant exposure counts diverge from the configured split | Allocation drift — flag misconfig or routing bug   |
| Primary metric event present in `top_events` but flat     | Underpowered or instrumentation regression         |
| Primary metric event missing from `top_events` entirely   | Instrumentation never landed or recently broke     |
| Experiment depends on a flag that's currently off         | Silent end — exposure has stopped without shipping |
| `popular_insights` shows experiment chart ranked top-3    | Active investigation — someone's watching          |

If `experiment-list` is empty or every running experiment is recent and
well-instrumented, experiments are probably not where the signal is today.

## Patterns to look for

### Stale launched experiment

`status = running`, `start_date` more than 3-4 weeks ago, `end_date` null, no
winner declared. Every day it stays running it accumulates exposure with no
decision. Check whether the team has actually been monitoring it
(`popular_insights` viewer count on the experiment's metric, recency of
`experiment-results-get`).

High-confidence finding when:

- The experiment has reached its required sample size weeks ago.
- The primary metric has stabilized — `experiment-timeseries-results` shows
  flat significance for ≥ 7 days.
- No recent `last_modified_at` on the experiment row (nobody is iterating).

### Primary-metric movement

`experiment-stats` or `experiment-timeseries-results` shows a primary metric
moving in a sustained direction with growing significance. Pair with
`experiment-get` to confirm the experiment isn't already shipped or stopped.
If significance has been holding for > 5 days and the team hasn't acted, that's
a finding — either ship the winner or kill the loser.

### Variant exposure imbalance

`experiment-results-get` reports exposure per variant. If the actual split
diverges from the configured split by more than ~5% (e.g. 50/50 configured but
actuals run 60/40), the routing layer is leaking exposure. Pair with
`feature-flags-evaluation-reasons-retrieve` on the flag backing the experiment
to confirm.

### Primary metric instrumentation gap

Experiment running, but the primary metric event is missing or ultra-low in
`top_events`. Either the event was renamed and the experiment wasn't updated,
or the SDK release that emits the event hasn't shipped. The scout can't fix
it, but flagging it early saves weeks of "why is the experiment underpowered."

### Experiment depending on disabled flag

`experiment-get` exposes the underlying flag. If `feature-flag-get-definition`
shows the flag is disabled or rolled out at 0%, the experiment isn't getting
fresh exposures. Flag this — the team probably forgot to end the experiment.

## Disqualifiers (skip these)

- **Holdout / long-tail retention experiments** — explicitly designed to run
  for 90+ days. The experiment description usually flags this; memory entries
  from prior runs should too.
- **Drafts / pending experiments** — `status = draft`. Not yet running.
- **Recently launched (< 5 days)** — too early to call anything; let exposure
  accumulate before judging.
- **Experiments with `experiment-stats` not yet computed** — the platform
  hasn't gathered enough data; don't surface as broken.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `experiment-list` — start here. Filter to `status = running` and sort by
  start date (oldest running first surfaces stale candidates).
- `experiment-get` — full configuration: variants, primary/secondary metrics,
  feature flag binding, exposure criteria.
- `experiment-results-get` — current per-variant outcomes; check for variant
  imbalance and metric movement.
- `experiment-stats` — significance, sample size, statistical power.
- `experiment-timeseries-results` — significance over time; look for sustained
  flat / sustained moving regions.
- `feature-flag-get-definition` — verify the backing flag is still active and
  rollout matches the experiment's configured split.
- `feature-flags-evaluation-reasons-retrieve` — debug variant assignment when
  exposure imbalance is suspected.

For deep investigation playbooks, the sandbox image bakes
`posthog:auditing-experiments-flags` (broad health audit across experiments
and flags), `posthog:configuring-experiment-analytics` (how to read metrics,
exposure criteria, multivariate handling), `posthog:managing-experiment-
lifecycle` (preconditions for ending / shipping / archiving), and
`posthog:analyzing-experiment-session-replays` (qualitative drill into how
users interact with each variant).

## Memory shapes worth writing

After investigating experiments on a project, leave durable steers like:

- _"Experiment 'onboarding-v3' is a long-running holdout — designed to last
  through 2026-Q3, do not flag as stale."_ (`addressed`, `domain:experiments`,
  `entity:onboarding-v3`)
- _"Project's primary metric for activation experiments is `signed_up`, not
  `$identify`; the team renamed it 2026-04."_ (`pattern`, `domain:experiments`)
- _"Experiment 'pricing-page-cta' showed sustained primary lift since
  2026-04-22 — flagged but not shipped; if still running next week without a
  decision, escalate."_ (`pattern`, `domain:experiments`,
  `entity:pricing-page-cta`)
- _"Variant imbalance on 'checkout-flow-test' is a known JS routing bug —
  team is aware, fix landing in v2.4.0."_ (`addressed`, `domain:experiments`,
  `entity:checkout-flow-test`)

These compound: by run #5, the scout has the team's experiment cadence, knows
which experiments are intentional outliers, and surfaces only the ones that
warrant action.
