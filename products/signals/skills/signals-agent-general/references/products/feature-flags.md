# Lens: feature flags

Feature-flag signals show up in `top_events` as `$feature_flag_called` and in
the project profile only weakly — no dedicated section in the inventory yet.
The scout's entry point is `feature-flag-get-all` plus the
`$feature_flag_called` row in `top_events`. The relationship between flag
count, evaluation count, and user reach tells you whether flag hygiene is the
issue or whether evaluation patterns themselves are surfacing something.

## Quick scan from the profile alone

Look at `$feature_flag_called` in `top_events`:

| Pattern                                                                    | What it usually means                              |
| -------------------------------------------------------------------------- | -------------------------------------------------- |
| `$feature_flag_called` `count` ≫ `distinct_users` (e.g. 100x)              | Server-side flag eval loop or per-request thrash   |
| `$feature_flag_called` `count` ≈ `distinct_users` (close to 1:1)           | Healthy — one eval per user session                |
| `$feature_flag_called` very high `recent_24h_count` and `recent_24h_users` | New flag launched at scale — verify intentional    |
| `$feature_flag_called` quiet on a team using flags heavily                 | Eval-side regression or SDK init failure suspected |

Pair with `feature-flag-get-all`:

| Pattern                                                      | What it usually means                              |
| ------------------------------------------------------------ | -------------------------------------------------- |
| Many flags with `rollout = 100` and `created_at > 6mo ago`   | Stale flags piling up — cleanup candidate set      |
| Flag `active = false` but high `$feature_flag_called` volume | Dead-code path still being evaluated — wasted work |
| Flag depends on another flag that's `active = false`         | Dependency stale — first flag effectively off      |
| Flag with `rollout = 0` and recent `last_modified_at`        | Mid-rollout — give it time before judging          |

If both `$feature_flag_called` is healthy and `feature-flag-get-all` shows
< 50 flags with no obvious staleness, feature flags probably aren't where the
signal is today.

## Patterns to look for

### Evaluation loop

`$feature_flag_called` `count` is in the millions but `distinct_users` is
small (e.g. 100k:5 ratio). A server-side process is evaluating the same flag
on every request without caching, or a client-side polling loop never
backed off. Drill in:

1. `read-data-schema event_property_values` on `$feature_flag` to find the
   top flag by call volume.
2. `query-trends` on `$feature_flag_called` filtered to the top flag,
   broken down by `$lib` (server SDK vs client) to confirm where it's looping.
3. `feature-flags-evaluation-reasons-retrieve` for the flag — if local-eval
   is enabled but the SDK keeps making remote calls, that's the bug.

### Stale rolled-out flag

`feature-flag-get-all` filtered to `active = true`, `rollout = 100`, and
`last_modified_at` > 90 days. The flag has been at full rollout for months
without being deleted. `feature-flags-status-retrieve` returns staleness
classification. Bundle them in one finding (the team usually wants to clean
the whole batch, not one at a time).

### Dependency staleness

`feature-flags-dependent-flags-retrieve` exposes the dependency tree. A flag
whose parent is disabled is effectively off — but `$feature_flag_called`
still fires. Surface the chain: dependent flag id, parent id, parent state.

### Newly launched flag with unexpected blast radius

A flag with `created_at` in the recent window and high
`$feature_flag_called` volume + high distinct_users. Validate against
`feature-flags-user-blast-radius-create` to compare predicted vs actual
exposure. If actual >> predicted, the rollout is wider than the team
expected.

### SDK init regression

`$feature_flag_called` count drops sharply 24h vs 7d baseline without a
corresponding traffic drop in `$pageview`. Either flag evaluation moved
elsewhere (e.g. behind an edge gateway) or the SDK init path broke. Cross-
check `error-tracking-issues-list` for SDK-init exceptions; pair with
`activity-log-list` for recent deploys.

## Disqualifiers (skip these)

- **Holdout flags meant to live forever** — explicit holdout / "never
  remove" tagging in the flag's description or metadata. Memory should
  record these.
- **Recently launched flags (< 14 days)** — too early to call stale. Don't
  surface as cleanup candidates.
- **Local / dev / test flags** — names containing `test_`, `dev_`, or
  flagged with `localhost` filters. Filter before counting.
- **Experiment-backed flags** — `feature-flag-get-definition` showing
  experiment binding; the experiments lens covers this case more directly.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `feature-flag-get-all` — start here. Filter by `active`, `rollout`,
  `created_at` to narrow the candidate set.
- `feature-flag-get-definition` — full flag config including filters,
  variants, experiment binding.
- `feature-flags-status-retrieve` — staleness classification per flag.
- `feature-flags-evaluation-reasons-retrieve` — why a flag returned a given
  value for debugging eval loops.
- `feature-flags-dependent-flags-retrieve` — dependency tree for cascade
  staleness.
- `feature-flags-user-blast-radius-create` — predicted vs actual exposure
  for a rollout.
- `feature-flags-activity-retrieve` — change history for a flag, useful
  when the flag's behavior shifted unexpectedly.
- `read-data-schema event_property_values` on `$feature_flag` — top flags
  by evaluation volume.

For deep investigation playbooks, the sandbox image bakes
`posthog:cleaning-up-stale-feature-flags` (staleness detection, dependency
checking, safe removal workflows) and `posthog:auditing-experiments-flags`
(broad health audit across experiments and flags).

## Memory shapes worth writing

After investigating feature flags on a project, leave durable steers like:

- _"Flag `enable-new-checkout` is intentionally a permanent holdout — do
  not surface as stale."_ (`addressed`, `domain:feature_flags`,
  `entity:enable-new-checkout`)
- _"Server SDK on auth path evaluates `block-bot-traffic` per-request — high
  volume is expected."_ (`pattern`, `domain:feature_flags`,
  `entity:block-bot-traffic`)
- _"Team has ~85 flags > 6 months old at rollout=100; surfaced once on
  2026-04-30, team scheduled cleanup for sprint 2026-W19."_ (`addressed`,
  `domain:feature_flags`)
- _"`$feature_flag_called` baseline is ~3M/day across ~50k users; ratios
  above 100:1 indicate eval loops."_ (`pattern`, `domain:feature_flags`)

These compound: by run #5, the scout knows the team's flag inventory, which
flags are intentional outliers, and only surfaces fresh evaluation anomalies
or net-new staleness.
