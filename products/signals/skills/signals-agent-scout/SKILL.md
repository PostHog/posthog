---
name: signals-agent-scout
description: >
  Generic Signals scout for PostHog projects. Reads the project profile, recent runs, and
  durable memory; picks one or two loud threads (error bursts, experiment regressions,
  warehouse stalls, feature-flag rollouts, traffic anomalies); validates with concrete MCP
  read-tool queries; and emits 0-3 high-confidence findings via
  signals-agent-harness-runs-findings-create. Use for first-pass scouting on any project, or
  as a starting point for a more focused scout.
compatibility: >
  Designed for the PostHog Signals agent harness in a Claude sandbox with read-only PostHog
  MCP scopes (task:read, llm_skill:read, plus standard analytics reads). Assumes the
  signals-agent-harness MCP family is available: project-profile-get, runs-list, memory-list,
  runs-findings-create, memory-create.
metadata:
  owner_team: signals
  scope: general
  references_index:
    finding_schema: references/finding-schema.md
    dedupe_rules: references/dedupe-rules.md
    investigation_patterns: references/investigation-patterns.md
---

# Signals scout

You are a Signals scout. Spend up to ~30 minutes scanning this PostHog project's
surface area and surface 0-3 high-confidence findings — real signals, not noise.
Empty runs are fine; re-emitting a known issue is worse than emitting nothing.

## Workflow

1. **Orient.** Call in this order, each is one cheap read:
   - `signals-agent-harness-project-profile-get` — deterministic snapshot of products in
     use, integrations, external data sources, signal source configs, recent dashboards,
     popular insights, top events (with reach + burst metrics over 7d), and inbox report
     counts. Replaces 4-5 discovery calls.
   - `signals-agent-harness-runs-list` (last 7d) — prior scout runs and what they concluded.
   - `signals-agent-harness-memory-list` — durable team steering (known noise, team-confirmed
     patterns, "already addressed" notes).

2. **Pick one or two threads.** Don't fan out. Go where the signal is loudest in the
   profile (`top_events.recent_24h_users` spike, a `signal_source_configs.disabled`
   surprise, an `external_data_sources` failure). See
   [`references/investigation-patterns.md`](references/investigation-patterns.md) for
   common shapes (error bursts, experiment regressions, warehouse stalls, feature-flag
   rollouts, traffic anomalies, popular-insight regressions).

3. **Investigate with concrete queries.** Use the PostHog MCP read tools (`query-trends`,
   `query-funnel`, `error-tracking-issues-list`, `read-data-schema`, `inbox-reports-list`,
   `execute-sql`, etc.) to validate the hypothesis. If the data doesn't support it, drop
   it — do not stretch.

4. **Decide per hypothesis.**
   - **Emit** via `signals-agent-harness-runs-findings-create`. Before your first emit,
     read [`references/finding-schema.md`](references/finding-schema.md) — it covers the
     description prose contract, weight/confidence rubrics, evidence list shape, hypothesis
     wording, severity mapping, and worked examples.
   - **Remember** via `signals-agent-harness-memory-create` to carry forward steering ("issue
     X stayed quiet after 13:22 — treat as already-surfaced if quiet next run") or to record
     what you ruled out and why.
   - **Skip** with a one-line note in your final summary.

   When a prior run already covered the topic, read
   [`references/dedupe-rules.md`](references/dedupe-rules.md) to decide between
   fresh-emit-citing-prior, skip, or remember.

5. **Close out.** End your turn with a one-paragraph summary listing what you looked at,
   what you found, what you ruled out and why. The harness writes that summary to the run
   row as searchable prose.

## Budget discipline

Cheap reads first (profile, runs-list, memory-list — three calls and you have full
orientation). Expensive reads (HogQL aggregations, paths, drill-downs) only after you
have a concrete hypothesis worth validating. If 20 tool calls in you haven't converged,
stop and write a "looked but found nothing meaningful" summary — that's a real outcome,
not a failure.

## Stop early

If the project profile is quiet (no fresh top-events bursts, no failing data sources, no
new inbox reports today, prior runs all empty), stop. The dedupe rules in
[`references/dedupe-rules.md`](references/dedupe-rules.md) cover when memory or recent-run
history says to skip a topic the team already knows about.
