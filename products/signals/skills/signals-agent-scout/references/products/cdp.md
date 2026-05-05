# Lens: CDP / hog functions

CDP (Customer Data Platform) is the team's **outbound pipeline** —
transformations, destinations, and the hog functions that move event data
out of PostHog into other systems (Slack, email providers, webhooks,
warehouses, ad platforms, etc.). Failures here are usually invisible to
end users but block the team's data-flowing-through-the-business plumbing.
Silent breakage is the worst case: data simply doesn't arrive at the
destination, and nobody notices until someone complains "we never got
that signup notification."

The team has CDP if `cdp-functions-list` returns enabled functions. There's
no `signal_source_configs` push source for CDP — this lens is direct query
against the hog-functions tools. The data shape is **success/failure
counts + function logs** rather than user-event volume, so the typical
"top_events recent_24h_count divergence" approach doesn't apply.

## Quick scan from `cdp-functions-list`

| Pattern                                                              | What it usually means                                                 |
| -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| All enabled functions show steady success rates                      | Healthy baseline; surface only if memory says otherwise               |
| Function with sudden drop in success rate (> 10% relative)           | Destination failing, credentials expired, rate limit, schema mismatch |
| Function with `disabled_at` set recently                             | Team disabled it manually — likely fixing something; check why        |
| Function with high `created_at` recency and 0 successful invocations | New function not yet receiving traffic, or trigger condition wrong    |
| Function with retry counts climbing without success                  | Persistent destination issue; eventual data loss when retries exhaust |
| Multiple functions of the same `template_id` failing together        | Upstream issue (PostHog → all destinations of one type)               |

If `cdp-functions-list` returns no enabled functions, the team isn't using
CDP — pivot. If they have functions but invocations are quiet across the
board, check whether trigger conditions match recent event activity (a
function expecting `signup` events when no signups happened isn't broken,
just inactive).

## Patterns to look for

### Destination failure-rate spike

A function's success rate drops materially below baseline (e.g. from 98% →
60%). Use `cdp-functions-metrics-retrieve` to confirm the drop is recent
and material; `cdp-functions-logs-retrieve` to read the actual error
messages. Common causes: destination credentials expired (auth errors
return 401/403), destination rate-limited (429s), destination schema
changed and the function's payload no longer matches (400s),
destination service degraded (503s). Cross-reference with the destination
provider's status page if memory has its URL recorded.

### New / recently-changed function failing

A function with recent `updated_at` showing immediate failures suggests
the change broke it — either a transformation logic bug, a destination
config change, or a typo in field mapping. The window between "deploy"
and "first failure" is usually short, so the timeline in
`cdp-functions-logs-retrieve` is diagnostic. Worth emitting if the
function is high-volume; worth a memory entry if it's a low-volume / new
addition the team is still iterating on.

### Cascade: shared template misbehaving

Multiple functions sharing the same `template_id` (e.g. all "Slack"
destinations) failing in a similar window. The issue is in the template
itself or in PostHog's outbound side, not in any single function. Check
`cdp-function-templates-list` for the template's recent `updated_at`,
and read logs across the affected functions for a common error.

### Retry-exhaustion data loss

A function shows retry counts climbing but eventual failures (the
function gives up). Each give-up is data that was supposed to land
somewhere and didn't. `cdp-functions-metrics-retrieve` exposes the
retry / failure split; logs show the give-up reason. High-priority
emit when the destination is load-bearing (memory should record which
destinations are critical).

### Throughput / volume change

Function invocations dropped or spiked materially without a corresponding
source-event change. A drop suggests the trigger condition narrowed
(e.g. cohort filter changed) or the source event volume itself dropped
(cross-check `top_events`). A spike suggests the trigger broadened or
duplicated. Worth a memory entry recording trigger configuration so
future runs can spot when it changes.

### Function template adoption

A new template appears in `cdp-function-templates-list` and a team member
just enabled an instance of it. Less a finding-trigger and more a
discovery worth memory: this team has a new outbound channel, future
runs should know to check it.

## Disqualifiers

- **Test invocations** — `cdp-functions-invocations-create` produces test
  events the team uses while iterating. Test runs against a function
  shouldn't be counted as production failures. Check the invocation's
  source / metadata before drilling.
- **Disabled functions** — `enabled=false` functions don't get invoked;
  zero throughput is correct.
- **Recently-changed function with brief failure window** — code being
  iterated. Memory should note the team's normal iteration shape.
- **Low-volume function with one or two failures** — statistical noise.
  Pivot to per-event success rate over a longer window before weighing.
- **Internal / dev destinations** — some functions route to internal
  Slack channels or test webhooks; failures there don't matter to users.
- **Destination provider known-down** — if memory records that a vendor
  has frequent outages, treat their failures as expected. Re-emit only
  when shape is novel (e.g. new error code).

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `cdp-functions-list` — start here. Lists all functions with status,
  template, recent `updated_at`. Use status filter to focus on enabled.
- `cdp-functions-retrieve` — single function detail: trigger conditions,
  destination config, payload mapping.
- `cdp-functions-metrics-retrieve` — per-function success / failure /
  retry counts over time. The bread-and-butter tool for this lens.
- `cdp-functions-logs-retrieve` — actual error messages. Use after
  metrics show a drop to find out _why_.
- `cdp-function-templates-list` / `cdp-function-templates-retrieve` —
  team's available outbound channels and their config shapes. Useful
  for spotting cascade patterns (multiple instances of one template).
- `cdp-functions-invocations-create` — produce a test invocation against
  a function. Use sparingly — only when a hypothesis warrants direct
  validation; never as bulk exploration.
- `read-data-schema events` — confirm the trigger event still exists and
  has the property the function maps before assuming the function itself
  is broken.

CDP doesn't have a dedicated PostHog-skill playbook in
`~/.claude/skills/` — the in-product UI at `/data-pipeline/destinations`
is the human-facing equivalent, but for agent investigation, lean on the
metrics + logs tools above.

## Memory shapes worth writing

After investigating CDP on a project, leave durable steers like:

- _"Slack-destination function `notify-signups` is the team's hot
  outbound — handles signup pings to #growth. Failures are P1; team
  notices within minutes."_ (`pattern`, `domain:cdp`,
  `entity:notify-signups`)
- _"`webhook-archival-internal` routes to an internal data warehouse;
  failures don't affect users, only internal analytics — P3 if at
  all."_ (`pattern`, `domain:cdp`, `entity:webhook-archival-internal`)
- _"Slack API rate-limits at hour boundaries (~xx:00) — recurring 429
  spike for 30s, recovers automatically. Not a signal."_ (`noise`,
  `domain:cdp`, `entity:slack-rate-limit`)
- _"All `email-mailgun-_` functions share the same auth config —
credential rotation 2026-04-15 caused brief cluster failure, fixed
same day."* (`addressed`, `domain:cdp`,
`entity:mailgun-auth-rotation-2026-04-15`)
- _"New `linear-issue-create` function added 2026-04-22 — volume
  ramping; expect transient errors during iteration phase, recheck
  baseline in 7d."_ (`pattern`, `domain:cdp`,
  `entity:linear-issue-create-ramp`)

These compound: by run #5, the scout knows which destinations are
load-bearing vs internal, which providers have known intermittent
issues, and which functions are in active iteration.
