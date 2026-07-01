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

> **Tool names vs. opt-in strings.** The callable MCP tools are
> **`signals-scout-emit-report`** and **`signals-scout-edit-report`** (same `signals-scout-*`
> prefix as `signals-scout-emit-signal`) — those are the names you invoke. The bare
> `emit_report` / `edit_report` (underscored) used throughout this doc and below are the **opt-in
> strings** you list under `allowed_tools`; they are not callable tool names. And like every
> `signals-scout-*` tool, **both report tools require the current `run_id`** (the run you're
> executing in) on every call — omitting it fails validation.

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

| Field                       | Type                    | Notes                                                                                                                                                                                                                                              |
| --------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_id`                    | string, required        | The current run's id — the run you're executing in, same as every `signals-scout-*` tool.                                                                                                                                                          |
| `title`                     | string, ≤300, non-empty | The inbox headline. One specific, quantified line.                                                                                                                                                                                                 |
| `summary`                   | string                  | The report body prose — the same description-prose discipline as a finding (hook → pattern → hypothesis → recommendation).                                                                                                                         |
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

The result tells you what happened: `report_id` (always set when a report was persisted —
**even when suppressed**, so you can edit or dedup against it), `report_status` (the birth status —
`ready` / `pending_input` / `suppressed` — the field is named `report_status` in the response, not
`status`), `emitted` (true only when it actually surfaced — `READY` / `PENDING_INPUT`),
`safety_explanation`, and
`skipped_reason` (set only when a preflight gate stopped the call before any report was
created — the same AI-data-processing / source-enabled gates that govern `emit-signal`).

### Opening a draft PR (autostart)

A surfaced, immediately-actionable report can open a draft PR automatically — the same autostart
path the pipeline uses. It's opt-in per report via three more `emit_report` fields; supply them only
when the report is a concrete, fixable issue you'd want a PR for:

| Field                  | Type        | Notes                                                                                                                                                                                                                                                    |
| ---------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository`           | string      | `"owner/repo"` targets that repo; the `NO_REPO` sentinel opts out; **omitting it** falls back to free-form selection across the team's repos — the slow path on a many-repo team (it spawns a selection sandbox), so pass `owner/repo` when you know it. |
| `priority`             | `P0`-`P4`   | Required for a PR. Pair with `priority_explanation`.                                                                                                                                                                                                     |
| `priority_explanation` | string      | Required when `priority` is set.                                                                                                                                                                                                                         |
| `suggested_reviewers`  | list of obj | Reviewers to consider, each `{github_login?, user_uuid?}` (at least one per entry; see the section below). A PR opens only if at least one clears their autonomy threshold.                                                                              |

Repo selection only runs when you signal PR intent — an explicit `repository`, or both `priority`
and `suggested_reviewers`. A report that supplies none of these just surfaces in the inbox (no repo
sandbox, no PR). Autostart itself still no-ops unless the report is `immediately_actionable`, has a
repo + priority, and a reviewer qualifies — so these fields are safe to omit for an informational
report.

## Choosing `suggested_reviewers` — how a report gets assigned to a human

`suggested_reviewers` is **not just a PR gate** — it is the **primary way a report gets routed
to the right person internally**. The inbox orders by `is_suggested_reviewer`, so a reviewer's
own reports float to the top of _their_ inbox; a report with the right reviewer reaches that
human even when **no PR** is involved. **Set it whenever you can name a plausible owner —
including on informational `requires_human_input` reports**, not only PR-bound ones. A report
with no reviewer just sits in the shared inbox hoping someone grabs it.

Each entry identifies one reviewer by **`github_login`**, **`user_uuid`**, or both:

- **`github_login`** — a **bare, lowercase GitHub login** (e.g. `octocat`, not `@OctoCat`). Internal
  assignment matches it against each user's linked GitHub login by exact, lowercased comparison, so a
  mis-cased handle, an `@`-prefix, a display name, a CODEOWNERS **team** slug, or an email won't set
  `is_suggested_reviewer` for anyone (autostart's PR-selection path is more lenient, but the
  assignment path is not).
- **`user_uuid`** — a **PostHog user UUID**. The server resolves it to that org member's linked GitHub
  login for you (and it wins if you also pass a `github_login`). Use this whenever your evidence
  already names a PostHog user — an account owner, an entity's `created_by`, a CSM — so you can route
  to them without ever looking up their handle. A `user_uuid` that isn't an org member of this team
  **with a linked GitHub identity** is rejected (the whole call fails), so it never silently drops.

So you have two routes to a reviewer. If you already hold a PostHog user UUID, prefer passing it as
`user_uuid` — it's the most reliable. Otherwise resolve a `github_login`, cheapest source first:

1. **Scratchpad cache.** A `reviewer:<domain>:<area>` entry you (or a sibling run) recorded
   before — reuse it. Fastest path, and the reason the caching step at the end of this list exists.
2. **Inbox precedent.** `inbox-reports-list` for a similar/related report on the same surface
   (same `source_product`, plus a free-text `search` for the area), then `inbox-reports-retrieve`
   / `inbox-report-artefacts-list` to see who comparable reports were routed to. Reuse that
   reviewer for the same area — the safest general recipe, available to every scout.
3. **CODEOWNERS / git** (only if the scout has a repo checkout). `.github/CODEOWNERS` for the
   owning path, or the last `git log` author for the file. Neither usually hands you a usable
   login directly: CODEOWNERS entries are often **team** slugs (`@your-org/team-name`) and `git log`
   gives a name + email — both must be resolved to an **individual** GitHub login before you write
   the reviewer (a team slug or an email won't match any user).
4. **`signals-scout-members-list`** — the in-run roster lookup, for the cold-start case where the
   cheaper paths above don't resolve an owner. It returns this project's members, each with `user_uuid`,
   `email`, name, and a resolved `github_login` (pass `search=` to narrow); match the owner and route to
   their `github_login`, or hand the `user_uuid` straight through and let the server resolve it. The
   org-scoped `org-members-list` / `org-member-get-github-login` tools are **not available in a scout
   run** — a scoped-team token can't reach the org-nested endpoint, so don't build a scout's reviewer
   recipe around them.

**If you can't confidently identify a reviewer, leave `suggested_reviewers` empty** — the report
still surfaces for a human to grab. **Never guess a handle**: a wrong login mis-assigns the report
(or silently fails to assign), which is worse than leaving it open. And remember `edit_report` can set
reviewers on a report later — so a report that surfaced routed to no one isn't stuck; once you resolve
an owner, edit it in (which also re-runs autostart).

**Cache for next time.** After you confidently tie an area to an owner, write a
`reviewer:<domain>:<area>` scratchpad entry with the bare lowercase login so the next run — and
sibling scouts — route faster. The fleet's reviewer map should compound over time.

## `edit_report` — update an existing report

Rewrite `title`/`summary`, append a note, and/or set `suggested_reviewers` on a report that already
exists. Pass `run_id` (the current run) and `report_id`, plus at least one of `title`, `summary`,
`append_note`, `suggested_reviewers`.

`edit_report` can target **any** of the team's inbox reports — not just ones a scout authored.
That makes it the right tool when a later run learns something about a report the pipeline (or
another scout) created. Rules of good behavior:

- **Prefer `append_note` over rewriting** `title`/`summary` on a report you didn't author. A
  note is additive and audit-friendly (it carries your scout as the author); a rewrite
  silently overwrites a human- or pipeline-authored headline.
- **Don't fight an in-flight pipeline.** A report the summary/research workflow is mid-run on
  can have its fields overwritten under you. If a report is actively being worked, append a
  note rather than rewriting.
- **Use `suggested_reviewers` to rescue an unrouted report.** Setting reviewers (same
  `{github_login?, user_uuid?}` shape as `emit_report`) replaces the report's reviewer list and
  re-runs autostart — so a report that surfaced routed to no one can be assigned to an owner you
  resolved later, and a now-actionable report with a repo + priority can open a draft PR. An empty
  list is a no-op (it never clears existing reviewers).

## Finding "the report I made last time"

There is no scout-specific report search — use the **vanilla inbox tools** the scout already
has. Before authoring, list the team's existing reports so you reconcile against one instead of
filing a duplicate:

- `inbox-reports-list` — filter by title/summary free-text (`search`), `status`, `source_product`,
  or your own `task_id`; newest-updated first.
- `inbox-reports-retrieve` — fetch a single report by id (use the `report_id` you stashed in the
  scratchpad last run).

## Dedup: the channel is NOT idempotent

`emit_report` is **not idempotent** — a retried call authors a _second_ report. There is no
server-side dedup key. The dedup story is two-sided and the scout owns it:

1. **Before authoring**, `inbox-reports-list` for a prior report on the same topic. Found
   one? `edit_report` it instead of authoring a new one.
2. **After authoring**, write a `report:<domain>:<entity>` scratchpad entry recording the
   `report_id` so the next run finds it (via `inbox-reports-retrieve`) without a title-search
   guess. (This is the report-channel member of the scratchpad key-prefix vocabulary — see
   [`dedupe-and-memory.md`](dedupe-and-memory.md).)

**Never retry an `emit_report` / `edit_report` call that may have succeeded** — a transport
error after the write commits, retried, double-files. If you're unsure whether a call landed,
`inbox-reports-list` to check before retrying.

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
```

A scout with no `allowed_tools` (or one that omits these) runs on the `emit-signal`-only
contract — the report channel is invisible to it. `signals-scout-anomaly-detection` is the
first canonical adopter — each scored, attributed metric anomaly is a natural finished 1:1
report, so it files via `emit_report` / `edit_report` rather than a weak signal (see its
`references/report-contract.md` for the worked, surface-specific shape).
`signals-scout-health-checks` and `signals-scout-observability-gaps` are the next intended
adopters (a bundled health-check cluster and a single observability-gap recommendation are both
natural 1:1 reports too). Add a short body section telling the scout _when_ to reach for the
channel. Keep it lean — the field-level detail lives here, not in the body.

**Rollout posture:** start a newly opted-in scout in **dry-run** (`emit=false` on its
`SignalScoutConfig`) so it runs and logs what it _would_ author without writing to the inbox.
Inspect via `signals-scout-runs-retrieve`, calibrate, then flip `emit=true`. The report channel
files a full inbox item on the first hit, so the cautious loop is worth it here.
