# The report channel: `emit-report` / `edit-report`

The report channel is your output: you've already done the research, so you file a full
`SignalReport` into the inbox directly — no weak signals, no pipeline clustering. This reference
is the contract: the two tools, their fields, how to choose between authoring and editing, and the
two behaviors that make this channel different (it isn't idempotent, and the pipeline may later
rewrite what you authored).

> Like every `signals-scout-*` tool, **both report tools require the current `run_id`** (the
> run you're executing in) on every call — omitting it fails validation.

## Author or edit

| You have…                                                                                                       | Use           |
| --------------------------------------------------------------------------------------------------------------- | ------------- |
| A finished, well-formed finding nothing in the inbox covers — filed **1:1** with full control of title/summary. | `emit-report` |
| New information about a report that already exists (one you authored last run, or a pipeline report).           | `edit-report` |

**Always search the inbox first** (`inbox-reports-list` → `inbox-reports-retrieve`): edit an
existing report rather than mint a near-duplicate. An AI observability shift is report-shaped when
it's a single, localized, validated change — one model/product's cost step, one latency band
shifting, one eval silently broken or regressing, one error class firing at scale, one runaway
cluster — that you've corroborated and would stand behind as a standalone inbox item. A scatter of
small, weakly-correlated wobbles across many models or dimensions is not a report — it's a sign you
haven't found the finding yet; keep investigating or record it in the scratchpad and move on.

Filing a report is a **high bar**. Author one only for a finding you'd own end-to-end as an inbox
item a human will act on. When you can't get there, a scratchpad note is the right home — never
file a half-formed report to fill space.

## `emit-report` — author a full report

Judges the report for safety, then persists it at the judged status.

| Field                       | Type                    | Notes                                                                                                                                                                                                                                              |
| --------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_id`                    | string, required        | The current run's id — same as every `signals-scout-*` tool.                                                                                                                                                                                       |
| `title`                     | string, ≤300, non-empty | The inbox headline. One specific, quantified line.                                                                                                                                                                                                 |
| `summary`                   | string                  | The report body prose — hook → pattern → hypothesis → recommendation. See _Writing the summary_ below.                                                                                                                                             |
| `evidence`                  | list, 1–50              | Each `{description, source_id}`. Becomes a bound signal row backing the report. `source_id` is the citable entity id. Hard cap of **50** — summarize/trim before calling; a longer list fails validation before the report is judged or persisted. |
| `actionability_explanation` | string                  | One sentence justifying the actionability call below.                                                                                                                                                                                              |
| `actionability`             | enum                    | `immediately_actionable` / `requires_human_input` / `not_actionable`. You make this call — the channel does not re-research it.                                                                                                                    |
| `already_addressed`         | bool, default `false`   | Set when the underlying issue is already handled and you're filing for the record.                                                                                                                                                                 |
| `suggested_reviewers`       | list of objects         | Each `{github_login}` and/or `{user_uuid}` (**not** a bare string). The **single most important routing field** — set on every report (PR or not). See the _`suggested_reviewers`_ section below for the object shape + resolution steps.          |

**Status is decided for you, from safety × actionability:**

| Safety judge | `actionability`          | Resulting status | Surfaces in inbox? |
| ------------ | ------------------------ | ---------------- | ------------------ |
| safe         | `immediately_actionable` | `READY`          | yes                |
| safe         | `requires_human_input`   | `PENDING_INPUT`  | yes                |
| safe         | `not_actionable`         | `SUPPRESSED`     | no                 |
| unsafe       | (any)                    | `SUPPRESSED`     | no                 |

Note the trap: `not_actionable` is **suppressed** (never surfaces). Reserve it for filing-for-the-record;
if you want a human to see it, it must be `immediately_actionable` or `requires_human_input`.

The result tells you what happened: `report_id` (always set when a report was persisted —
**even when suppressed**, so you can edit or dedup against it), `report_status` (the birth status —
`ready` / `pending_input` / `suppressed`), `emitted` (true only when it actually surfaced),
`safety_explanation`, and `skipped_reason` (set only when a preflight gate — the team's
AI-data-processing approval or the signals-scout source being enabled — stopped the call before any
report was created).

### Writing the `title` and `summary`

The `title` is the inbox headline and the `summary` is the body a human reads to decide whether to
act — write both for a busy reader scanning a feed of other reports.

- **`title`** — one specific, quantified line. Lead with what's wrong, which slice, and the blast
  radius, not a vague category. _"`sonnet` p90 latency jumped from ~19s to ~48s after 14:00 UTC,
  confined to the `posthog_ai` product"_, not _"LLM latency up"_.
- **`summary`** — a tight few paragraphs following hook → pattern → hypothesis → recommendation:
  1. **Hook** — what's happening, quantified ("`$ai_total_cost_usd` for the `code` product rose from
     ~$40/day to ~$210/day between Apr 26–28, while generation count held flat").
  2. **Pattern** — the shape that makes this signal, not noise ("the rise is confined to one
     `ai_product` and one model after a prompt-version bump in the same window; other products' spend
     is flat — a per-product cost regression, not a fleet-wide price change").
  3. **Hypothesis** — your best read of the cause.
  4. **Recommendation** — the concrete action that would resolve it.

Quantify ("~$210/day", "p90 ~48s") over qualitative ("a lot"), and cite entity ids (trace ids,
generation ids, evaluation ids, model/provider names, eval names, cluster ids, prompt versions, time
ranges) inline so a reviewer can pivot straight from prose to source. Put the same citations in
`evidence` so they back the report as bound signals.

### Opening a draft PR (autostart)

First, `suggested_reviewers` is **not** a PR field — set it whenever you can name a plausible owner,
PR or not. It's the routing lever and is covered in its own section below; the three fields in this
section are the **PR-only** ones.

A surfaced, immediately-actionable report can open a draft PR automatically. It's opt-in per report
via these fields; supply them only when the report is a concrete, fixable issue you'd want a PR for.

| Field                  | Type      | Notes                                                                                                                                                                                                                                                    |
| ---------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository`           | string    | `"owner/repo"` targets that repo; the `NO_REPO` sentinel opts out; **omitting it** falls back to free-form selection across the team's repos — the slow path on a many-repo team (it spawns a selection sandbox), so pass `owner/repo` when you know it. |
| `priority`             | `P0`-`P4` | Required for a PR. Pair with `priority_explanation`.                                                                                                                                                                                                     |
| `priority_explanation` | string    | Required when `priority` is set.                                                                                                                                                                                                                         |

Repo selection only runs when you signal PR intent — an explicit `repository`, or both `priority`
and `suggested_reviewers`. A report that supplies none of these just surfaces in the inbox (no repo
sandbox, no PR). Autostart no-ops unless the report is `immediately_actionable`, has a repo +
priority, and a reviewer qualifies — so these three PR fields are safe to omit for an informational
report. `suggested_reviewers` is not: set it whenever you can name a plausible owner (see the next
section), PR or not. An AI observability regression (cost / latency / eval / runaway loop) is almost
always a thing to investigate, not a one-line code fix, so most of these reports want
`requires_human_input` and a reviewer, not a PR.

## `suggested_reviewers` — set it on every report (this is how it reaches a human)

`suggested_reviewers` is the **single most important routing field**. It is how a report reaches the
right person: the inbox orders by `is_suggested_reviewer`, so a reviewer's own reports float to the
top of _their_ inbox even when **no PR** is involved. **A report with an empty `suggested_reviewers`
is assigned to nobody — it lands in the shared inbox and is very likely to be missed.** So resolve and
set at least one reviewer on every report you author, including informational `requires_human_input`
ones.

Each entry is an **object**, not a bare string — `{"github_login": "..."}` and/or
`{"user_uuid": "..."}` (at least one of the two per entry; a list of plain strings like `["octocat"]`
**fails validation**). Pick whichever you resolved:

- **`github_login`** — the GitHub login, case-insensitive (stored lowercased), no `@`, no display name
  (e.g. `{"github_login": "octocat"}`).
- **`user_uuid`** — the PostHog user UUID (e.g. from `org-members-list`); the server resolves it to the
  member's linked GitHub login. Use this when you know the PostHog user but not their handle. A
  `user_uuid` that isn't an org member with a linked GitHub identity is **rejected** (never silently
  dropped), so the reviewer always routes or the call tells you it didn't.

You rarely know either outright, so resolve it — cheapest first:

1. **Scratchpad cache.** A `reviewer:<domain>:<area>` entry you (or a prior run) recorded — reuse it.
   For AI observability, key by the owning product / model area (`reviewer:llm_analytics:<area>`).
2. **Inbox precedent.** `inbox-reports-list` (filter by `source_product` + a free-text `search`) for a
   comparable report on the same product/model/eval, then `inbox-report-artefacts-list` on it — the
   `suggested_reviewers` artefact is where the routed reviewer lives (the report record itself doesn't
   expose it). Reuse that reviewer for the same area.
3. **`org-member-get-github-login`** — the **canonical resolver, available on every run**. Identify the
   owning **person** (by name/email via `org-members-list`, or `@me`), then pass their PostHog user
   UUID to `org-member-get-github-login` to get their linked GitHub login (or just pass the UUID
   straight through as `{"user_uuid": "..."}` and let the server resolve it). It returns null when the
   person hasn't linked a GitHub account — then try the next plausible owner.

**Never guess a handle** — a wrong login mis-assigns the report, which is worse than leaving it open.
If you genuinely can't resolve any confident owner, author the report anyway (it still surfaces) but
treat that as the exception, not the norm. Once you've tied a product/model area to an owner, write a
`reviewer:llm_analytics:<area>` scratchpad entry with the resolved login so the next run routes
instantly.

**On `edit-report`:** `edit-report` **also accepts `suggested_reviewers`** — it replaces the report's
reviewer list (an empty list is a no-op; existing reviewers are never cleared) and re-runs autostart,
so it's the right tool to **route a report that surfaced with no owner**. When a later run resolves an
owner for an orphaned report, `edit-report` it with the reviewer rather than only appending a note.

## `edit-report` — update an existing report

Rewrite `title`/`summary` and/or append a note to a report that already exists. Pass `run_id` and
`report_id`, plus at least one of `title`, `summary`, `append_note`.

`edit-report` can target **any** of the team's inbox reports — not just ones a scout authored. That
makes it the right tool when a later run learns something about a report the pipeline (or another
scout) created. Two rules of good behavior:

- **Prefer `append_note` over rewriting** `title`/`summary` on a report you didn't author. A note is
  additive and audit-friendly (it carries your scout as author); a rewrite silently overwrites a
  human- or pipeline-authored headline.
- **Don't fight an in-flight pipeline.** A report the summary/research workflow is mid-run on can have
  its fields overwritten under you. If a report is actively being worked, append a note rather than
  rewriting.

**A persistent regression is one report, not one per tick.** A cost step that's still elevated, a
latency band that hasn't recovered, an eval still failing more: when a new complete window confirms
the same issue is ongoing, `append_note` the fresh window onto the report your
`report:llm_analytics:<entity>` pointer names — don't author a fresh report each run. But
`edit-report` **can't change status**, so appending to a `resolved` / `suppressed` / `failed` report
(one that won't surface in the inbox) buries a real relapse under a closed item. Check the matched
report's status first: when it's no longer live, **author a fresh report** for the relapse and
repoint the `report:llm_analytics:<entity>` scratchpad key at the new id.

## Dedup: the channel is NOT idempotent

`emit-report` is **not idempotent** — a retried call authors a _second_ report. There is no
server-side dedup key. The dedup story is two-sided and you own it:

1. **Before authoring**, `inbox-reports-list` for a prior report on the same topic (filter by
   `search` / `status`). Pass `ordering=-updated_at` — the default ordering buckets by your own
   reviewer-match and status first, so without it the most recent duplicate can sort below older rows
   and you'd miss it. **Don't filter `source_product=llm_analytics`:** your own report-channel reports
   persist their backing signals under `source_product=signals_scout`, so a `llm_analytics` filter
   matches none of them — omit it, or use `signals_scout`. Found a match? `edit-report` it instead of
   authoring a new one.
2. **After authoring**, write a `report:llm_analytics:<entity>` scratchpad entry recording the
   `report_id` so the next run finds it (via `inbox-reports-retrieve`) without a title-search guess.

**Never retry an `emit-report` / `edit-report` call that may have succeeded** — a transport error
after the write commits, retried, double-files. If unsure whether a call landed, `inbox-reports-list`
to check before retrying.

## The pipeline may rewrite what you authored (accepted)

An authored report is a first-class report that coexists with pipeline reports. When future signals
consolidate around the same topic, the pipeline may **re-promote and re-research the report,
overwriting your authored `title`/`summary`**. This is accepted behavior, not a bug — there is no
pin. Author the finding, and let the inbox stay the source of truth for how it's currently framed.
Your durable record of "I filed this" is the `report:` scratchpad entry and the `report_id`, not the
title text.
