---
name: investigating-logs
description: >
  Investigate logs in a PostHog project: verify a service or deployment is healthy, explain an error spike,
  triage an incident, or understand what a log stream is saying. Use when the user asks to "check the logs",
  asks whether a service, deploy, release, or change is working or broke anything, asks why errors are up or
  what changed, or wants the root cause of failures visible in logs. Routes the logs MCP tools
  (services overview, pattern mining, before/after pattern diffing, bucketed counts, facets, raw rows) so
  investigations start from summaries instead of raw rows or hand-written SQL over the logs table.
---

# Investigating logs

Investigation is a narrowing problem: **summarize before you read**.
One `posthog:logs-patterns` call compresses millions of lines into at most 200 templates,
and one `posthog:logs-patterns-diff` call answers "what is different about now vs. before" directly.
Raw rows (`posthog:query-logs`) are the last step of an investigation, never the first.

## When to use this skill

- "Check the logs" / "is service X healthy?" / "did my deploy (or model bump, config change, migration) break anything?"
- "Why are errors up?" / "explain this spike" / incident triage — "what changed?"
- "What is this service logging?" — orienting in an unfamiliar or noisy stream.
- Finding the log evidence for a failure reported elsewhere (an alert, an error-tracking issue, a user complaint).

## When _not_ to use this skill

- Creating or tuning log alerts — that's `authoring-log-alerts`.
- Analytics over product events, persons, or insights — that's `querying-posthog-data`.
- HogQL exposes a `logs` table via `posthog:execute-sql`, but do not investigate through it:
  hand-written SQL over logs routinely hits read-byte caps and re-derives what the tools below do in one cheap call.
  Reserve SQL for the rare case of joining log-derived facts with non-log data.

## Tools

| Tool                                                                  | Job                                                                                           |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `posthog:logs-services-create`                                        | Top-25 services with log_count, error_count, error_rate, sparkline. Orientation.              |
| `posthog:logs-patterns`                                               | Mine one window's message templates, ordered by frequency. "What is this stream saying?"      |
| `posthog:logs-patterns-diff`                                          | Diff templates between two windows: new / rate-shifted / gone. "What changed?"                |
| `posthog:logs-count` / `posthog:logs-count-ranges`                    | Scalar and time-bucketed counts for a filter. Localize volume before pulling rows.            |
| `posthog:logs-sparkline-query`                                        | Volume over time broken down by severity or service (the one bucketed view with a breakdown). |
| `posthog:logs-facet-values-create`                                    | Distribution of severity/service (or a resource attribute) under a filter.                    |
| `posthog:logs-attributes-list` / `posthog:logs-attribute-values-list` | Discover attribute keys and values before building filters.                                   |
| `posthog:query-logs`                                                  | Raw rows. Endpoint of every drill-down, entry point of none.                                  |

Each tool's own description documents its parameters and response shape — read it before calling.

## Pick the workflow by question shape

### "Is it healthy?" — post-deploy / post-change verification

The user changed something (deploy, model bump, config, migration) and wants to know the logs still look right.

1. Pin down the change time and the affected service(s). Ask if the user hasn't said; the diff is meaningless without a boundary.
2. Orient with `posthog:logs-services-create`: is the service still logging at all, and what is its error_rate now?
   A service that went silent fails verification just as hard as one that started erroring.
3. `posthog:logs-patterns-diff` with `query.dateRange` from the change time to now and `baselineDateRange`
   set to a comparable window just before the change, scoped to `serviceNames`.
   New error/fatal templates right after a change are the classic regression signature;
   large `rate_ratio` shifts on existing error templates are the second thing to check.
4. Check volume continuity with `posthog:logs-count-ranges` spanning before and after the boundary:
   a rate discontinuity (crash loop, restart storm, silence) shows up here even when message content looks unchanged.
5. Drill only the suspects: pivot each suspicious pattern to raw lines via its `match_regex` with `posthog:query-logs`.

A pass verdict needs all three: no new error templates, no large error rate_ratio shifts, and continuous volume.
Say which windows you compared — "healthy" is only as strong as the baseline.

### "Explain this spike"

1. Localize it: `posthog:logs-count-ranges` over the user's window, then recurse into the dense bucket(s) — each bucket's
   `date_from`/`date_to` feeds the next call. Stop after 3–4 levels.
2. Explain it: `posthog:logs-patterns-diff` with the spike as `query.dateRange` and the window just before as
   `baselineDateRange`. The top `new` and `rate_shift` entries are the explanation. Do not mine both windows
   separately and diff by hand — the diff is one call.

### Incident triage — "what broke?"

`posthog:logs-patterns-diff` first: incident window vs. a known-good window just before (or omit the baseline for
same-window-last-week). Suspects are `new` entries and the biggest `rate_ratio` shifts; pivot each to raw lines.
If the failing service is unknown, find it first with `posthog:logs-facet-values-create` faceting `service_name`
under `severityLevels: ["error", "fatal"]`.

### "What is this stream saying?" — unfamiliar service

`posthog:logs-patterns` over the last hour, scoped to the service. Scan templates by `estimated_count` and
non-zero error share in `severity_counts`. Widen the window or add `searchTerm` only if the answer isn't there.

### Known needle — a specific message, attribute, or person

When the target is already precise (an error string, a request id, a distinct_id), skip pattern mining:
discover the right keys with `posthog:logs-attributes-list` / `posthog:logs-attribute-values-list`,
size the result with `posthog:logs-count`, then pull rows with `posthog:query-logs`.

## Rules that keep investigations honest and cheap

- Scope `serviceNames` (or a resource-attribute filter) on every call once the target service is known.
  Unscoped calls scan the whole team's stream and starve the pattern sample budget.
- `posthog:query-logs` requires an explicit `query.dateRange` — omitting it is a 400, not a default window.
- Pattern counts are sampled estimates (`sampled: true`); templates rarer than ~1 in 10,000 rows can be invisible.
  Absence of a rare template is not evidence it stopped.
- Before trusting a wall of `new` entries in a diff, check `baseline.total_count` —
  a tiny or empty baseline (logging only just started) makes everything look new.
- `severityLevels` matches the six canonical lowercase buckets against `severity_text` exactly.
  Zero rows on a severity filter → check the stored values with `posthog:logs-attribute-values-list { key: "severity_text" }`.
- Budget: one services call, at most one patterns-diff per window pair, 3–4 count-ranges levels,
  and `query-logs` only for confirmed suspects with `limit` ≤ 100.

## Output

Lead with the verdict, then the evidence:

- **Verdict**: healthy / regressed / inconclusive, with the windows compared.
- **Suspects** (if any): template, classification (`new` / `rate_shift`), estimated counts or `rate_ratio`, services, and 1–2 sample raw lines.
- **What was checked and what wasn't**: services covered, windows, and any sampling or baseline caveats that limit confidence.

The user should be able to act on the verdict without re-running the investigation.
