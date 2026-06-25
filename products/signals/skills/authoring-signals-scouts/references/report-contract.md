# The report channel: `emit_report` / `edit_report`

Most scouts have one output: `emit-signal`, a weak finding the pipeline clusters, dedupes,
and may or may not promote into a `SignalReport`. A scout that has **already done the
research and knows the exact report it wants to file** can skip the pipeline and author the
report directly — the **report channel**. This reference is the contract for that channel:
the tools, their fields, when to reach for them over `emit-signal`, and the two behaviors
that make this channel different (it isn't idempotent, and the pipeline may later rewrite
what you authored).

This is **opt-in**. A scout gets these tools only if its skill's frontmatter
`allowed_tools` lists them — see [Opting a scout in](#opting-a-scout-in). Don't add them to a
scout whose findings are genuinely "weak observations the pipeline should consolidate" —
that's exactly what `emit-signal` is for.

## When to use which channel

| You have…                                                                                                          | Use           |
| ------------------------------------------------------------------------------------------------------------------ | ------------- |
| A weak/partial observation; the value is in the pipeline grouping it with other signals.                           | `emit-signal` |
| A finished, well-formed finding you want filed **1:1** as a report — no clustering, full control of title/summary. | `emit_report` |
| New information about a report that already exists (one you authored last run, or a pipeline report).              | `edit_report` |

The discriminator is **fidelity vs. consolidation**. `emit-signal` trades 1:1 control for the
pipeline's ability to merge many weak signals into one report; `emit_report` keeps the control
and skips the merge. A scout whose natural unit of output is "one well-framed report" (a
bundled health-check cluster, a single observability-gap recommendation) is a report-channel
fit. A scout that surfaces many small correlated observations is not — let the pipeline do its
job.

Reporting is a **higher bar than emitting**, not a shortcut around the confidence gate. Author a
report only when you'd stand behind it as a standalone inbox item a human will act on.

## `emit_report` — author a full report

Judges the report for safety, then persists it at the judged status.

| Field                       | Type                    | Notes                                                                                                                           |
| --------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `title`                     | string, ≤300, non-empty | The inbox headline. One specific, quantified line.                                                                              |
| `summary`                   | string                  | The report body prose — the same description-prose discipline as a finding (hook → pattern → hypothesis → recommendation).      |
| `evidence`                  | list, ≥1                | Each `{description, source_id}`. Becomes a bound signal row backing the report. `source_id` is the citable entity id.           |
| `actionability_explanation` | string                  | One sentence justifying the actionability call below.                                                                           |
| `actionability`             | enum                    | `immediately_actionable` / `requires_human_input` / `not_actionable`. You make this call — the channel does not re-research it. |
| `already_addressed`         | bool, default `false`   | Set when the underlying issue is already handled and you're filing for the record.                                              |

**Status is decided for you, from safety × actionability:**

| Safety judge | `actionability`          | Resulting status | Surfaces in inbox? |
| ------------ | ------------------------ | ---------------- | ------------------ |
| safe         | `immediately_actionable` | `READY`          | yes                |
| safe         | `requires_human_input`   | `PENDING_INPUT`  | yes                |
| safe         | `not_actionable`         | `SUPPRESSED`     | no                 |
| unsafe       | (any)                    | `SUPPRESSED`     | no                 |

The result tells you what happened: `report_id` (always set when a report was persisted —
**even when suppressed**, so you can edit or dedup against it), `status`, `emitted` (true only
when it actually surfaced — `READY` / `PENDING_INPUT`), `safety_explanation`, and
`skipped_reason` (set only when a preflight gate stopped the call before any report was
created — the same AI-data-processing / source-enabled gates that govern `emit-signal`).

## `edit_report` — update an existing report

Rewrite `title`/`summary` and/or append a note to a report that already exists. Pass
`report_id` plus at least one of `title`, `summary`, `append_note`.

`edit_report` can target **any** of the team's inbox reports — not just ones a scout authored.
That makes it the right tool when a later run learns something about a report the pipeline (or
another scout) created. Two rules of good behavior:

- **Prefer `append_note` over rewriting** `title`/`summary` on a report you didn't author. A
  note is additive and audit-friendly (it carries your scout as the author); a rewrite
  silently overwrites a human- or pipeline-authored headline.
- **Don't fight an in-flight pipeline.** A report the summary/research workflow is mid-run on
  can have its fields overwritten under you. If a report is actively being worked, append a
  note rather than rewriting.

## `search_scout_reports` — find "the report I made last time"

The **dedup read tool**. Before authoring, search the team's existing reports so you reconcile
against one instead of filing a duplicate. `query` is a case-insensitive title substring;
`statuses` filters lifecycle states; newest-updated first. Returns `report_id`, `title`,
`status`, `signal_count`, `created_at`, `updated_at` per row.

## Dedup: the channel is NOT idempotent

`emit_report` is **not idempotent** — a retried call authors a _second_ report. There is no
server-side dedup key. The dedup story is two-sided and the scout owns it:

1. **Before authoring**, `search_scout_reports` for a prior report on the same topic. Found
   one? `edit_report` it instead of authoring a new one.
2. **After authoring**, write a `report:<domain>:<entity>` scratchpad entry recording the
   `report_id` so the next run finds it without a title-search guess. (This is the report-channel
   member of the scratchpad key-prefix vocabulary — see
   [`dedupe-and-memory.md`](dedupe-and-memory.md).)

**Never retry an `emit_report` / `edit_report` call that may have succeeded** — a transport
error after the write commits, retried, double-files. If you're unsure whether a call landed,
`search_scout_reports` to check before retrying.

## The pipeline may rewrite what you authored (accepted)

An authored report is a first-class `SignalReport` that coexists with pipeline reports. When
future signals consolidate around the same topic, the pipeline may **re-promote and re-research
the report, overwriting your authored `title`/`summary`**. This is accepted behavior, not a
bug — there is no pin. Don't author a report assuming your exact prose is immutable; author the
finding, and let the inbox stay the source of truth for how it's currently framed. Your
durable record of "I filed this" is the `report:` scratchpad entry and the `report_id`, not the
title text.

## Opting a scout in

In the scout's `SKILL.md` frontmatter, list the report tools under `allowed_tools`:

```yaml
allowed_tools:
  - emit_report
  - edit_report
  - search_scout_reports
```

A scout with no `allowed_tools` (or one that omits these) runs on the `emit-signal`-only
contract — the report channel is invisible to it. Add a short body section telling the scout
_when_ to reach for the channel (the canonical pilots,
`signals-scout-health-checks` and `signals-scout-observability-gaps`, show the shape). Keep it
lean — the field-level detail lives here, not in the body.

**Rollout posture:** start a newly opted-in scout in **dry-run** (`emit=false` on its
`SignalScoutConfig`) so it runs and logs what it _would_ author without writing to the inbox.
Inspect via `signals-scout-runs-retrieve`, calibrate, then flip `emit=true`. The report channel
files a full inbox item on the first hit, so the cautious loop is worth it here.
