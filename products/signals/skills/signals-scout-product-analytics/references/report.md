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
existing report rather than mint a near-duplicate. A product-analytics finding is report-shaped
when it's a single, localized, validated regression — one funnel step's conversion dropping, one
cohort's retention cliff, one flow's lifecycle composition tilting toward dormant — that you've
corroborated against the flow's seasonality-matched baseline with a steady entrant denominator,
and would stand behind as a standalone inbox item. A scatter of small, weakly-correlated wobbles
across many flows is not a report — it's a sign you haven't found the finding yet, or that the
move is a capture/volume problem that belongs to another scout; keep investigating or record it
in the scratchpad and move on.

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
| `suggested_reviewers`       | list of objects         | Each `{github_login?, user_uuid?}` (at least one per entry). The **single most important routing field** — set on every report (PR or not). See the _`suggested_reviewers`_ section below for resolution steps.                                    |

**Status is decided for you, from safety × actionability:**

| Safety judge | `actionability`          | Resulting status | Surfaces in inbox? |
| ------------ | ------------------------ | ---------------- | ------------------ |
| safe         | `immediately_actionable` | `READY`          | yes                |
| safe         | `requires_human_input`   | `PENDING_INPUT`  | yes                |
| safe         | `not_actionable`         | `SUPPRESSED`     | no                 |
| unsafe       | (any)                    | `SUPPRESSED`     | no                 |

Note the trap: `not_actionable` is **suppressed** (never surfaces). Reserve it for filing-for-the-record;
if you want a human to see it, it must be `immediately_actionable` or `requires_human_input`. A
behavioral regression is almost always an investigation, not a one-line code fix, so the natural
call here is `requires_human_input`.

The result tells you what happened: `report_id` (always set when a report was persisted —
**even when suppressed**, so you can edit or dedup against it), `report_status` (the birth status —
`ready` / `pending_input` / `suppressed`), `emitted` (true only when it actually surfaced),
`safety_explanation`, and `skipped_reason` (set only when a preflight gate — the team's
AI-data-processing approval or the signals-scout source being enabled — stopped the call before any
report was created).

### Writing the `title` and `summary`

The `title` is the inbox headline and the `summary` is the body a human reads to decide whether to
act — write both for a busy reader scanning a feed of other reports.

- **`title`** — one specific, quantified line. Lead with which flow, which step/cohort, and the
  rate move, not a vague category. _"Activation funnel step-2 conversion fell 62%→48% over the last
  7d while step-1 entrants held steady (~5.2k/day)"_, not _"Funnel down"_.
- **`summary`** — a tight few paragraphs following hook → pattern → hypothesis → recommendation:
  1. **Hook** — what's happening, quantified ("the `signup → activated` funnel's step-2 conversion
     dropped from a ~61% trailing-4-week median to 48% over the last complete week, while step-1
     entrants held at ~5.2k/day").
  2. **Pattern** — the shape that makes this a regression, not noise ("the drop is broad across
     platform and country breakdowns, the entrant denominator is steady, and no flow-definition
     edit or running experiment touched the funnel — a real conversion regression, not a
     measurement or capture artifact").
  3. **Hypothesis** — your best read of the cause.
  4. **Recommendation** — the concrete next step that would confirm or resolve it.

Quantify ("62%→48%", "~5.2k/day") over qualitative ("a lot"), and cite entity ids (the flow's
`short_id`, step events, cohort dates, breakdown segments, time ranges) inline so a reviewer can
pivot straight from prose to source. Put the same citations in `evidence` so they back the report
as bound signals.

### Opening a draft PR (autostart)

First, `suggested_reviewers` is **not** a PR field — set it whenever you can name a plausible owner,
PR or not. It's the routing lever and is covered in its own section below; the three fields in this
section are the **PR-only** ones.

A surfaced, immediately-actionable report can open a draft PR automatically. It's opt-in per report
via these fields; supply them only when the report is a concrete, fixable issue you'd want a PR for.

| Field                  | Type      | Notes                                                                                                                                                                                                                                                    |
| ---------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repository`           | string    | `"owner/repo"` targets that repo; the `NO_REPO` sentinel opts out; **omitting it** falls back to free-form selection across the team's repos — the slow path on a many-repo team (it spawns a selection sandbox), so pass `owner/repo` when you know it. |
| `priority`             | `P0`-`P4` | Required for a PR. Pair with `priority_explanation`. P2 for a confirmed broad regression on a human-saved flow; P3 for a single-segment or suggestive move, and for anything on an `inferred` flow.                                                      |
| `priority_explanation` | string    | Required when `priority` is set.                                                                                                                                                                                                                         |

Repo selection only runs when you signal PR intent — an explicit `repository`, or both `priority`
and `suggested_reviewers`. A report that supplies none of these just surfaces in the inbox (no repo
sandbox, no PR). Autostart no-ops unless the report is `immediately_actionable`, has a repo +
priority, and a reviewer qualifies — so these three PR fields are safe to omit for an informational
report. `suggested_reviewers` is not: set it whenever you can name a plausible owner (see the next
section), PR or not. A behavioral regression is usually a thing to investigate (which flag/release/
segment caused it), not a one-line code fix, so most product-analytics reports want
`requires_human_input` and a reviewer, not a PR.

## `suggested_reviewers` — set it on every report (this is how it reaches a human)

`suggested_reviewers` is the **single most important routing field**. It is how a report reaches the
right person: the inbox orders by `is_suggested_reviewer`, so a reviewer's own reports float to the
top of _their_ inbox even when **no PR** is involved. **A report with an empty `suggested_reviewers`
is assigned to nobody — it lands in the shared inbox and is very likely to be missed.** So resolve and
set at least one reviewer on every report you author, including informational `requires_human_input`
ones.

Each entry identifies one reviewer by **`github_login`**, **`user_uuid`**, or both:

- **`github_login`** — a **bare, lowercase GitHub login** — no `@`, no display name (e.g. `octocat`,
  not `@OctoCat`). Assignment matches it against each user's linked GitHub login by exact, lowercased
  comparison, so a mis-cased handle, an `@`-prefix, a display name, a team slug, or an email won't
  assign to anyone.
- **`user_uuid`** — a **PostHog user UUID**. The server resolves it to that org member's linked GitHub
  login for you (and it wins if you also pass a `github_login`). A `user_uuid` that isn't an org member
  of this team **with a linked GitHub identity** is rejected (the whole call fails), so it never
  silently drops. Use it whenever your evidence already names a PostHog user — the flow's `created_by`,
  the insight owner, an account's CSM — so you route to them without ever looking up their handle.

So you have two routes. Product-analytics evidence almost always hands you the owning **person**
already — saved funnels/retention insights carry a `created_by` user UUID — so passing that
**`user_uuid`** straight through is usually the route. **But because resolution is fail-loud (an
unlinked `created_by` rejects the whole `emit-report`, per above), don't hand a `user_uuid` you're
unsure about:** a `created_by` belonging to a PM, a customer, or a departed user has no linked GitHub
identity and will fail the emit. Prefer a `created_by` you've already routed, or a cached login; if
you can't confidently resolve an owner, author the report **unrouted** and `edit-report` reviewers in
later (see below) rather than risk the emit. Otherwise resolve an owner, cheapest first:

1. **Scratchpad cache.** A `reviewer:<domain>:<area>` entry you (or a prior run) recorded — reuse it.
   For product-analytics, key by the owning flow / product area (`reviewer:product_analytics:<area>`).
2. **Inbox precedent.** `inbox-reports-list` (free-text `search`, optionally `source_product=signals_scout`
   for prior scout-authored reports — **not** `product_analytics`, which never matches the channel's
   signals) for a comparable report on the same flow/surface, then `inbox-report-artefacts-list` on it — the
   `suggested_reviewers` artefact is where the routed reviewer lives (the report record itself doesn't
   expose it). Reuse that reviewer for the same area.
3. **`user_uuid` from the entity** — the primary route, restated here as a step so it isn't skipped:
   the flow's `created_by` is usually the owner, so pass it straight through and the server resolves it,
   subject to the fail-loud caveat above. Reach past it to the roster lookup below only when you have no
   entity owner, or the `created_by` isn't a linked org member.
4. **`signals-scout-members-list`** — the in-run roster lookup, for the cold-start case where the
   cache, inbox precedent, and entity `created_by` all come up empty. The org-scoped `org-members-list`
   / `org-member-get-github-login` tools are **not available in a scout run** (a scoped-team token can't
   reach the org-nested endpoint), so this is the resolver to reach for. It returns this project's
   members, each with `user_uuid`, `email`, name, and a resolved `github_login` (pass `search=` to
   narrow); match the owner and route to their `github_login`. A member with a null `github_login` can't
   be routed to — pick a different owner or author unrouted.

**Never guess a handle** — a wrong login mis-assigns the report, which is worse than leaving it open.
If you genuinely can't resolve any confident owner, author the report anyway (it still surfaces, just
unrouted) and `edit-report` reviewers in later once you resolve one (see below). Once you've tied a
flow/area to an owner, write a `reviewer:product_analytics:<area>` scratchpad entry with the bare
lowercase login so the next run routes instantly.

**On `edit-report`:** `edit-report` now accepts `suggested_reviewers` too — setting them replaces the
report's reviewer list and re-runs autostart, so a report that surfaced routed to no one can be rescued
the moment you resolve an owner (and a now-actionable report with a repo + priority can open a draft
PR). An empty list is a no-op — it never clears the existing reviewers.

## `edit-report` — update an existing report

Rewrite `title`/`summary`, append a note, and/or set `suggested_reviewers` on a report that already
exists. Pass `run_id` and `report_id`, plus at least one of `title`, `summary`, `append_note`,
`suggested_reviewers`.

`edit-report` can target **any** of the team's inbox reports — not just ones a scout authored. That
makes it the right tool when a later run learns something about a report the pipeline (or another
scout) created. Rules of good behavior:

- **Prefer `append_note` over rewriting** `title`/`summary` on a report you didn't author. A note is
  additive and audit-friendly (it carries your scout as author); a rewrite silently overwrites a
  human- or pipeline-authored headline.
- **Don't fight an in-flight pipeline.** A report the summary/research workflow is mid-run on can have
  its fields overwritten under you. If a report is actively being worked, append a note rather than
  rewriting.
- **Rescue an unrouted report with `suggested_reviewers`.** Setting reviewers (same
  `{github_login?, user_uuid?}` shape as `emit-report`) replaces the report's reviewer list and re-runs
  autostart — so a report that surfaced routed to no one can be assigned to an owner you resolved later
  (e.g. once you read the flow's `created_by`). An empty list is a no-op; it never clears existing
  reviewers.
- **Only edit a report that's still live in the inbox.** `edit-report` rewrites `title`/`summary`,
  appends a note, or sets reviewers — it **cannot change status**, so it can't reopen a `resolved` /
  `suppressed` / `failed` report. Appending a relapse to a closed report buries a real, actionable
  regression under an item that no longer surfaces. Check the matched report's `status` first: if it
  isn't live, author a fresh report and repoint `report:product_analytics:flow:<short_id>` at the new id.

For this scout the common edit is a flow that's _still moving_: a funnel that kept sliding, a
retention cliff that deepened, or a flow that recovered then relapsed. When the report you authored
last run (found via the `report:product_analytics:flow:<short_id>` pointer) is **still live**,
`append_note` the fresh window's rate, baseline band, and entrant volumes onto it rather than filing
a second report. If that report has since gone `resolved`/`suppressed`/`failed`, a relapse is a
**new report** (it needs to surface and re-route), not a note on the dead one.

## Dedup: the channel is NOT idempotent

`emit-report` is **not idempotent** — a retried call authors a _second_ report. There is no
server-side dedup key. The dedup story is two-sided and you own it:

1. **The scratchpad pointer is the reliable dedup key.** After authoring, write a
   `report:product_analytics:flow:<short_id>` entry recording the `report_id`; the next run
   `inbox-reports-retrieve`s it directly — no search guess. This is the path that actually holds up.
   **Key the pointer to the affected rate, not just the `short_id`:** one funnel/retention insight
   carries several independent rates (different funnel steps, retention cohorts, lifecycle states), so
   a pointer like `report:product_analytics:flow:<short_id>:step2` keeps a later drop on a _different_
   step/cohort from being appended onto an unrelated report. Only `edit-report` when the matched report
   covers the **same** rate; a genuinely distinct rate within the same insight is a fresh report.
2. **A keyword `inbox-reports-list` search is a noisy fallback** — use it only when no pointer exists.
   On a busy project a broad term (e.g. `search=funnel`) returns hundreds of unrelated reports
   (error-tracking funnel bugs, other scouts' funnel reports), and your flow's report can sit far down
   the list (or be `failed`/stale and not float up). Search the flow's _specific_ distinguishing terms
   (its name, the activation/step events, the `short_id`), pass `ordering=-updated_at` (the default
   ordering buckets by your own reviewer-match and status first, so the most recent duplicate can
   otherwise sort below older rows), and still confirm a hit with `inbox-reports-retrieve` before
   treating it as the same flow. Found one? `edit-report` it instead of authoring a new one.

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
