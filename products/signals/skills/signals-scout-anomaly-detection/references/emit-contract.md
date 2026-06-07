# The emit contract

How this scout calls `signals-scout-emit-signal` and writes a well-calibrated finding. The
harness validates request shape but does **not** grade prose — that's on you. This mirrors the
contract the whole signals-scout fleet runs on.

## Fields

| Field         | Type                   | Required     | Notes                                                  |
| ------------- | ---------------------- | ------------ | ------------------------------------------------------ |
| `description` | string                 | ✅           | Non-empty prose — the inbox surface and dedupe target. |
| `weight`      | float `[0,1]`          | ✅           | How much human attention this deserves.                |
| `confidence`  | float `[0,1]`          | ✅           | How sure you are the finding is real.                  |
| `evidence`    | list (0–20)            | ✅           | `{source_product, summary, entity_id?}` per entry.     |
| `hypothesis`  | string                 | recommended  | One-line root-cause hypothesis.                        |
| `severity`    | `P0`–`P4`              | recommended  | Informational only; no routing.                        |
| `dedupe_keys` | list of strings        | recommended  | `<kind>:<entity_id>` — groups across runs/sources.     |
| `time_range`  | `{date_from, date_to}` | when bounded | The anomalous window.                                  |
| `finding_id`  | string                 | recommended  | Stable trace id, **not** a dedupe key (see below).     |

## Weight vs confidence — keep distinct

`weight` = how much attention it deserves; `confidence` = how sure it's real. A confidently
real but minor blip is high-confidence, low-weight.

**Weight:** 0.85–1.00 active customer/business impact or large blast radius; 0.65–0.84
material move worth looking at today; 0.40–0.64 notable but speculative; < 0.20 don't emit.

**Confidence:** 0.85–1.00 unambiguous (high z, guards passed, seasonality ruled out, not
already reported); 0.65–0.84 one strong read + plausible cause, minor unknowns; < 0.65 don't
emit — refresh the baseline instead.

**The emit gate:** if you can't reach `confidence ≥ 0.65`, write a scratchpad entry, don't
emit. For this scout, a strong finding is **robust z ≥ ~3.5 on the latest complete bucket**,
the guards in `anomaly-methods.md` passed, the move not explained by seasonality or a pipeline
gap, weight ≥ 0.7, confidence ≥ 0.85.

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
the baseline median, the z-score, and the time window in the summaries.

## Dedupe keys

Stable strings the inbox groups on. Use `insight:<short_id>` and a metric-anomaly key like
`metric_anomaly:<short_id>:<date>` so a recurrence on a later day is a new finding that cites
the prior one rather than silently colliding. Add `dashboard:<id>` when relevant. Include 1–2.

## finding_id (not a dedupe key)

A stable, human-readable trace id tying the signal to its run — e.g.
`anomaly-revenue-over-time-ym0K91uz-2026-06-07`. It is **not** used for idempotency:
`emit_signal` dedupes on its own `document_id` and your `dedupe_keys`, never on `finding_id`.
**Re-calling emit with the same `finding_id` writes a second signal — never retry an emit that
may already have succeeded.** A recurrence on a later day is a new finding citing the prior id.

## Worked example

```yaml
finding_id: anomaly-daily-signups-9aBcDeF-2026-06-07
weight: 0.86
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
time_range: { date_from: 2026-06-06T00:00:00Z, date_to: 2026-06-07T00:00:00Z }
dedupe_keys:
  - insight:9aBcDeF
  - metric_anomaly:9aBcDeF:2026-06-06
description: |
  Daily signups dropped to 412 yesterday (2026-06-06) against an ~1,048 same-weekday baseline
  (robust z = 4.8, MAD 95) on insight 9aBcDeF, pinned to the Growth dashboard (41233). This is
  a single complete-day drop of ~60%, well outside the weekday rhythm — the last 8 same
  weekdays were all within ±1.5 z, so it's not seasonality. Likely a broken signup flow or a
  tracking regression from a recent deploy. Recommend opening insight 9aBcDeF, checking
  whether the drop is broad or segment-specific, and correlating with today's deploys.
```

Why it's good: quantified hook with the baseline and z, seasonality explicitly ruled out,
partial bucket excluded, actionable recommendation, dual dedupe keys (insight + dated
metric anomaly), P1 justified by business impact, confidence 0.88 because the read is clean.
