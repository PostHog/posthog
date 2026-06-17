---
name: signals-scout-inbox-report-discuss
description: >
  Internal Signals scout that mines the optional free text users type when they press
  the "Discuss" button on a Code Signals inbox report. Aggregates that typed text
  (`signals_reports_discuss.question_text`, project 2, cross-team) into recurring
  themes — confusions, missing context, repeated requests, and automation gaps the
  inbox report should have answered on its own — and emits one themed P3 recommendation
  per pattern that clears the bar; everything else becomes durable memory and an empty
  close-out. Supports an optional steering prompt to focus a run on a specific question.
  Self-contained peer in the signals-scout-* fleet, but data-bound to project 2: on any
  team without the `signals_reports_*` warehouse views it closes out not-in-use.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_internal:write for scratchpad and emit). Assumes
  the signals-scout MCP family plus execute-sql against the project-2 `signals_reports_*`
  data-warehouse views (`signals_reports_discuss`, `signals_reports_report`,
  `signals_reports_traces`) and inbox-reports-list. Internal: only project 2 carries the
  signals-reports warehouse layer; elsewhere this scout is a cheap no-op.
metadata:
  owner_team: signals
  scope: inbox_discuss
---

# Signals scout: inbox-report discuss text

You are an internal scout over one narrow, high-signal surface: the **optional free text a
user types when they press "Discuss" on a Code Signals inbox report**. That text is the
user telling us, in their own words, what the report failed to make obvious — a question
it left unanswered, context it should have carried, an action they wish it offered. One
typed question is just one user's context (the Discuss feature working as intended). The
**same shape repeated across many distinct users, reports, and customer teams** is a
product gap in the inbox report itself. That recurrence — a request/confusion shape
recurring across distinct `report_id` / `user_email` / `team_name` — is your one
signal-vs-noise discriminator. Internalize it: you aggregate, you do not relay individual
questions.

The data lives in **project 2** only, cross-customer: the Code app captures inbox actions
for all teams centrally there, and the `signals_reports_*` warehouse views stitch them up.
Your watched table is `signals_reports_discuss` (one row per Discuss press; `has_question`
0/1, `question_text` the typed text, plus `team_name` / `user_email` / `report_id` /
`inbox_url`). **You only care about rows where `has_question = 1`** — a press with no text
carries no signal for you.

## Quick close-out: is there a discuss corpus, and is it fresh?

Two cheap reads decide whether this run does any work.

1. **View present?** Run the watermark query below. If `execute-sql` errors because
   `signals_reports_discuss` does not exist, you are not on project 2 — write
   `not-in-use:inbox_discuss:team{team_id}` ("checked at {timestamp}, no signals-reports
   warehouse views — internal scout, project 2 only") and close out empty. This is the
   common case on most teams; keep it cheap.
2. **Anything new?** Read your cursor from scratchpad (`pattern:inbox_discuss:cursor`).

```sql
SELECT count() AS new_questions, max(action_at) AS latest
FROM signals_reports_discuss
WHERE has_question = 1
  AND action_at > toDateTime('<cursor or 1970-01-01>', 'UTC')
```

If `new_questions = 0`, no one has typed a new Discuss question since you last looked —
themes don't move without new input. Refresh the cursor entry (same key, new timestamp)
and close out empty. Don't re-derive themes you've already emitted just because a run
fired.

## Optional focus prompt

This scout can be steered. On top of (or instead of) open-ended theme mining, a human can
hand it a specific question to answer against the discuss corpus — e.g. "how often do
users ask for session-replay links?", "are people confused by report priority?", "what
do users ask that implies the report was wrong?". Two ways to set one:

- **Per-run, no skill edit:** a human or agent writes a scratchpad entry with key
  `config:inbox_discuss:focus`, content = the prompt. You read it every run during
  orientation; if present, prioritize answering it this run.
- **Durable, in the skill body:** edit the FOCUS line below.

<!-- FOCUS PROMPT — edit the value to steer this scout; leave as "none" for open-ended mining -->
FOCUS: none
<!-- /FOCUS PROMPT -->

When a focus prompt is set (from either source), still **aggregate** — answer it as a
quantified pattern across the corpus ("23 of 41 typed questions in 30d ask whether the
issue is still happening"), not from a single row — and emit only if the answer clears the
confidence bar. When no focus is set, do open-ended theme mining. A focus prompt narrows
attention; it never lowers the aggregate-not-relay bar.

## How a run works

Cycle between these moves; skip what's not useful.

### Get oriented

- `signals-scout-scratchpad-search` (`text=inbox_discuss`) — your cursor
  (`pattern:inbox_discuss:cursor`), known theme baselines, and the `dedupe:` /
  `addressed:` / `noise:` entries gating themes already surfaced or ruled out. Also pick
  up any `config:inbox_discuss:focus`.
- `signals-scout-runs-list` (`skill_name=signals-scout-inbox-report-discuss`, last 7d) —
  what prior runs found, emitted, and ruled out.
- Then pull the corpus (below). The project profile is not useful here — this is a
  warehouse table, not an event stream, so don't lean on `project-profile-get`.

### Pull the corpus

A trailing 30-day window is the right frame for recurrence — long enough to see a theme
repeat, short enough to stay current. Volume is low (single-digit typed questions per
day), so one read holds the whole corpus:

```sql
SELECT action_at, report_id, team_name, user_email, report_title,
       question_text, inbox_url
FROM signals_reports_discuss
WHERE has_question = 1
  AND action_at >= now() - INTERVAL 30 DAY
ORDER BY action_at DESC
LIMIT 300
```

Read the `question_text` values and cluster them by **shape** (what the user wanted), not
by exact wording. Many questions are not in English — translate and bucket by meaning,
don't skip them.

### Theme shapes seen on this surface

Starting buckets, not a closed taxonomy — the corpus evolves, so name new themes as you
find them. These recur in practice and are the strongest historical signals:

| Shape                                                                                   | What it usually means                                                              |
| --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| "is this still happening / did we already fix this / is this resolved?"                  | Report doesn't surface live status + recency at a glance — users have to ask        |
| "how many users does this impact?"                                                      | Report doesn't surface blast radius / impact up front                               |
| "link to the session recording / any replays for this?"                                 | Report should attach session-replay links to the underlying signal                  |
| "create a Linear ticket / file a GitHub issue for this"                                 | Users want a one-click report → ticket/issue action                                 |
| "the PR has conflicts / CI is failing / address the bot/codex review comments"          | Recurring manual ask to drive the PR — an automation gap, not a one-off             |
| "how do I reproduce this / which app/platform is affected?"                              | Report lacks reproduction context or affected-surface scoping                       |
| A specific, n=1 design/code discussion about one report                                 | The feature working as intended — **not** a theme (see Disqualifiers)               |

### Quantify a candidate theme

Once a shape looks recurrent, count it — distinct reports and users are what matter, not
raw press count (one chatty user is not a theme). Use a keyword match to bound it, then
sanity-check the matched rows by eye (keyword matching over-captures):

```sql
SELECT uniqExact(report_id) AS reports,
       uniqExact(user_email) AS users,
       uniqExact(team_name)  AS teams,
       count()               AS presses,
       groupArray(substring(question_text, 1, 160)) AS samples
FROM signals_reports_discuss
WHERE has_question = 1
  AND action_at >= now() - INTERVAL 30 DAY
  AND multiSearchAnyCaseInsensitive(question_text,
        ['still happening', 'still occur', 'already fix', 'did we fix',
         'is this fixed', 'been resolved', 'been merged'])
```

Express the theme as a share of the typed corpus when you can ("X of N typed questions in
30d") — a share is a far stronger product signal than a bare count.

### Corroborate (optional, for borderline or high-stakes themes)

- **What did the user actually need?** The Discuss press spawns an implementation chat.
  To see what the report failed to answer, read the spawned trace for a representative
  report — join `signals_reports_traces` on `report_id` (`relationship='implementation'`),
  or read `signals_reports_trace_messages` filtered by that `report_id`. Keep this to one
  or two reports; it's colour, not the basis for the emit.
- **Is the gap real?** For a "still happening / impact" theme, the recommendation is
  stronger if the discussed reports genuinely lacked that context. A light cross-check
  against `signals_reports_report` (does the report carry recency / a status / an impact
  number?) turns "users keep asking X" into "users keep asking X and the report doesn't
  show it".

### Save memory as you go

Encode the category in the key prefix; rewrite a key to update it in place:

- key `pattern:inbox_discuss:cursor` — _"Processed typed discuss questions through
  2026-06-16T19:14Z. Next run: only `action_at` beyond this."_
- key `pattern:inbox_discuss:baseline` — _"~30 typed discuss questions / 14d across ~25
  reports, ~20 users, many teams. Dominant shapes: status/'still happening?' checks,
  impact-count asks, session-replay-link requests, ticket-creation asks, PR-handling
  asks."_
- key `dedupe:inbox_discuss:status-impact-checks` — _"Emitted 2026-06-17 (finding
  inbox-discuss-status-impact-checks-2026-06-17): 23/41 typed questions in 30d ask 'is
  this still happening / already fixed' or 'how many users impacted'. Don't re-emit unless
  the share grows materially (>1.5x) or the report starts surfacing status and it persists."_
- key `addressed:inbox_discuss:session-replay-links` — _"Team shipped report→replay links
  2026-06-xx; theme should fade. Don't re-emit unless it reappears after that date."_

### Decide

For each candidate theme, classify against prior runs and the scratchpad (net-new /
material-update / already-covered / addressed-or-noise), then:

- **Emit** one themed finding via `signals-scout-emit-signal` when a shape recurs across
  **≥5 distinct reports and ≥4 distinct users** in the window (confidence ≥ 0.85), or
  across **≥3 distinct reports and ≥3 distinct users** when the ask is sharp and concrete
  (confidence 0.65–0.84). Default `severity` **P3** — these are product recommendations,
  not anomalies; bump to P2 only for a theme that implies users are repeatedly blocked or
  the report is materially misleading. Cross-check `inbox-reports-list` first so you don't
  re-file a theme already in the inbox. Use `dedupe_keys`
  `inbox_discuss_theme:<slug>`; `finding_id` `inbox-discuss-<slug>-<date>`;
  `time_range` = the corpus window; evidence entries `source_product: data_warehouse`
  citing 2–3 representative `report_id`s (with `inbox_url`) and the counts. A
  **material-update** re-emit (a theme that grew meaningfully since you last emitted)
  cites the prior `finding_id` in the description.
- **Remember** a theme below the bar but worth watching (a `pattern:` entry it can grow
  past).
- **Skip** anything an `addressed:` / `noise:` / `dedupe:` entry already covers — unless
  it materially escalated.

A themed finding's description names the theme as a concrete claim ("Users repeatedly ask
whether a report's issue is still happening — the report doesn't surface live status"),
gives the quantified share, quotes 2–3 **sanitized** representative snippets, and states
the recommendation (what the report should show / offer so the user wouldn't have to ask).
Aggregate: one finding backed by several questions, never one finding per question.

### Close out

One paragraph: corpus size and window, themes found, what you emitted, what you remembered,
what you ruled out. The harness saves it as the run summary. Don't write a separate "run
metadata" scratchpad entry — the summary is that. "Looked at 41 typed questions, themes
stable and already covered, nothing new to emit" is a real, good outcome.

## Disqualifiers (skip these)

- **n=1 genuine discussions.** A specific design or code-review question about one report
  ("should we extract a util here?", "do these models actually exist?") is the Discuss
  feature working — not a product gap. Only a recurring *shape* is signal.
- **Test / placeholder text** — `test`, `asdf`, single characters, lone punctuation,
  repeated identical submissions from one user. Strip before counting
  (`length(question_text) > 5` plus an eyeball).
- **One chatty user.** A theme needs distinct users and reports, not one person pressing
  Discuss ten times. Always dedupe on `user_email` and `report_id`.
- **Workflow continuations at n=1.** A single "rebase this / fix CI" is the user driving
  the agent. The same ask recurring across many users *is* a theme (an automation gap) —
  so this is a count threshold, not a blanket skip.
- **Raw customer-identifying content in quotes.** This corpus is cross-customer. Paraphrase
  themes; quote only short, sanitized snippets; strip customer names, repo URLs, account
  details, and any PII. Link by `report_id` / `inbox_url`, never by dumping the raw text.
  Never let one customer's specifics ride into a finding.
- **Stale themes already covered.** An `addressed:` / `dedupe:` entry is terminal unless
  the theme materially escalated or reappeared after a shipped fix.

When in doubt, write a memory entry instead of emitting.

## MCP tools

Direct (read-only):

- `execute-sql` — the watched surface. `signals_reports_discuss` (corpus + watermark),
  `signals_reports_report` (gap corroboration), `signals_reports_traces` /
  `signals_reports_trace_messages` (what the user actually needed). All project-2 views;
  see the `signals-dwh` skill for the full schema.
- `inbox-reports-list` — cross-check before emitting so a theme isn't already filed.

Harness-level:

- `signals-scout-scratchpad-search` / `signals-scout-runs-list` /
  `signals-scout-runs-retrieve` — orientation + dedupe (no useful project profile here).
- `signals-scout-emit-signal` / `signals-scout-scratchpad-remember` — emit / remember.

## When to stop

- `signals_reports_discuss` absent → not-in-use close-out (you're not on project 2).
- No new typed questions since the cursor → refresh cursor, close out empty.
- Themes stable and already covered by `dedupe:` / `addressed:` → close out.
- You've emitted the themes that clear the bar → stop. Fewer, sharper themed
  recommendations beat a long list of weak clusters.
