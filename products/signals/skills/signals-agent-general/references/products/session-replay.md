# Lens: Session replay

Sessions are a unique signal source: they capture **what users actually
experienced**, not just what they did. Pure event analysis sees a click; replay
sees that the user clicked twice because the first click was on an unresponsive
element. This lens is about surfacing UX-level signal that other lenses
structurally miss.

The team has session replay if `products_in_use` includes `session_replay` and
`top_events` has `$session_recording_*` events with non-trivial volume. The
existing push pipeline (`session_analysis_cluster` source) already emits
clustered problem signals — the scout's value here is **cross-session pattern
recognition** that the per-cluster emitter can't see, plus **bridging to other
lenses** when replay evidence supports a finding from elsewhere.

## Quick scan from the profile alone

| Pattern                                                               | What it usually means                                                       |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `$session_recording_*` event volume stable across 7d/24h              | Healthy capture, baseline operating                                         |
| `$session_recording_*` `recent_24h_count / count` ≪ `1/7`             | Capture dropped — SDK regression, sampling change, or quota                 |
| `$session_recording_*` quiet but `$pageview` healthy                  | Replay broken specifically — check SDK init / ad blockers / config          |
| `session_analysis_cluster` enabled in `signal_source_configs`         | Push pipeline is producing problem signals — read inbox before drilling     |
| Recent `inbox-reports-list` count from `session_replay` source rising | Cluster pipeline surfacing more issues than baseline                        |
| `session_analysis_cluster` enabled but inbox reports are rare         | Pipeline running but clusters aren't reaching threshold — sampling or noise |

If `$session_recording_*` events are absent from `top_events`, replay isn't
running or the team disabled it — pivot to other lenses. If
`session_analysis_cluster` isn't enabled in `signal_source_configs`, the team
hasn't opted into the push-source clusters, so this lens's data is mostly
direct query against recordings rather than read from the inbox.

## Patterns to look for

### Pattern-cluster spike

`inbox-reports-list` filtered to `source_product=session_replay` shows
clusters growing — a recurring problem (rage-clicking the same button, dead
zone in a flow) is happening to more users than baseline. The cluster
description from the push pipeline already names the pattern; the scout's job
is to confirm reach (`distinct_users`) is material and the timeline is recent
(not an old cluster surfacing). Cross-source convergence with
`error-tracking` issues or a recent deploy in `activity-log-list` is high-signal.

### Rage-click concentration on a UI element

Rage clicks (rapid repeated clicks on the same element) cluster on a specific
selector or path. Often surfaces when a UX change made an element look
clickable but unresponsive, or when a loading state isn't visible enough.
Use `posthog:investigating-replay` to drill into a sample session — does the
user actually achieve their goal afterward, or do they bounce? The latter is
worth emitting; the former is friction worth a memory entry.

### Dead-click cluster

Users clicking elements that don't respond — different from rage clicks
(repeated) but related. Often caused by JavaScript errors blocking handlers
or by UI elements styled like buttons that aren't actually interactive.
Pair with `error-tracking-issues-list` filtered to the same time window and
URL — if there's an exception spike on the page, the dead clicks are likely
caused by it.

### Error-during-recording correlation

`$exception` volume in a session window matches an `error-tracking` issue
spike. Watching a few replays of the affected sessions tells you whether
users see the error (worth emitting), recover gracefully (worth a memory
entry), or rage-click and abandon (high-priority emit). Use
`posthog:finding-replay-for-issue` to get the most informative replay for
a given error-tracking issue rather than blindly sampling.

### Session-completion / watch-time drop

Average session duration or watch-time on a key flow drops materially.
Suggests users are bailing earlier — could be a perf regression, a confusing
new step, or a banner / modal disrupting flow. `query-session-recordings-list`
filtered to the affected flow with recent timestamps gives you a candidate
set; sample 2-3 recordings to confirm the behavior is consistent.

### Capture-rate drop (SDK / config issue)

`$session_recording_*` events dropped vs baseline while `$pageview` and other
events are healthy. Specific to replay capture — usually an SDK upgrade
gone wrong, a feature flag toggling sampling, an ad-blocker pattern, or a
quota threshold hit. Use `posthog:diagnosing-missing-recordings` for the
checklist.

### Cross-experiment behavior contrast

When experiments are running, replay can show qualitative differences
between variants that the metric numbers don't capture (e.g. variant B
users hesitate noticeably longer at step 3). Use
`posthog:analyzing-experiment-session-replays` for the comparison playbook.
Worth emitting when the qualitative shape contradicts the metric direction —
"variant B looks healthier in numbers but users are rage-clicking the new
CTA."

## Disqualifiers

- **Internal / dev sessions** — engineers testing in production produce
  noisy replays. Filter on email domain or known internal cohort.
- **Bot traffic** — synthetic monitoring against production looks like
  user sessions; check user-agent patterns.
- **Demo accounts** — many B2B teams have demo accounts whose users behave
  differently (often clicking everything, generating false rage-click
  signal). Memory should record their identity markers.
- **Mobile-vs-web baseline differences** — mobile typically has higher
  rage-click density; treating them as a single baseline produces false
  positives. Memory should split per platform.
- **Recent SDK rollout** — capture rate changes after an SDK upgrade are
  expected, not a regression. Cross-check `activity-log-list` and recent
  deploys.
- **Sampling-policy change** — if the team flipped a sampling feature flag,
  the apparent drop isn't a capture issue. Check `feature-flags` lens.
- **Single user clicking weird things** — one person's session isn't a
  pattern. Pivot to per-user rate before weighing.

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `inbox-reports-list` filtered to `source_product=session_replay` — start
  here. The push pipeline already clusters problems; read what's there
  before doing direct-query exploration.
- `inbox-reports-retrieve` — drill into a specific session-replay-sourced
  report; see linked sessions and the cluster description.
- `query-session-recordings-list` — list recent recordings, filterable by
  user / event / pageURL / duration. Use to pull a candidate set when you
  have a hypothesis worth replay-validating.
- `session-recording-get` — fetch one recording's metadata (events, duration,
  participants, segments).
- `session-recording-summarize` — AI-generated summary of what happened in
  a recording. Faster than watching; gives a high-level read on whether the
  pattern matches your hypothesis.
- `session-recording-playlists-list` / `session-recording-playlist-get` —
  team-curated session sets. The team's playlists tell you what flows they
  watch deliberately.
- `query-trends` on `$session_recording_*` events with breakdowns —
  capture-rate analysis (e.g. by browser, by URL, by day-of-week).
- `error-tracking-issues-list` — when correlating replay patterns with
  exceptions, this is the bridge.

For deep investigation playbooks, the sandbox image bakes:

- `posthog:investigating-replay` — full session investigation: metadata,
  person profile, same-session events, linked error-tracking issues.
- `posthog:finding-replay-for-issue` — finding the most informative replay
  linked to a given error-tracking issue. Use when the spike is on the
  errors lens and you want replay confirmation.
- `posthog:analyzing-experiment-session-replays` — comparing replay
  patterns across experiment variants.
- `posthog:diagnosing-missing-recordings` — when capture appears broken,
  this is the troubleshooting checklist.

Lean on these rather than manually deriving the investigation order — they
encode hard-won detail (e.g. which person properties matter, which event
sequences are diagnostic).

## Memory shapes worth writing

After investigating session replay on a project, leave durable steers like:

- _"This team's `$session_recording_full_snapshot` baseline is ~5k/day with
  ~80% capture rate (recordings/pageviews); below 60% suggests SDK or
  config regression."_ (`pattern`, `domain:session_replay`,
  `entity:capture_rate_baseline`)
- _"Mobile sessions show ~3x rage-click density vs web — known UX shape,
  not a signal unless mobile baseline shifts."_ (`pattern`,
  `domain:session_replay`, `entity:mobile_rageclick_baseline`)
- _"Demo accounts (`@acme-demo.example.com`) produce noisy session patterns
  — filter `properties.email NOT LIKE '%-demo%'` for user-facing
  signal."_ (`noise`, `domain:session_replay`, `entity:demo_filter`)
- _"`session_analysis_cluster` push source enabled 2026-04-15; expect
  steady-state ~2 inbox reports/week from this source."_ (`pattern`,
  `domain:session_replay`, `entity:cluster_source_baseline`)
- _"Cluster `signup-page-button-rageclick` was active 2026-04-22 to
  2026-04-30, root-cause was a CSS regression, fixed in deploy abc123 —
  don't re-emit if it reappears briefly during cache propagation."_
  (`addressed`, `domain:session_replay`, `entity:cluster-signup-rageclick`)

These compound: by run #5, the scout knows the team's healthy capture
baseline, which UX patterns are noise vs signal on which platforms, what
demo / internal markers to filter, and which historical clusters were
already investigated and resolved.
