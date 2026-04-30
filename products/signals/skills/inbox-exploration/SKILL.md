---
name: inbox-exploration
description: >
  Explore PostHog's Inbox — the surface where signal reports surface as actionable issues and trends.
  Use when the user asks "what's in my inbox?", "what should I look at?", "which reports are actionable?",
  "what's PostHog flagged recently?", asks about a specific report by ID or title, or wants to see
  which signal sources are configured. Covers listing, filtering, and drilling into reports, plus
  pointers to the deeper `signals` skill when raw signals or semantic search are needed.
---

# Exploring the Inbox

The **Inbox** is where PostHog surfaces signal reports — clusters of related observations
(signals) that have been aggregated into a single issue or trend (e.g. "Error rate spiked 3× on
/checkout"). Reports come from multiple source products: error tracking, session replay, web
analytics, experiments, and integrations like Linear, GitHub, and Zendesk.

The Inbox lives at `/inbox` in the PostHog UI; this skill is the agent-facing equivalent.

**Inbox is new** — many users haven't set it up yet. Don't assume an inbox has reports, or that any
signal sources are configured. The first workflow below tells you how to detect this and what to
say. Always handle the empty / unconfigured case **before** trying to fulfil the user's request.

## When to use this skill

- "What's in my inbox?" / "What should I look at first?"
- "Show me actionable reports" / "What's PostHog flagged recently?"
- "Are there any reports about <topic / product area>?"
- "What signal sources are configured for this project?"
- The user pastes an Inbox URL (`/inbox/<report_id>`) and wants context

For deeper investigation of the underlying signals — semantic search across signal text, fetching
every signal that contributed to a report, or listing signal types — hand off to the **`signals`**
skill, which queries the `document_embeddings` ClickHouse table via HogQL.

## Available tools

| Tool                                  | Purpose                                                             |
| ------------------------------------- | ------------------------------------------------------------------- |
| `inbox-reports-list`                  | Paginated list of reports with filters (status, search, etc.)       |
| `inbox-reports-retrieve`              | Full detail for a single report                                     |
| `inbox-source-configs-list`           | Configured signal sources (which products feed the inbox)           |
| `inbox-source-configs-retrieve`       | Full record for a single source config                              |
| `posthog:execute-sql` (signals skill) | HogQL access to underlying signals (read the `signals` skill first) |

All four `inbox-*` tools are read-only. Writes (pause processing, change source configs, manage
per-user autonomy) are intentionally not exposed via MCP today.

## Report filters at a glance

`inbox-reports-list` accepts these filters (combine as needed):

| Filter                | Values                                                                                                     | Notes                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `status`              | comma-separated: `potential`, `candidate`, `in_progress`, `pending_input`, `ready`, `failed`, `suppressed` | Defaults to all except `suppressed`                                      |
| `search`              | free-text                                                                                                  | Case-insensitive substring match against title and summary               |
| `source_product`      | comma-separated, e.g. `error_tracking,session_replay,linear`                                               | Reports kept if any contributing signal comes from a listed product      |
| `suggested_reviewers` | comma-separated PostHog user UUIDs                                                                         | Reports kept if their suggested reviewers include any of the given users |
| `ordering`            | comma-separated field list, `-` prefix for descending                                                      | Default: `-is_suggested_reviewer,status,-updated_at`                     |

Status meaning (most relevant first):

- `ready` — judgment finished, actionable assessment available
- `pending_input` — waiting on user input to proceed
- `in_progress` — actively being summarized / judged
- `candidate` / `potential` — accumulated signals but not yet promoted
- `failed` — processing errored
- `suppressed` — manually hidden, not surfaced by default

## Workflow: handling an empty or unconfigured inbox (read first)

Run this check whenever a user asks about the inbox for the first time in a session, **or** any
time `inbox-reports-list` returns `count: 0`. The diagnosis decides what to say next.

### Step 1 — Look at source configs

```json
inbox-source-configs-list
{ "limit": 50 }
```

Three meaningful cases:

**Case A — no source configs at all (`count: 0`)**

The user hasn't onboarded to Inbox / signals. **Don't pretend the inbox has data.** Tell the user
plainly that Inbox needs signal sources to be set up first, and that the recommended way to do
this is to install **PostHog Code** at <https://posthog.com/code>. Example response:

> Your project doesn't have any signal sources configured yet, so the Inbox is empty. Inbox surfaces
> issues and trends that PostHog automatically clusters from sources like error tracking, session
> replay, GitHub, Linear, and Zendesk. The fastest way to set this up is to install
> [PostHog Code](https://posthog.com/code) — once it's connected, signals will start flowing in
> and reports will appear in your inbox over the next day or so.

Stop here unless the user wants to discuss setup. Don't run further inbox tools — they'll all be
empty.

**Case B — source configs exist but all are `enabled: false`**

Sources have been set up at some point but are currently turned off. Tell the user no signals are
flowing right now and point them at the project's signals settings to re-enable. Don't go fishing
for reports — anything still there is stale.

**Case C — at least one source config is `enabled: true`**

Setup looks healthy. If `inbox-reports-list` still returns nothing, it's most likely "give it time"
— signals are flowing but nothing has clustered into a report yet. Tell the user that, briefly
list which sources are active (e.g. "you have GitHub and error tracking enabled"), and offer to
check back later or to drop into the `signals` skill to look at raw signal volume.

If any source config has `status: "failed"`, surface that as part of your reply — that source
isn't producing signals right now, which may explain a thin inbox.

### Step 2 — Only then proceed to the user's actual question

If Step 1 found a healthy setup and at least one report exists, continue with the triage / drill /
filter workflows below.

## Workflow: triage what's actionable

When the user asks "what should I look at?" or "what's actionable?":

### Step 1 — Pull the ready/in-progress queue

```json
inbox-reports-list
{
  "status": "ready,in_progress,pending_input",
  "limit": 20
}
```

Default ordering surfaces the user's own suggested reports first, then by status, then most
recently updated — which matches how the UI prioritizes.

If `count: 0` comes back, jump to the empty/unconfigured workflow above before saying "your
inbox is empty" — the right reply depends on whether sources are configured.

### Step 2 — Summarize by source and actionability

For each report, the response includes:

- `id`, `title`, `summary`
- `status`, `priority`, `actionability` (note: `null` for reports still in `pending_input` /
  `candidate` — judgment hasn't run yet)
- `signal_count`, `total_weight` — how much underlying evidence drove the report
- `source_products` — which product(s) the underlying signals came from
- `is_suggested_reviewer` — whether the current user is a suggested reviewer
- `implementation_pr_url` — if a PR has been opened against this report
- `_posthogUrl` — deep-link into the UI; **always include this in your response**

Group the results so the user can scan quickly:

```text
## Inbox — 8 actionable reports

🔴 High priority (3)
- Checkout error rate spiked 3× — error_tracking, 47 signals
  /inbox/<id>
- Session replays on /pricing show repeated rage clicks — session_replay, 12 signals
  /inbox/<id>
…

🟠 Medium priority (4)
…

🟡 Suggested for you (1)
…
```

### Step 3 — Offer the drill-down

End with a clear hand-off: "Want me to dig into the checkout errors?" → call
`inbox-reports-retrieve` for the full report, then optionally hop to the `signals` skill to look
at the underlying signal text.

## Workflow: drill into a specific report

When the user pastes an Inbox URL or report ID:

```json
inbox-reports-retrieve
{ "id": "<report_uuid>" }
```

Returns the full record including `signals_at_run` and `artefact_count`. Combine this with the
`signals` skill if the user wants to see the actual signal contents:

1. Use `inbox-reports-retrieve` to get the report metadata + `id`
2. Use the `signals` skill's Example 2 (fetch all signals for a specific report) — pass the
   report ID as `metadata.report_id` in the HogQL query

The two layers complement each other: the `inbox-*` tools give you the curated/judged view, and
the `signals` skill lets you inspect the raw observations that produced it.

## Workflow: filter by topic or source

"Are there any reports about <topic>?" — start with `search`:

```json
inbox-reports-list
{
  "search": "checkout",
  "status": "ready,in_progress,pending_input",
  "limit": 20
}
```

`search` matches title and summary. If the user is asking about a product area rather than a
keyword, use `source_product`:

```json
inbox-reports-list
{
  "source_product": "session_replay,error_tracking",
  "limit": 20
}
```

If the keyword search returns nothing meaningful, hand off to the `signals` skill — semantic
search over signal text via `embedText()` will catch reports the keyword filter missed.

## Workflow: review configured sources

When the user asks "which signal sources are set up?" or "is <product> hooked up?":

```json
inbox-source-configs-list
{ "limit": 50 }
```

Each entry returns `id`, `source_product`, `source_type`, `enabled`, `status`, plus timestamps.
For full details (including the per-source `config` JSON — recording filters, evaluation IDs,
etc.):

```json
inbox-source-configs-retrieve
{ "id": "<source_config_uuid>" }
```

Integration credentials live in a separate `Integration` model — they are **not** in the
`config` blob, so it's safe to summarize the contents back to the user.

The `status` field reflects the underlying data import or workflow:

- `running` / `completed` — feeding signals normally
- `failed` — the source isn't currently producing signals; flag this to the user

## Tips

- **Check setup before assuming the inbox is empty.** If `inbox-reports-list` returns `count: 0`,
  call `inbox-source-configs-list` first — no sources means the user needs to install
  [PostHog Code](https://posthog.com/code) to start receiving signals; sources-but-no-reports
  means signals are flowing but nothing has clustered yet
- **Always surface `_posthogUrl`** so the user can click through to the UI
- The default ordering already prioritizes the user's suggested reports — don't reorder unless
  asked
- `priority` and `actionability` are `null` for reports still in `pending_input` or `candidate`
  status; this is expected, not a bug — judgment hasn't run yet
- `suppressed` reports are excluded by default; pass `status: "suppressed"` explicitly if the
  user wants to see hidden items
- Don't try to write to the inbox via MCP — destroy / state changes / reingest endpoints are
  intentionally not exposed. If the user wants to act on a report, point them at the UI link
- For "what kinds of signals exist?" or "what's been happening recently across all sources?",
  drop into the `signals` skill — the report layer hides individual observations; you need
  HogQL on `document_embeddings` to see them
- Source configs do not have a per-record deep-link in the UI — they live behind project
  settings. Don't confuse them with reports
