# The report channel: `emit-report` / `edit-report`

`emit-signal` is your default output: a weak finding the pipeline clusters, dedupes, and
may or may not promote into a report. When you've **already done the research and know the
exact report you want to file**, you can skip the pipeline and author the report directly —
the report channel. This reference is the contract: the tools, their fields, when to reach
for them over `emit-signal`, and the two behaviors that make this channel different (it
isn't idempotent, and the pipeline may later rewrite what you authored).

> Like every `signals-scout-*` tool, **both report tools require the current `run_id`** (the
> run you're executing in) on every call — omitting it fails validation.

## When to use which channel

| You have…                                                                                                          | Use           |
| ------------------------------------------------------------------------------------------------------------------ | ------------- |
| A weak/partial observation; the value is in the pipeline grouping it with other signals.                           | `emit-signal` |
| A finished, well-formed finding you want filed **1:1** as a report — no clustering, full control of title/summary. | `emit-report` |
| New information about a report that already exists (one you authored last run, or a pipeline report).              | `edit-report` |

The discriminator is **fidelity vs. consolidation**. `emit-signal` trades 1:1 control for the
pipeline's ability to merge many weak signals into one report; `emit-report` keeps the control
and skips the merge. As the cross-product generalist, your fit for the report channel is the
**fully-validated cross-product correlation** — one finding you've corroborated across surfaces
and would stand behind as a standalone inbox item. A scatter of small correlated observations is
not — let the pipeline do its job with `emit-signal`.

Reporting is a **higher bar than emitting**, not a shortcut around the confidence gate. Author a
report only when you'd own it end-to-end as an inbox item a human will act on.

## `emit-report` — author a full report

Judges the report for safety, then persists it at the judged status.

| Field                       | Type                    | Notes                                                                                                                                                                                                                                              |
| --------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_id`                    | string, required        | The current run's id — same as every `signals-scout-*` tool.                                                                                                                                                                                       |
| `title`                     | string, ≤300, non-empty | The inbox headline. One specific, quantified line.                                                                                                                                                                                                 |
| `summary`                   | string                  | The report body prose — the same description discipline as a finding (hook → pattern → hypothesis → recommendation); see [`emit.md`](emit.md).                                                                                                     |
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
`safety_explanation`, and `skipped_reason` (set only when a preflight gate stopped the call before
any report was created — the same AI-data-processing / source-enabled gates that govern `emit-signal`).

### Opening a draft PR (autostart)

A surfaced, immediately-actionable report can open a draft PR automatically. It's opt-in per report
via four more fields; supply them only when the report is a concrete, fixable issue you'd want a PR for:

| Field                  | Type        | Notes                                                                                                                                                                                                                                                    |
| ---------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository`           | string      | `"owner/repo"` targets that repo; the `NO_REPO` sentinel opts out; **omitting it** falls back to free-form selection across the team's repos — the slow path on a many-repo team (it spawns a selection sandbox), so pass `owner/repo` when you know it. |
| `priority`             | `P0`-`P4`   | Required for a PR. Pair with `priority_explanation`.                                                                                                                                                                                                     |
| `priority_explanation` | string      | Required when `priority` is set.                                                                                                                                                                                                                         |
| `suggested_reviewers`  | list of str | GitHub logins to consider. A PR opens only if at least one clears their autonomy threshold.                                                                                                                                                              |

Repo selection only runs when you signal PR intent — an explicit `repository`, or both `priority`
and `suggested_reviewers`. A report that supplies none of these just surfaces in the inbox (no repo
sandbox, no PR). Autostart no-ops unless the report is `immediately_actionable`, has a repo +
priority, and a reviewer qualifies — so these fields are safe to omit for an informational report.

## Choosing `suggested_reviewers` — how a report gets routed to a human

`suggested_reviewers` is **not just a PR gate** — it is the **primary way a report reaches the right
person internally**. The inbox orders by `is_suggested_reviewer`, so a reviewer's own reports float
to the top of _their_ inbox even when **no PR** is involved. **Set it whenever you can name a
plausible owner — including on informational `requires_human_input` reports.** A report with no
reviewer just sits in the shared inbox hoping someone grabs it.

Each entry must be a **bare, lowercase GitHub login** — no `@`, no display name (e.g. `octocat`,
not `@OctoCat`). Internal assignment matches the login against each user's linked GitHub login by
exact, lowercased comparison, so a mis-cased handle, an `@`-prefix, a display name, a team slug, or
an email won't assign to anyone. You rarely know the login outright — resolve it, cheapest first:

1. **Scratchpad cache.** A `reviewer:<domain>:<area>` entry you (or a sibling run) recorded before — reuse it.
2. **Inbox precedent.** `inbox-reports-list` for a similar report on the same surface (same
   `source_product`, plus a free-text `search`), then `inbox-reports-retrieve` to see who comparable
   reports were routed to. Reuse that reviewer for the same area.
3. **`org-member-get-github-login`** — the canonical resolver, available to every scout run. Once
   you've identified the owning **person** (by name/email via `org-members-list`, or `@me`), pass
   their PostHog user UUID to get their linked GitHub login (returns null when none is linked).

**If you can't resolve a confident login, leave `suggested_reviewers` empty** — the report still
surfaces. **Never guess a handle**: a wrong login mis-assigns the report, which is worse than leaving
it open. After you confidently tie an area to an owner, write a `reviewer:<domain>:<area>` scratchpad
entry with the bare lowercase login so the next run routes faster.

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
   `search` / `status` / `source_product`, newest-updated first). Found one? `edit-report` it instead
   of authoring a new one.
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
