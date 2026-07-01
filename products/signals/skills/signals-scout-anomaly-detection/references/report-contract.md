# The report contract

How this scout files an anomaly on the **report channel** — `signals-scout-emit-report` to
author a fresh inbox report, `signals-scout-edit-report` to update one on a recurrence. A
scored, attributed anomaly you'd stand behind is a finished, 1:1 inbox report, not a weak
signal for the pipeline to cluster — so you author it directly and own its framing end to end.

The harness already gives you the **general** report-channel discipline in your run prompt:
search the inbox before authoring, prefer editing over a near-duplicate, keep a
`report:<domain>:<entity>` scratchpad pointer, set `suggested_reviewers` to route the report,
and never retry a non-idempotent call. This file is the **anomaly-specific** contract on top of
that: the authoring bar, the title/summary prose, the evidence shape, how to set
actionability / priority / repository / reviewers for a metric move, and the notebook write-up.
The harness validates request shape but does **not** grade prose — that's on you.

## The authoring bar (higher than emitting)

Authoring a report is a **higher bar** than firing a signal — it surfaces a full inbox item a
human will act on, with no pipeline consolidation to soften a weak call. Author only when:

- robust z ≥ ~3.5 on the **latest complete bucket** (the partial bucket is excluded),
- the guards in [`anomaly-methods.md`](anomaly-methods.md) passed,
- the move is **not** explained by seasonality or a known data-pipeline gap, and
- you've **attributed** it (which segment drove it) and would stand behind it standalone.

Below that bar, write a `baseline:` / `noise:` scratchpad entry instead — don't author.

## `emit_report` — author a full report

| Field                       | Type                    | Notes                                                                                                                                                           |
| --------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `title`                     | string, ≤300, non-empty | The inbox headline. One specific, quantified line (see below).                                                                                                  |
| `summary`                   | string                  | The report body prose — hook → pattern → hypothesis → lineage → recommendation (see below).                                                                     |
| `evidence`                  | list, 1–50              | Each `{description, source_id}`. Becomes a bound signal row backing the report.                                                                                 |
| `actionability_explanation` | string                  | One sentence justifying the actionability call.                                                                                                                 |
| `actionability`             | enum                    | `immediately_actionable` / `requires_human_input` / `not_actionable`. You make the call.                                                                        |
| `already_addressed`         | bool, default `false`   | Set when the move is already handled and you're filing for the record.                                                                                          |
| `suggested_reviewers`       | list of objects         | Who owns the metric/dashboard — routes the report. Each entry is `{github_login}` and/or `{user_uuid}` (not a bare string). High-leverage — set it (see below). |
| `priority`                  | `P0`–`P4`               | Optional; pair with `priority_explanation`. Needed for an autostart draft PR.                                                                                   |
| `priority_explanation`      | string                  | Required when `priority` is set.                                                                                                                                |
| `repository`                | string                  | `owner/repo` for a code fix, the `NO_REPO` sentinel for a pure metric move, omitted for free-form.                                                              |

The result carries `report_id` (always set when a report was persisted — even when suppressed,
so you can edit / dedup against it), `report_status`, `emitted` (true only when it surfaced as
READY / PENDING_INPUT), `safety_explanation`, and `skipped_reason` (set only when a preflight
gate stopped the call before any report was created).

Stash the `report_id` in a `report:anomaly_detection:insight:<short_id>` scratchpad pointer so
the next run finds it instead of filing a duplicate — but condition the pointer on the outcome:

- **Surfaced** (`emitted=true`) — record the `report_id` as the live report to edit on a
  recurrence.
- **Suppressed** (`emitted=false` but a `report_id` came back — the safety judge or a
  `not_actionable` call kept it out of the inbox) — record the `report_id` together with its
  suppressed status. `edit_report` only rewrites title/summary or appends a note; it cannot
  resurface a suppressed report, so a later recurrence should re-author rather than edit the
  invisible one.

### Title

One tight, quantified headline naming the metric, the direction, and the date:
`Daily signups dropped ~60% vs same-weekday baseline (2026-06-06)`. A human scanning the inbox
should grasp what moved and how much from the title alone.

### Summary (the body prose)

`summary` renders as GitHub-flavored markdown in the inbox and is collapsed to the first ~300
characters behind a "Show more" toggle. Front-load, structure, no walls:

1. **Hook** — what moved, **quantified**: "daily signups dropped to 412 yesterday vs an ~1,050
   same-weekday baseline (robust z = 4.8)". End the lead with a blank line so the preview
   truncates at a clean break.
2. **Pattern** — the shape that makes it signal not noise: direction, that it cleared the
   seasonality-matched baseline, whether it's one bucket or sustained.
3. **Hypothesis** — the suspected cause (deploy, experiment, pipeline, real behavior change).
4. **Lineage** — if a prior report covered this insight, link it (you're usually editing it
   instead — see below).
5. **Recommendation** — a closing `Recommend: …` line naming the next action (which insight to
   open, what to check).

Cite the insight `short_id` and dashboard id inline so a human pivots straight to the source,
and close with the notebook URL: "Full write-up with charts: `<notebook-url>`."

### Evidence

Each entry `{description, source_id}`, 1–50, capped well below that in practice. Cite every
concrete claim. `source_id` is the citable entity id — the insight `short_id` for the scored
series, the notebook `short_id` for the write-up. Put the bucket value, the baseline median,
the z-score, and the time window in the descriptions. **Always include one evidence entry whose
`source_id` is the notebook `short_id`** and whose description links the write-up URL — that's
the durable artifact the human opens.

### Actionability, priority, repository

- **Actionability.** A metric anomaly is usually `requires_human_input` — a human investigates
  the move and decides whether it's a real regression (surfaces as PENDING_INPUT). Use
  `immediately_actionable` only when there's a concrete, obvious fix (e.g. a tracking
  regression from a named deploy — surfaces as READY). `not_actionable` is suppressed; the
  safety judge can suppress regardless, so don't inflate.
- **Priority** (the old severity, now an autostart input). `P0` active critical (outage / data
  loss); `P1` active material (a revenue/conversion drop hitting the business now); `P2`
  confirmed contained; `P3` suspected or minor; `P4` FYI. A sustained drop-to-zero on a key
  metric is typically P1; a one-bucket spike already receding is P2–P3. Set it (with
  `priority_explanation`) when the move is concrete enough to justify urgency.
- **Repository.** Most metric anomalies have no single code fix — pass the `NO_REPO` sentinel.
  Pass `owner/repo` only when the anomaly is a tracking/instrumentation regression you can point
  at a repo. Don't leave it to free-form selection unless you genuinely don't know.

### Suggested reviewers

The single highest-leverage field — it **routes** the report to whoever owns the metric. The
harness prompt covers resolution in full (resolve via `signals-scout-members-list`, each entry an
object `{github_login}` and/or `{user_uuid}`, and `edit_report` can route an orphaned report). The
anomaly specifics: cache the owner under a `reviewer:anomaly_detection:<area>` key, and reuse inbox
precedent (`inbox-reports-list` on the same dashboard/surface, then `inbox-report-artefacts-list`)
for who has owned that metric before. Never guess a handle.

## `edit_report` — update on a recurrence

A recurrence or escalation of an insight's anomaly you already reported is an **edit, not a new
report**. Find the live report (the `report:` pointer's `report_id` → `inbox-reports-retrieve`,
or `inbox-reports-list` by the insight), then:

- **`append_note`** with the new evidence — additive, audit-friendly, and the right move on any
  report (even a pipeline-authored one). Build a **fresh notebook** for the new window and link
  it in the note (one notebook per window — never append a new anomaly to a prior notebook).
- **Rewrite `title`/`summary`** only on a report you authored, and only when the framing is
  genuinely stale.

`edit_report` is preflight-gated like `emit_report`, but it **raises** when the scout is gated
(dry-run `emit=false`, un-approved AI processing, or a disabled source) rather than returning a
`skipped_reason` — the note is never appended. So if you built a fresh recurrence notebook and
the `edit_report` call is blocked (or otherwise doesn't commit), **delete that notebook with
`notebooks-destroy`** — same orphan-cleanup rule as a non-surfacing author. Equivalently, defer
building the notebook until the edit is about to commit.

A genuinely distinct anomaly (a different insight, or a new move on the same one after the prior
was resolved) is a new `emit_report`, with a `summary` lineage line citing the prior report.

## Dedup

The channel isn't idempotent, and the harness prompt covers the general discipline (search the
inbox first with `ordering=-updated_at`, edit over a near-duplicate, never retry a call that may
have landed, and the accepted caveat that the pipeline may later rewrite a report you authored).
The anomaly specifics: dedup by the insight via your
`report:anomaly_detection:insight:<short_id>` pointer (and `inbox-reports-list` on the insight /
metric / dashboard), and **live-check before editing** — a suppressed or resolved report can't be
resurfaced by `edit_report`, so re-author with a `summary` lineage line citing the prior
`report_id` instead of editing the invisible one.

## The notebook write-up

The report `summary` is the inbox surface; the **notebook is the durable artifact** behind it —
the place a human lands to see the charts, the baseline math, and the attribution that justify
the call. **Build the notebook _before_ you author the report**, then link its URL from the
summary and cite it as an evidence entry. One notebook per authored report (and one per window
on a recurrence).

### Create it

Call `notebooks-create` with a `title` and `content` (ProseMirror rich-text JSON). The response
carries the new notebook's `short_id` and a clickable URL in `_posthogUrl` (the tool enriches the
result with `/notebooks/{short_id}`) — surface that verbatim, don't hand-build it. If you ever
need to build the link yourself, it is `generate-app-url` with `url=/notebooks/{shortId}`.

- **Title** — name the metric, the direction, and the date, e.g.
  `Anomaly: daily signups dropped ~60% (2026-06-06)`.
- **One notebook per report** — never append a new anomaly to a prior run's notebook. A
  recurrence on a later day is a new notebook, linked from the `edit_report` note.

### What goes in it

Lead with the same hook the inbox sees, then the evidence the ~300-char preview can't hold:

1. **Summary** — the quantified hook (bucket value vs baseline, robust z, priority), one or two
   sentences. Same claim as the report summary, so the notebook stands alone.
2. **The chart** — embed the anomalous series so the spike/drop is visible, with the window wide
   enough (e.g. `-63d`) that the baseline _and_ the break are both on screen. A `SavedInsightNode`
   renders the insight's own saved date range and carries no date override — so use it only when
   that saved range already shows the baseline; if the insight is saved to a short window (often
   `-7d`), embed an inline widened `DataVisualizationNode` (or `InsightVizNode`) for the scored
   window instead.
3. **Baseline & method** — the seasonality-matched baseline (median + MAD per bucket), the
   z-score, which detector(s) `alert-simulate` fired, and that the partial bucket was excluded.
4. **Attribution** — which breakdown segment(s) drove the move, and whether it's broad
   (regression) or one segment (often expected).
5. **Hypothesis & next step** — suspected cause and what to check, matching the report summary.

### Embedded-chart recipe

Charts are `{type: "ph-query", attrs: {nodeId: "<unique>", query: <query>}}` nodes inside
`content`. `query` is one of:

- **Embed the anomalous saved insight** —
  `{kind: "SavedInsightNode", shortId: "<short_id>"}`. Renders the insight's _saved_ date range
  (no override); fine when that range shows the baseline, otherwise prefer a widened node below.
- **Chart a SQL-fallback series** —
  `{kind: "DataVisualizationNode", source: {kind: "HogQLQuery", query: "SELECT ..."}, display: "ActionsLineGraph"}`.
  Do **not** wrap a `HogQLQuery` in an `InsightVizNode`.
- **Build an ad-hoc product-analytics chart** —
  `{kind: "InsightVizNode", source: {kind: "TrendsQuery", ...}}`.

Prefer embedding the saved insight you scored — it stays in sync with the source and is the thing
the human will open next. Give each `ph-query` node a distinct `nodeId`.

`content` is a ProseMirror doc (the tool documents no node schema, so use this skeleton). Text is
`paragraph` / `heading` (with `attrs.level`) / `bulletList` → `listItem` → `paragraph`; charts are
`ph-query` nodes. A minimal working shape:

```json
{
  "type": "doc",
  "content": [
    {
      "type": "heading",
      "attrs": { "level": 1 },
      "content": [{ "type": "text", "text": "Anomaly: <metric> <direction> (<date>)" }]
    },
    { "type": "paragraph", "content": [{ "type": "text", "text": "<the quantified hook>" }] },
    {
      "type": "ph-query",
      "attrs": { "nodeId": "scored-insight", "query": { "kind": "SavedInsightNode", "shortId": "<short_id>" } }
    },
    { "type": "heading", "attrs": { "level": 2 }, "content": [{ "type": "text", "text": "Baseline & method" }] },
    {
      "type": "bulletList",
      "content": [
        {
          "type": "listItem",
          "content": [
            {
              "type": "paragraph",
              "content": [{ "type": "text", "text": "<baseline median + MAD, the z, partial bucket excluded>" }]
            }
          ]
        }
      ]
    }
  ]
}
```

For a SQL-fallback chart, swap the `ph-query` query for
`{ "kind": "DataVisualizationNode", "source": { "kind": "HogQLQuery", "query": "SELECT ..." }, "display": "ActionsLineGraph" }`.

### Clean up if the report doesn't surface

The notebook (gated only by `notebook:write`) is created before the report channel runs its
preflight gates and safety judge. If the report **did not surface** — `emit_report` returned a
`skipped_reason` (dry-run `emit=false`, un-approved AI processing, or a disabled source — no
report created), or the safety judge suppressed it (`emitted=false`) — **delete the just-created
notebook with `notebooks-destroy`** so a non-surfacing run leaves no orphan user-facing artifact.
Only a notebook behind a surfaced report should survive the run. Skipping notebook _creation_ is
acceptable only if `notebooks-create` fails — then author anyway and note the missing artifact in
the summary.

## Worked example

```yaml
# signals-scout-emit-report
title: 'Daily signups dropped ~60% vs same-weekday baseline (2026-06-06)'
actionability: requires_human_input
actionability_explanation: >
  A human needs to confirm whether this is a broken signup flow or a tracking regression and
  decide the fix.
priority: P1
priority_explanation: >
  Signups are a top-of-funnel business metric; a sustained ~60% drop is active material impact.
suggested_reviewers:
  - github_login: octocat
repository: NO_REPO
evidence:
  - source_id: 9aBcDeF
    description: >
      'Daily signups' (insight 9aBcDeF on dashboard Growth/41233): yesterday 412 vs 8-same-weekday
      median 1,048 (MAD 95) → robust z = 4.8. Prior 7 same-weekdays all within ±1.5 z. Latest
      complete day only; today's partial bucket excluded.
  - source_id: aB12cD34
    description: >
      Write-up with the -63d chart, the per-weekday baseline, and the segment attribution:
      https://us.posthog.com/project/41233/notebooks/aB12cD34
summary: |
  Daily signups dropped to 412 yesterday (2026-06-06) against an ~1,048 same-weekday baseline
  (robust z = 4.8, MAD 95) on insight 9aBcDeF, pinned to the Growth dashboard (41233).

  **Pattern** — a single complete-day drop of ~60%, well outside the weekday rhythm: the last 8
  same weekdays were all within ±1.5 z, so it's not seasonality, and it's not a pipeline gap (other
  insights are unaffected at the same timestamp).
  **Hypothesis** — likely a broken signup flow or a tracking regression from a recent deploy.
  Recommend: open insight 9aBcDeF, check whether the drop is broad or segment-specific, and
  correlate with today's deploys. Full write-up with charts:
  https://us.posthog.com/project/41233/notebooks/aB12cD34.
```

Why it's good: quantified title and hook with the baseline and z, seasonality and pipeline-gap
explicitly ruled out, partial bucket excluded, actionable recommendation, the notebook cited in
evidence and linked from the summary, `requires_human_input` (a human decides the fix) with P1
justified by business impact, and a reviewer set so it routes to an owner.
