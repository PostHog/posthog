# Delegation recipes

Worked recipes for the common "have the scouts do X for me" asks.
Each one follows the same discipline: ground the job in real data, pick the cheapest rung on the steering ladder that gets it watched, and set up the feedback loop so the watch improves.
Tool mechanics (exact call shapes, confirmation flows, config fields) live in `authoring-scouts`; this file is about choosing the right move.

## "Watch this event I just shipped"

A new custom event ("`checkout_v2_completed`", "`ai_summary_generated`") that no canonical scout knows about.

1. Confirm the event actually captures: `read-data-schema` for its shape, a quick `execute-sql` for volume.
   No data yet? Wait until it flows — a scout can't baseline an empty stream.
2. Check the roster (`scout-config-list` descriptions): if the event belongs to a surface a specialist already watches (an error, a survey response, a flag call), a **note** telling that scout about the new event is enough.
3. Otherwise author a **custom single-event scout** via `authoring-scouts` — the custom single-event pattern in its `references/scout-patterns.md` is the template.
   Give it a real discriminator ("volume drops >50% against the trailing week while site traffic holds") rather than "watch for anything odd".

## "Tell me if errors / logs / traffic spike"

Almost always already covered — the canonical fleet ships anomaly watchers for error tracking, logs, web analytics, and most other surfaces.

1. Find the specialist in `scout-config-list` and confirm it's `enabled` with `emit: true`.
2. If the ask has a specific edge ("especially the checkout service", "only production"), leave the scout a **note** with that focus.
3. Only escalate to a skill edit if the scout structurally can't see what you care about (wrong threshold, missing disqualifier) — and it keeps proving that across runs.

## "Keep an eye on X this week" (time-boxed focus)

The textbook note use case — no authoring at all:

```json
scout-notes-create
{
  "content": "We think the EU signup funnel regressed after Tuesday's deploy — prioritize it this week. Baseline: ~4.2% visitor→signup.",
  "skill_name": "signals-scout-product-analytics",
  "expires_at": "<ISO date ~1 week out>"
}
```

`expires_at` makes the note self-retiring, so the channel stays clean without anyone remembering to delete it.
Omit `skill_name` to address the whole fleet — right when you don't know which scout will hit the surface first ("we migrated auth providers Monday; treat auth-adjacent shifts as suspect").

## "Give me a daily digest of what's happening"

Wanting a rhythm, not a new detector.
Two options, cheapest first:

1. Most scouts already run daily (default `run_interval_minutes: 1440`) and write only when something clears the bar — so the inbox _is_ the digest.
   Check the user isn't actually asking for a triage habit (`inbox-exploration` each morning).
2. If they genuinely want a roll-up report every day regardless of anomalies, that's the **daily digest / roll-up pattern** in `authoring-scouts`' `references/scout-patterns.md` — a custom scout that summarizes rather than detects.
   Set `auto_pause_exempt` thoughtfully: a digest people read but never "act on" in the inbox sense can look ignored to the auto-pause sweep.

## "Watch something outside PostHog" (vendor status page, docs, a competitor)

Scouts run in a sandbox that defaults to a trusted-domain allowlist (PostHog, GitHub, package registries).

1. If the external data already syncs into the data warehouse (Slack, a CRM, billing, support), point a scout at the warehouse table — the warehouse-backed source pattern — with no network change needed.
2. For genuinely external reads (a status page, arxiv, a changelog), author the custom scout and set `network_access: "full"` on its config.
   The change applies from the next run and is activity-logged.

## "The scouts are too noisy"

Diagnose which scout, then climb the ladder — don't pause the fleet wholesale.

1. Find the offender: report rates per scout via `exploring-scouts` (near-100% of runs writing is the tell), or just look at who filed the reports being ignored.
2. **Dismiss the noise well.** Every dismissal note is forwarded to the filing scout — three specific notes ("staging hosts", "known crawler", "internal test org") often quiet a scout with zero editing.
3. Still noisy? A **note** stating the pattern generally ("traffic from `*.dev.example.com` is ours, never report it").
4. Structurally noisy? Edit the body via `authoring-scouts`: add the disqualifier, raise the threshold.
5. Right signal, wrong volume? Slow it down: `scout-config-update` with a larger `run_interval_minutes`.
   Pause (`enabled: false`) is the last resort — a paused scout learns nothing.

## "The scouts never find anything"

Quiet is often correct — most runs should close out empty.
Before loosening anything:

1. Confirm the fleet runs at all (`scout-config-list`: enrollment, `enabled`, `emit` — dry-run scouts write nothing) and that runs actually execute (`exploring-scouts` health check).
2. Read a few run summaries: a scout narrating "surface at baseline" is working; if it keeps saying "no data for X", the watched surface may not capture data (`scout-project-profile-get` shows what's in use).
3. Only then consider the bar: a threshold edit via `authoring-scouts`, or a note pointing at what the team considers report-worthy that the scout is skipping.
4. Check the inbox default view isn't hiding output: suppressed reports (judged not-actionable) don't surface — `inbox-reports-list` with `status: "suppressed"` shows whether the scout is finding things that get filtered.

## "Get reports to the right person"

Reports reach people via `suggested_reviewers` — the inbox floats a report to the top of the suggested reviewer's own view.

1. Routing depends on org members having **linked GitHub identities**; without them, no report can flag `is_suggested_reviewer` for anyone.
2. If a surface's reports keep landing unrouted, teach the fleet the owner: a note ("checkout belongs to Dana — route checkout findings to dana-gh"), or for permanence, the owner map in the scout's body.
   Scouts cache confirmed owners as `reviewer:` scratchpad entries, so one good steer compounds.
3. A live report routed to no one isn't stuck — a scout (or you, via the report tools) can set reviewers on it after the fact.

## "Try a risky watch safely"

For a scout you expect to be chatty, expensive, or high-stakes:

1. Create it with `emit: false` (dry-run) in the nested config at `scout-create-prepare` time — it runs and logs what it _would_ report without touching the inbox.
2. Spend one `scout-run-now`, then read the run via `exploring-scouts` to see what it would have written.
   Runs are metered against the project's daily budget — dogfood the queries by hand for iteration and save real runs for end-to-end checks.
3. Calibrate, flip `emit: true`, and let the normal act-and-feed-back loop take over.
