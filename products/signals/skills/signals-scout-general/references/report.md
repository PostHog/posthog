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
existing report rather than mint a near-duplicate. As the cross-product generalist, your natural
fit is the **fully-validated cross-product correlation** — one finding you've corroborated across
surfaces and would stand behind as a standalone inbox item. A scatter of small, weakly-correlated
observations is not a report — it's a sign you haven't found the finding yet; keep investigating or
record it in the scratchpad and move on.

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

- **`title`** — one specific, quantified line. Lead with what's wrong and the blast radius, not a
  vague category. _"Checkout 500s spiked to 8% of sessions after the 14:00 deploy — ~1,200 users
  affected"_, not _"Checkout errors"_.
- **`summary`** — a tight few paragraphs following hook → pattern → hypothesis → recommendation:
  1. **Hook** — what's happening, quantified ("error rate on the checkout funnel jumped from ~0.5%
     to 8% of sessions between 14:00 and 15:30 UTC").
  2. **Pattern** — the shape that makes this signal, not noise ("the step that broke is the same one
     a feature flag flipped at 14:00, and the errors are confined to users in that flag's rollout").
  3. **Hypothesis** — your best read of the cause.
  4. **Recommendation** — the concrete action that would resolve it.

Quantify ("~1,200 users") over qualitative ("many users"), and cite entity ids (issue ids, recording
ids, dashboard short_ids, flag keys) inline so a reviewer can pivot straight from prose to source.
Put the same citations in `evidence` so they back the report as bound signals.

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
section), PR or not.

## `suggested_reviewers` — set it on every report (this is how it reaches a human)

`suggested_reviewers` is the **single most important routing field**. It is how a report reaches the
right person: the inbox orders by `is_suggested_reviewer`, so a reviewer's own reports float to the
top of _their_ inbox even when **no PR** is involved. **A report with an empty `suggested_reviewers`
is assigned to nobody — it lands in the shared inbox and is very likely to be missed.** So resolve and
set at least one reviewer on every report you author, including informational `requires_human_input`
ones.

Each entry is an **object**, not a bare string — `{"github_login": "..."}` and/or `{"user_uuid": "..."}`
(at least one of the two per entry; a list of plain strings like `["octocat"]` **fails validation**):

- **`github_login`** — a bare, lowercase GitHub login, no `@`, no display name (e.g.
  `{"github_login": "octocat"}`). Assignment matches it against each user's linked GitHub login by
  exact, lowercased comparison, so a mis-cased handle, an `@`-prefix, a display name, a team slug, or
  an email won't assign to anyone.
- **`user_uuid`** — a PostHog user UUID (e.g. `{"user_uuid": "..."}`); the server resolves it to that
  member's linked GitHub login. A `user_uuid` that isn't an org member with a linked GitHub identity
  is rejected (never silently dropped).

You rarely know either outright, so resolve it — cheapest first:

1. **Scratchpad cache.** A `reviewer:<domain>:<area>` entry you (or a prior run) recorded — reuse it.
2. **Inbox precedent.** `inbox-reports-list` (filter by `source_product` + a free-text `search`) for a
   comparable report on the same surface, then `inbox-report-artefacts-list` on it — the
   `suggested_reviewers` artefact is where the routed reviewer lives (the report record itself doesn't
   expose it). Reuse that reviewer for the same area.
3. **`user_uuid` from the entity.** When your evidence already names a PostHog user — an entity's
   `created_by`, an account owner — pass that user's `user_uuid` straight through as a
   `{"user_uuid": "..."}` entry and the server resolves it to their linked GitHub login. No lookup
   call needed.
4. **`signals-scout-members-list`** — the in-run roster lookup, for the cold-start case where you have
   only a name or email. It returns this project's members, each with `email`, name, and a resolved
   `github_login` (pass `search=` to narrow a large project); match the owner and route to their
   `github_login`. A member whose `github_login` is null can't be routed to — pick a different owner.
   The org-scoped `org-member-get-github-login` / `org-members-list` tools are **not available in a
   scout run** (a scoped-team token can't reach the org-nested endpoint), so reach for this, not those.

**Never guess a handle** — a wrong login mis-assigns the report, which is worse than leaving it open.
If you genuinely can't resolve any confident owner, author the report anyway (it still surfaces) but
treat that as the exception, not the norm. Once you've tied an area to an owner, write a
`reviewer:<domain>:<area>` scratchpad entry with the bare lowercase login so the next run routes
instantly.

**On `edit-report`:** reviewers are set at author time and `edit-report` can't change them — so the
one chance to route a report is when you `emit-report` it. If you're editing a report that landed with
no reviewer, `append_note` naming the owner you'd route it to so a human can pick it up; the durable
fix is to get `suggested_reviewers` right at emit.

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

## Dedup: the channel is NOT idempotent

`emit-report` is **not idempotent** — a retried call authors a _second_ report. There is no
server-side dedup key. The dedup story is two-sided and you own it:

1. **Before authoring**, `inbox-reports-list` for a prior report on the same topic (filter by
   `search` / `status` / `source_product`). Pass `ordering=-updated_at` — the default ordering buckets
   by your own reviewer-match and status first, so without it the most recent duplicate can sort below
   older rows and you'd miss it. Found one? `edit-report` it instead of authoring a new one.
2. **After authoring**, write a `report:<domain>:<entity>` scratchpad entry recording the `report_id`
   so the next run finds it (via `inbox-reports-retrieve`) without a title-search guess.

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
