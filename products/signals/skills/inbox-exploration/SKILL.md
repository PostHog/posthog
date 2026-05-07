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

Inbox is part of [PostHog Code](https://posthog.com/code), PostHog's agentic surface for
engineering teams.

Don't assume the user's project has reports, or that any signal sources are configured — plenty
of projects don't have Inbox set up. Always run the setup-check workflow below before answering
the user's actual question.

## When to use this skill

- "What's in my inbox?" / "What should I look at first?"
- "Show me actionable reports" / "What's PostHog flagged recently?"
- "Are there any reports about <topic / product area>?"
- "What signal sources are configured for this project?"
- The user pastes a report ID or URL and wants context

For deeper investigation, hand off to other skills and tools:

- **`signals` skill** — query `document_embeddings` via HogQL for raw signal text, semantic
  search across signals, or to inspect every signal that contributed to a report.
- **PostHog's product-specific MCP tools** — when a report points at a specific error, log line,
  session, person, or time range, reach for the matching domain tool to pull richer context:
  - Error tracking: `query-error-tracking-issues`, `error-tracking-issues-retrieve` for
    error-tracking-sourced reports
  - Logs: `query-logs`, `logs-count-ranges` to find log activity around the issue
  - Session replays: `query-session-recordings-list`, `session-recording-get` to find
    recordings of affected users
  - Persons / activity: `persons-retrieve`, `activity-log-list` to inspect a specific user's
    behavior
  - Trends / SQL: `query-trends`, `execute-sql` for ad-hoc verification queries

A signal report tells you _what_ PostHog clustered. The product-specific tools tell you the
_underlying detail_ — pair them when the user wants to dig in.

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

## Terminology

What each report status means (in roughly the order a triage agent should care about):

- `ready` — judgment finished, actionable assessment available
- `pending_input` — waiting on user input to proceed
- `in_progress` — actively being summarized / judged
- `candidate` / `potential` — accumulated signals but not yet promoted to a real report
- `failed` — processing errored
- `suppressed` — manually hidden; not surfaced by default

By default `inbox-reports-list` excludes `suppressed` reports and orders results by
`-is_suggested_reviewer,status,-updated_at` — the user's own suggested reports first, then by
status, then most recently updated. Refer to the tool's input schema for filter mechanics.

## What "suggested reviewer" means

`is_suggested_reviewer: true` on a report means **the current PostHog user is one of up to
three people the report-research flow flagged as best-placed to act on this report**. It is
the strongest signal you have that a report matters to the user _personally_, and you should
lean on it when triaging.

How the flag is produced (see `report_generation/resolve_reviewers.py`):

1. While researching a report, the agent identifies the GitHub commits most relevant to the
   underlying signals (e.g. commits that touched the failing code path).
2. It fetches the authors of those commits, weights earlier/more-relevant commits more
   heavily, and keeps the top three GitHub logins. These get persisted as a
   `SUGGESTED_REVIEWERS` artefact on the report.
3. At read time, those GitHub logins are mapped back to PostHog users via each org member's
   linked GitHub identity (social auth or GitHub integration). If the _current_ viewer's
   linked GitHub login is one of them, `is_suggested_reviewer` flips to `true` for that
   report.

Practical implications for triage:

- A `true` value means "you wrote (or recently touched) the code this report is about" — not
  "you were assigned this." It's heuristic, not authoritative.
- A `false` value doesn't mean the report is irrelevant — it can mean (a) someone else owns
  the code, (b) no one in the org has a linked GitHub account matching the suggested logins,
  or (c) the source material wasn't tied to a specific repo / commits.
- If the user asks "what should _I_ look at?", lead with `is_suggested_reviewer: true`
  reports — these are the ones where the user's name is on the relevant code. Mention the
  rest as a secondary group rather than mixing them in.
- If the user has _no_ suggested reports but the inbox isn't empty, say so explicitly
  ("nothing in the inbox is tied to code you've authored recently") rather than pretending
  the top of the list is personalized.

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

If `count: 0` comes back, jump to the empty/unconfigured workflow above before saying "your
inbox is empty" — the right reply depends on whether sources are configured.

### Step 2 — Summarize by source and actionability

For each report, the response includes:

- `id`, `title`, `summary`
- `status`, `priority`, `actionability` (note: `null` for reports still in `pending_input` /
  `candidate` — judgment hasn't run yet)
- `signal_count`, `total_weight` — how much underlying evidence drove the report
- `source_products` — which product(s) the underlying signals came from
- `is_suggested_reviewer` — whether the current user is a suggested reviewer for this
  report (see "What 'suggested reviewer' means" above — it's based on GitHub commit
  authorship of the relevant code, mapped to PostHog users via linked GitHub identity)
- `implementation_pr_url` — if a PR has been opened against this report
- `_posthogUrl` — clickable deep-link to the report; **always include this in your response**

Group the results so the user can scan quickly. **Lead with reports where
`is_suggested_reviewer: true`** — those are the ones tied to code the current user has
authored — and only then fall back to priority groupings for the rest:

```text
## Inbox — 8 actionable reports

⭐ Suggested for you (1)
- Checkout error rate spiked 3× — error_tracking, 47 signals (you're a suggested reviewer)
  <_posthogUrl>

🔴 High priority (2 more)
- Session replays on /pricing show repeated rage clicks — session_replay, 12 signals
  <_posthogUrl>
…

🟠 Medium priority (4)
…
```

If no reports come back with `is_suggested_reviewer: true`, say so explicitly before listing
the rest — don't silently drop the section.

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
- **Always surface `_posthogUrl`** so the user can click through to the report
- The default ordering already prioritizes the user's suggested reports — don't reorder unless
  asked
- `priority` and `actionability` are `null` for reports still in `pending_input` or `candidate`
  status; this is expected, not a bug — judgment hasn't run yet
- `suppressed` reports are excluded by default; pass `status: "suppressed"` explicitly if the
  user wants to see hidden items
- Don't try to write to the inbox via MCP — destroy / state changes / reingest endpoints are
  intentionally not exposed. If the user wants to act on a report, point them at the
  `_posthogUrl` deep-link
- For "what kinds of signals exist?" or "what's been happening recently across all sources?",
  drop into the `signals` skill — the report layer hides individual observations; you need
  HogQL on `document_embeddings` to see them
- Source configs don't have per-record deep-links — they live behind project settings, so
  `inbox-source-configs-retrieve` returns no `_posthogUrl`. Don't confuse them with reports
