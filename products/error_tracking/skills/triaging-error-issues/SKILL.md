---
name: triaging-error-issues
description: >
  Triage PostHog error tracking issues during a daily or on-call review.
  Use when the user asks "what's broken?", "what new errors do we have?",
  "show me top errors today", "what should I look at this morning",
  or wants a prioritized list of active issues to work on. Surfaces new
  and high-impact issues, ranks by users affected and recency, points at
  linked replays, and proposes next actions (investigate, assign, suppress,
  merge).
---

# Triaging error tracking issues

When a user asks "what's broken?" or wants a daily error review, the goal is a short
prioritized list of issues worth a human's attention — not a dump of every active
issue. Most projects have hundreds of active issues; the few that matter are usually
new (first seen in the last 24-48h), spiking, or affecting many distinct users.

## Available tools

| Tool                                        | Purpose                                                                   |
| ------------------------------------------- | ------------------------------------------------------------------------- |
| `posthog:query-error-tracking-issues-list`  | List + rank issues with aggregate metrics (occurrences, users, sessions)  |
| `posthog:query-error-tracking-issue`        | Compact details for a single issue (status, assignee, top frame, release) |
| `posthog:query-error-tracking-issue-events` | Sampled `$exception` events with stack, URL, browser, and `$session_id`   |
| `posthog:query-session-recordings-list`     | Find replays of users hitting an issue                                    |
| `posthog:inbox-reports-list`                | Pre-curated actionable signals if the project uses Inbox                  |

## Workflow

### Step 1 — Pick a window and a signal

Read the time window from the user's wording. Defaults if unspecified:

- "Today" / "this morning" / "right now" → `dateRange: { date_from: "-24h" }`
- "This week" / "since Monday" → `-7d`
- On-call shift handoff → `-24h`

Pick what "matters" means:

- **New issues** — `orderBy: "first_seen"`, `orderDirection: "DESC"`, tight window.
  Catches regressions introduced by recent deploys.
- **High-impact** — `orderBy: "users"` ranks by distinct users affected. Better than
  raw occurrences for severity (one bot loop produces many occurrences but one user).
- **Trending** — `orderBy: "occurrences"` over a short window vs a longer baseline
  to spot spikes.

### Step 2 — Pull the candidate list

Start narrow and widen if too few issues come back:

```json
posthog:query-error-tracking-issues-list
{
  "status": "active",
  "orderBy": "users",
  "orderDirection": "DESC",
  "dateRange": { "date_from": "-24h" },
  "limit": 20,
  "volumeResolution": 24
}
```

Match `volumeResolution` to the window (24 buckets for `-24h`, 14 for `-14d`, etc.)
so each row's sparkline has enough resolution to show a spike vs flat steady state.
A single bucket only gives a total, not a shape.

For new-issues-only, run a parallel query with `orderBy: "first_seen"`:

```json
{
  "status": "active",
  "orderBy": "first_seen",
  "orderDirection": "DESC",
  "dateRange": { "date_from": "-24h" },
  "limit": 10
}
```

If a project mixes browser and server SDKs, the top-by-users list is usually drowned
by server-side errors (each invocation often gets a fresh `distinct_id`). Narrow with
the `library` filter — values match the SDK's `$lib`, not the npm package name, examples:

- `web` — posthog-js (browser)
- `posthog-node`, `posthog-python`, `posthog-ruby`, `posthog-go`, `posthog-php`, `posthog-java`, `posthog-elixir` — server SDKs
- `posthog-edge` — Cloudflare Workers / edge runtime
- `posthog-ios`, `posthog-android`, `posthog-react-native`, `posthog-flutter` — mobile

### Step 3 — Filter the noise

The list will include known noise. Before presenting, drop or call out:

- Issues whose volume is flat over the window — they're not new, the user already
  lives with them. Surface them only if they're in the top by users.
- Bot-only issues — if all events come from headless browsers or crawler user agents,
  flag for suppression (`suppressing-noisy-errors`) instead of triage.

If unsure whether an issue is new vs. recurring, compare `first_seen` to the start
of the window:

- `first_seen` inside the window → new, worth attention
- `first_seen` weeks ago but spiking now → regression worth attention
- `first_seen` weeks ago, flat volume → background noise

### Step 4 — Add context for the top items

For the top 3-5 candidates, pull a sample exception so the summary includes a stack
frame and URL, not just a title. Use `posthog:query-error-tracking-issue-events` rather than
raw SQL — it returns normalized fields (`$exception_types`, `$exception_values`,
`$current_url`, browser/OS, `$session_id`) and defaults to `onlyAppFrames: true` to
strip vendor noise from the stack:

```json
posthog:query-error-tracking-issue-events
{
  "issueId": "<issue_id>",
  "limit": 1,
  "verbosity": "stack"
}
```

If the user wants to see what users were doing, hand off to `finding-replay-for-issue`
to pick the best linked recording. Don't fetch replays for every triaged issue — only
the ones the user asks to dig into.

### Step 5 — Present the triage list

Lead with a one-line headline ("3 new issues in last 24h, 1 spike, 5 active
high-impact"). Then a short table sorted by your chosen signal:

| Issue | First seen | Users | Sessions | Sample message                    | Suggested action           |
| ----- | ---------- | ----- | -------- | --------------------------------- | -------------------------- |
| ...   | 2h ago     | 142   | 198      | `TypeError ... at checkout.js:42` | Investigate                |
| ...   | spike      | 67    | 89       | `Network request failed`          | Watch — likely transient   |
| ...   | 3d ago     | 12    | 12       | `chrome-extension:// timeout`     | Suppress (extension noise) |

For each, suggest one of: **investigate** (`investigating-error-issue`), **assign**
(`error-tracking-issues-partial-update`), **suppress** (`suppressing-noisy-errors`),
**merge** (`grouping-noisy-errors`), or **resolve** if it's already known fixed.

## Tips

- A single deploy often surfaces several related new issues. If multiple new issues
  share a `properties.$lib_version` (or `properties.$exception_releases` when the
  SDK is configured to populate it), present them grouped — a rollback decision
  rests on the cluster, not any one issue.
- "Users" is the right severity proxy for user-facing apps. For backend services
  without a real distinct_id concept, fall back to `sessions` or `occurrences`.
- Don't auto-assign or auto-resolve as part of triage. Present the list and let the
  user decide. Bulk actions belong in dedicated skills.
- If the project uses Inbox (`posthog:inbox-reports-list`), check it first — PostHog
  may have already curated the most actionable issues so you avoid re-deriving them.
- Provide the issue URL (`/error_tracking/<id>`) for each row so the user can jump
  straight to the issue page if they want to drill down themselves.
