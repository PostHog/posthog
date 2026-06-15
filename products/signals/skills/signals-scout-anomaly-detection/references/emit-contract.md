# The emit contract

How this scout calls `signals-scout-emit-signal` and writes a well-calibrated finding. The
harness validates request shape but does **not** grade prose — that's on you. This mirrors the
contract the whole signals-scout fleet runs on.

## Fields

| Field         | Type                   | Required     | Notes                                                  |
| ------------- | ---------------------- | ------------ | ------------------------------------------------------ |
| `description` | string                 | ✅           | Non-empty prose — the inbox surface and dedupe target. |
| `confidence`  | float `[0,1]`          | ✅           | How sure you are the finding is real.                  |
| `evidence`    | list (0–20)            | ✅           | `{source_product, summary, entity_id?}` per entry.     |
| `hypothesis`  | string                 | recommended  | One-line root-cause hypothesis.                        |
| `severity`    | `P0`–`P4`              | recommended  | Informational only; no routing.                        |
| `dedupe_keys` | list of strings        | recommended  | `<kind>:<entity_id>` — groups across runs/sources.     |
| `time_range`  | `{date_from, date_to}` | when bounded | The anomalous window.                                  |
| `finding_id`  | string                 | recommended  | Stable trace id, **not** a dedupe key (see below).     |

## Confidence — the emit gate

`confidence` = how sure you are the finding is real. It is the emit gate: a finding you can't
stand behind belongs in the scratchpad, not the inbox. You do not rank findings yourself — the
inbox handles ordering once you emit.

**Confidence:** 0.85–1.00 unambiguous (high z, guards passed, seasonality ruled out, not
already reported); 0.65–0.84 one strong read + plausible cause, minor unknowns; < 0.65 don't
emit — refresh the baseline instead.

**The emit gate:** if you can't reach `confidence ≥ 0.65`, write a scratchpad entry, don't
emit. For this scout, a strong finding is **robust z ≥ ~3.5 on the latest complete bucket**,
the guards in `anomaly-methods.md` passed, the move not explained by seasonality or a pipeline
gap, confidence ≥ 0.85.

## Severity

`P0` active critical (outage / data loss); `P1` active material (revenue/conversion drop
hitting the business now); `P2` confirmed contained; `P3` suspected or minor confirmed; `P4`
FYI / curiosity. A sustained drop-to-zero on a key metric is typically P1; a one-bucket spike
that's already receding is P2–P3.

## Description prose contract

One tight paragraph (3–6 sentences) a busy human reads in a feed of 30:

1. **Hook** — what moved, **quantified**: "daily signups dropped to 412 yesterday vs an
   ~1,050 same-weekday baseline (robust z = 4.8)".
2. **Pattern** — the shape that makes it signal not noise: direction, that it cleared the
   seasonality-matched baseline, whether it's one bucket or sustained.
3. **Hypothesis** — the suspected cause (deploy, experiment, pipeline, real behavior change).
4. **Lineage** — if a prior run touched this insight, cite its `finding_id`.
5. **Recommendation** — the next action (which insight to open, what to check).

Cite the insight `short_id` and dashboard id inline so a human pivots straight to the source.

## Evidence

Each entry `{source_product, summary, entity_id?}`, ≤ 20. Cite every concrete claim. For this
scout: `source_product: query_runs` (the SQL/insight-query reads), `entity_id` = the insight
`short_id`; add `signals_scout` entries to cite a prior run/finding. Put the bucket value,
the baseline median, the z-score, and the time window in the summaries. Add one
`source_product: notebook` entry whose `entity_id` is the notebook `short_id` and whose
summary is a brief description of the write-up followed by the notebook URL (see below) —
that is the durable artifact the human opens.

## The notebook write-up

The inbox description is a 3–6 sentence hook; the **notebook is the durable artifact** behind
it — the place a human lands to see the charts, the baseline math, and the attribution that
justify the call. **Build the notebook _before_ you emit**, then reference its URL from the
signal. One notebook per emitted finding.

### Create it

Call `notebooks-create` with a `title` and `content` (ProseMirror rich-text JSON). The
response carries the new notebook's `short_id` and a clickable URL (the tool enriches the
result with `/notebooks/{short_id}`) — that URL is what you wire into the emit. If you ever
need to build the link yourself, it is `generate-app-url` with `url=/notebooks/{shortId}`.

- **Title** — name the metric, the direction, and the date, e.g.
  `Anomaly: daily signups dropped ~60% (2026-06-06)`. A human scanning a notebook list should
  recognise it.
- **One notebook per finding** — never append a new anomaly to a prior run's notebook. A
  recurrence on a later day is a new notebook citing the prior one, mirroring the dedupe-key
  convention.

### What goes in it

Lead with the same hook the inbox sees, then the evidence the 3–6 sentences can't hold:

1. **Summary** — the quantified hook (bucket value vs baseline, robust z, severity), one or
   two sentences. Same claim as the description, so the notebook stands alone.
2. **The chart** — embed the anomalous series so the spike/drop is visible, and make sure the
   window is wide enough (e.g. `-63d`) that the baseline _and_ the break are both on screen. A
   `SavedInsightNode` renders the insight's own saved date range and carries no date override —
   so use it only when that saved range already shows the baseline; if the insight is saved to a
   short window (often `-7d`), embed an inline widened `DataVisualizationNode` (or
   `InsightVizNode`) for the scored window instead, so the write-up keeps the very evidence it
   exists to preserve.
3. **Baseline & method** — the seasonality-matched baseline (median + MAD per bucket), the
   z-score, which detector(s) `alert-simulate` fired, and that the partial bucket was excluded.
   This is the math that doesn't fit the inbox hook.
4. **Attribution** — which breakdown segment(s) drove the move (the attribution read from the
   investigation), and whether it's broad (regression) or one segment (often expected).
5. **Hypothesis & next step** — suspected cause and what to check, matching the emit hypothesis.

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

Prefer embedding the saved insight you scored — it stays in sync with the source and is the
thing the human will open next. Give each `ph-query` node a distinct `nodeId`. `notebooks-create`
returns the new notebook's URL in `_posthogUrl` — surface that verbatim, don't hand-build it.

`content` is a ProseMirror doc (the tool documents no node schema, so use this skeleton). Text
is `paragraph` / `heading` (with `attrs.level`) / `bulletList` → `listItem` → `paragraph`;
charts are `ph-query` nodes. A minimal working shape:

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

### Wire it into the emit

- **Description** — add a closing clause: "Full write-up with charts: `<notebook-url>`."
- **Evidence** — one `{source_product: notebook, entity_id: <short_id>, summary: <brief description + url>}` entry.
- **dedupe_keys** — optionally add `notebook:<short_id>` so the artifact is traceable from the
  signal's `extra`.

**Clean up if the emit doesn't land.** `signals-scout-emit-signal` is preflight-gated — on a
dry-run config (`emit=False`), un-approved AI processing, or a disabled source it returns a
`skipped_reason` and writes **no** signal. The notebook, gated only by `notebook:write`, has
already been created — so an orphaned user-facing artifact would leak into the project,
breaking the dry-run/source-disabled contract. **If the emit result is skipped (not emitted),
delete the just-created notebook with `notebooks-destroy`.** Only a notebook attached to a real
emitted signal should survive the run.

Skipping notebook _creation_ is only acceptable if `notebooks-create` fails — then emit anyway
(the finding still matters) and note the missing artifact in the description.

## Dedupe keys

Stable strings stored on the signal for traceability and grouping context — they are recorded
in the signal's `extra`, **not** enforced as idempotency keys by `emit_signal` (grouping is
semantic). Your own dedupe is the scratchpad / run-history check before emitting. Use
`insight:<short_id>` and a metric-anomaly key like `metric_anomaly:<short_id>:<date>` so a
recurrence on a later day reads as a new finding citing the prior one. Add `dashboard:<id>`
when relevant. Include 1–2.

## finding_id (not a dedupe key)

A stable, human-readable trace id tying the signal to its run — e.g.
`anomaly-revenue-over-time-ym0K91uz-2026-06-07`. It is **not** used for idempotency: the
pipeline assigns every signal a fresh random `document_id` and dedupes on that, never on
`finding_id` — and never on your `dedupe_keys` either (those are stored in `extra` for the
inbox to group on _after_ ingest, they don't make a repeat emit idempotent).
**Re-calling emit with the same `finding_id` writes a second signal — never retry an emit that
may already have succeeded.** A recurrence on a later day is a new finding citing the prior id.

## Worked example

```yaml
finding_id: anomaly-daily-signups-9aBcDeF-2026-06-07
confidence: 0.88
severity: P1
hypothesis: >
  Daily signups dropped ~60% below the same-weekday baseline starting yesterday — likely a
  broken signup flow or a tracking regression from a recent deploy.
evidence:
  - source_product: query_runs
    entity_id: 9aBcDeF
    summary: >
      'Daily signups' (insight 9aBcDeF on dashboard Growth/41233): yesterday 412 vs
      8-same-weekday median 1,048 (MAD 95) → robust z = 4.8. Prior 7 same-weekdays all
      within ±1.5 z. Latest complete day only; today's partial bucket excluded.
  - source_product: notebook
    entity_id: aB12cD34
    summary: >
      Write-up with the -63d chart, the per-weekday baseline, and the segment attribution:
      https://us.posthog.com/project/41233/notebooks/aB12cD34
time_range: { date_from: 2026-06-06T00:00:00Z, date_to: 2026-06-07T00:00:00Z }
dedupe_keys:
  - insight:9aBcDeF
  - metric_anomaly:9aBcDeF:2026-06-06
  - notebook:aB12cD34
description: |
  Daily signups dropped to 412 yesterday (2026-06-06) against an ~1,048 same-weekday baseline
  (robust z = 4.8, MAD 95) on insight 9aBcDeF, pinned to the Growth dashboard (41233). This is
  a single complete-day drop of ~60%, well outside the weekday rhythm — the last 8 same
  weekdays were all within ±1.5 z, so it's not seasonality. Likely a broken signup flow or a
  tracking regression from a recent deploy. Recommend opening insight 9aBcDeF, checking
  whether the drop is broad or segment-specific, and correlating with today's deploys. Full
  write-up with charts: https://us.posthog.com/project/41233/notebooks/aB12cD34.
```

Why it's good: quantified hook with the baseline and z, seasonality explicitly ruled out,
partial bucket excluded, actionable recommendation, dual dedupe keys (insight + dated
metric anomaly), P1 justified by business impact, confidence 0.88 because the read is clean.
The notebook the scout built before emitting is cited in the evidence and linked from the
description, so the human lands on the charts and baseline math in one click.
