---
name: inbox-exploration
description: >
  Explore PostHog's Inbox and act on what it surfaces — the place where signal reports cluster into
  actionable issues and trends. Use when the user asks "what's in my inbox?", "what should I look at?",
  "which reports are actionable?", "what's PostHog flagged recently?", asks about a specific report by
  ID or title, wants to act on / fix / implement a report (turn it into a PR), wants to dismiss or
  snooze a report, or wants to see which signal sources are configured. Covers listing, filtering,
  drilling into, and acting on reports, plus pointers to the deeper `signals` skill when raw signals
  or semantic search are needed.
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
- "Fix this inbox item" / "turn this report into a PR" / "implement this report" — see
  _Workflow: act on an actionable report_
- "Dismiss this" / "snooze this report" — see _Workflow: dismiss or snooze a report_

For deeper investigation, hand off to other skills and tools:

- **`signals` skill** — query `document_embeddings` via HogQL for raw signal text, semantic
  search across signals, or to inspect every signal that contributed to a report.
- **PostHog's product-specific MCP tools** — when a report points at a specific error, log line,
  session, person, or time range, reach for the matching domain tool to pull richer context:
  - Error tracking: `query-error-tracking-issues-list`, `query-error-tracking-issue`,
    `query-error-tracking-issue-events` for error-tracking-sourced reports
  - Logs: `query-logs`, `logs-count-ranges` to find log activity around the issue
  - Session replays: `query-session-recordings-list`, `session-recording-get` to find
    recordings of affected users
  - Persons / activity: `persons-retrieve`, `activity-log-list` to inspect a specific user's
    behavior
  - Trends / SQL: `query-trends`, `execute-sql` for ad-hoc verification queries

A signal report tells you _what_ PostHog clustered. The product-specific tools tell you the
_underlying detail_ — pair them when the user wants to dig in.

## Available tools

| Tool                                  | Purpose                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `inbox-reports-list`                  | Paginated list of reports with filters (status, search, etc.)                                                 |
| `inbox-reports-retrieve`              | Full detail for a single report                                                                               |
| `inbox-report-artefacts-list`         | A report's full work log — `signal_finding` evidence, status judgments, commits, task runs, notes (read-only) |
| `inbox-report-artefacts-retrieve`     | Full detail for a single artefact (read-only)                                                                 |
| `inbox-reports-set-state`             | Dismiss (`suppressed`) or snooze (`potential`) a single report                                                |
| `inbox-reports-bulk-set-state`        | Same transition for 1–100 reports in one call (per-id result)                                                 |
| `inbox-source-configs-list`           | Configured signal sources (which products feed the inbox)                                                     |
| `inbox-source-configs-retrieve`       | Full record for a single source config                                                                        |
| `inbox-source-configs-partial-update` | Toggle a source's `enabled` flag (or adjust its `config`)                                                     |
| `posthog:execute-sql` (signals skill) | HogQL access to underlying signals (read the `signals` skill first)                                           |

The `inbox-reports-*-list` / `-retrieve`, `inbox-report-artefacts-list` / `-retrieve`, and
`inbox-source-configs-*-list` / `-retrieve` tools are read-only. The exposed writes are `inbox-reports-set-state` (dismiss / snooze a single report),
`inbox-reports-bulk-set-state` (the same transition for 1–100 reports in one call) — see
_Workflow: dismiss or snooze a report_ — and `inbox-source-configs-partial-update`, which flips a
source's `enabled` flag on or off (e.g. `{enabled: false}` to stop a source feeding the inbox);
`-create` / `-update` exist too for standing a source up or replacing it wholesale. Other writes
(pause processing, mark a report resolved, set `implementation_pr_url`) are not exposed via MCP
today — those happen on the product surface when a PR is opened against a report.

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
flowing right now. You can re-enable a source directly with
`inbox-source-configs-partial-update { "id": "<source_config_uuid>", "enabled": true }` (confirm
with the user first), or they can flip it on from the project's signals settings. Don't go fishing
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

Returns the full record including `signals_at_run` and `artefact_count`. Then read the report's
work log:

```json
inbox-report-artefacts-list
{ "report_id": "<report_uuid>" }
```

This returns the report's evidence (`signal_finding`), the judgments behind its
status/priority/actionability (`safety_judgment`, `actionability_judgment`, `priority_judgment`,
`repo_selection`, `suggested_reviewers`), and its work-log (`commit`, `task_run`, `note`) — the
curated "why it exists and what's been done" view, in one read-only call.

Use the `signals` skill only when you need the raw signal text beyond the curated findings:

1. Use `inbox-reports-retrieve` to get the report metadata + `id`
2. Use `inbox-report-artefacts-list` for the curated evidence, judgments, and work-log
3. Use the `signals` skill's Example 2 (fetch all signals for a specific report) — pass the
   report ID as `metadata.report_id` in the HogQL query — only for the raw underlying signal text

The layers complement each other: `inbox-report-artefacts-list` gives you the curated/judged view
(evidence + judgments + PR/task-run history), and the `signals` skill lets you inspect the raw
observations that produced it.

## Workflow: act on an actionable report

When the user wants to _do_ something about a report — "fix this inbox item", "turn this into a
PR", "implement this" — not just read it. A `ready` report with
`actionability: immediately_actionable` is the usual candidate. The discipline that matters here:
**a report is a diagnosis, not ground truth — verify it against the actual code before you
implement.** Reports from `signals_scout` (and any LLM-research source) are especially worth
double-checking; their `summary` often reads as a confident root-cause with file and function
names, but it can be stale or wrong.

### Step 1 — Retrieve and check it isn't already handled

```json
inbox-reports-retrieve
{ "id": "<report_uuid>" }
```

Before doing any work, look at:

- `already_addressed` — if `true`, the fix may already be in flight or merged; confirm with the
  user before duplicating it.
- `implementation_pr_url` — if a PR is already linked, surface it instead of opening a second one.
- `status` — only `ready` reports carry a finished judgment. A `candidate` / `pending_input`
  report hasn't been researched yet; don't implement off a half-formed summary.

### Step 2 — Verify the diagnosis against the code (do not skip)

Start by reading the report's work log — its evidence and the judgments behind it:

```json
inbox-report-artefacts-list
{ "report_id": "<report_uuid>" }
```

This surfaces the `signal_finding` evidence, the status/priority/actionability judgments, and any
`commit` / `task_run` history — exactly the "why it exists and what's already been done" you need
before touching code. Then the report's `summary` will name files, functions, and sometimes line
numbers. **Open them and confirm the claim holds** — that the cited code exists, still looks the
way the report describes, and actually produces the described failure. As a deeper fallback, pull
the raw underlying signals via the `signals` skill (`metadata.report_id`) if you need the signal
text behind the curated findings. If the diagnosis doesn't hold up, say so and stop — a wrong
report is itself a useful finding (and a candidate for _dismiss_ below), not a license to write a
speculative fix.

### Step 3 — Scope the fix to the right layer

- If `source_products` includes `signals_scout` and the root cause is in a **scout's own
  behavior** (the prompt it runs, a threshold it uses), the better fix is often the scout's
  `SKILL.md`, not the harness. Note that per-team custom scouts live in the user's Skills Store,
  not this repo, so the fix site may be out of reach of a repo PR — flag that to the user.
- Otherwise treat it like any normal change: follow the repo's conventions (`CLAUDE.md`,
  area-specific skills), make the change minimal, and add a regression test that would have caught
  the reported failure.

### Step 4 — Open the PR and link it back

Open the PR following the repo's PR conventions. There is **no MCP tool to mark a report resolved
or set `implementation_pr_url`** — that link is populated on the product surface when a PR is
opened against the report. So reference the report in the PR description (its `_posthogUrl`) and
tell the user which report the PR addresses, so the loop is traceable. Don't claim the report is
"resolved" in the inbox — it isn't until the product surface records the merged PR.

## Workflow: dismiss or snooze a report

When the user has reviewed a report and wants it gone, or wants to defer it. These are the inbox
writes exposed via MCP:

```json
inbox-reports-set-state
{
  "id": "<report_uuid>",
  "state": "suppressed",
  "dismissal_reason": "analysis_wrong",
  "dismissal_note": "Verified against products/foo/bar.py — the cited code path can't reach this state."
}
```

- `state: "suppressed"` dismisses the report from the inbox; `state: "potential"` snoozes it back
  into the pipeline. When snoozing, `snooze_for: <N>` holds it until it accumulates N more signals.
- `dismissal_reason` must be one of six server-validated canonical codes — `already_fixed`,
  `report_unclear`, `analysis_wrong`, `wontfix_intentional`, `wontfix_irrelevant`, `other` — an
  unlisted value returns `400`. `already_fixed` is a _snooze_, so pair it with `state: "potential"`
  rather than `"suppressed"`; reach for `other` plus a `dismissal_note` for anything that doesn't
  fit a specific code. `dismissal_note` is free-form (≤ 4000 chars). Both persist as a DISMISSAL
  artefact, so the rationale survives even if the report transitions again later — **always include
  them** so a future reader knows _why_.
- It's a destructive, non-idempotent transition and returns `409` if it isn't allowed from the
  report's current status (and `400` if `dismissal_reason` isn't a canonical code). Confirm with
  the user before suppressing, and capture _why_ in the note — a dismissal with no rationale is
  worse than none. A report you dismissed because the diagnosis was wrong (Step 2 above) is the
  textbook case: suppress it with `analysis_wrong` and the evidence in the note.
- To dismiss or snooze several reports at once, use `inbox-reports-bulk-set-state` with an `ids`
  array (1–100). It applies the same `state` / `dismissal_reason` / `dismissal_note` / `snooze_for`
  to every id and returns a per-id `results` list (in request order) plus a
  `transitioned_count` / `skipped_count` / `failed_count` / `not_found_count` summary. Each id is
  processed independently, so the call returns `200` even on partial failure — an id whose
  transition isn't allowed comes back as `skipped` (the single-report `409`) while the rest go
  through. Inspect the per-id outcomes rather than assuming the whole batch succeeded.

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

To turn a source on or off, use `inbox-source-configs-partial-update` with the config's `id` and
`{ "enabled": true | false }` — only the fields you pass change, so this is the right tool for a
plain toggle (`-update` replaces the whole record; `-create` stands up a new source). Confirm with
the user before flipping a source, since enabling one drives signal processing and spend.

```json
inbox-source-configs-partial-update
{ "id": "<source_config_uuid>", "enabled": false }
```

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
- The inbox writes exposed via MCP are `inbox-reports-set-state` (dismiss / snooze one report),
  `inbox-reports-bulk-set-state` (the same for 1–100 reports), and `inbox-source-configs-partial-update`
  (toggle a source's `enabled` flag). To _act_ on a report (implement a
  fix), verify the diagnosis against the code first, then open a
  PR — see _Workflow: act on an actionable report_. Marking a report resolved / setting
  `implementation_pr_url` happens on the product surface, not via MCP; always also surface the
  `_posthogUrl` deep-link
- **Never implement a report's fix straight from its `summary`.** Reports — especially
  `signals_scout` ones — are LLM diagnoses; confirm the cited files / functions / behavior in the
  actual code before writing a fix. A report that doesn't hold up is a dismissal candidate, not a
  fix
- For "what kinds of signals exist?" or "what's been happening recently across all sources?",
  drop into the `signals` skill — the report layer hides individual observations; you need
  HogQL on `document_embeddings` to see them
- Source configs don't have per-record deep-links — they live behind project settings, so
  `inbox-source-configs-retrieve` returns no `_posthogUrl`. Don't confuse them with reports
