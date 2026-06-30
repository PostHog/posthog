# The emit contract

How a scout calls `signals-scout-emit-signal`, and how to write a scout's **Decide**
section so it emits well-calibrated findings. This is the contract the signal-emitting fleet
runs on — author your scout so its findings fit this shape. (The canonical generalist,
`signals-scout-general`, is report-only and authors `SignalReport`s directly instead, via the
report channel — whose contract rides in the harness prompt, not a bundled reference.) The
harness validates request shape but does **not** grade prose quality; that's on the scout.

## Fields

| Field          | Type                   | Required     | Notes                                                  |
| -------------- | ---------------------- | ------------ | ------------------------------------------------------ |
| `description`  | string                 | ✅           | Non-empty prose — the inbox surface and dedupe target. |
| `confidence`   | float `[0,1]`          | ✅           | Epistemic certainty the finding is real.               |
| `evidence`     | list (0–20)            | ✅           | `{source_product, summary, entity_id?}` per entry.     |
| `hypothesis`   | string                 | recommended  | One-line root-cause hypothesis the finding tests.      |
| `severity`     | `P0`–`P4`              | recommended  | Informational only; no routing.                        |
| `dedupe_keys`  | list of strings        | recommended  | `<kind>:<entity_id>` — groups across runs/sources.     |
| `time_range`   | `{date_from, date_to}` | when bounded | For bursts, deploys, experiments.                      |
| `finding_id`   | string                 | recommended  | Stable trace id, **not** a dedupe key (see below).     |
| `mcp_trace_id` | string                 | optional     | When you want a reviewer to replay MCP queries.        |

## Confidence — the emit gate

`confidence` = how sure the scout is the finding is real. It is the emit gate: a finding the
scout can't stand behind belongs in the scratchpad, not the inbox. The scout does not rank
findings itself — the inbox handles ordering once a finding is emitted.

**Confidence rubric:**

| Range     | Use when                                                                           |
| --------- | ---------------------------------------------------------------------------------- |
| 0.85–1.00 | Multiple corroborating queries; pattern unambiguous; verified not already covered. |
| 0.65–0.84 | One strong query + plausible hypothesis; minor unknowns remain.                    |
| 0.40–0.64 | Suggestive pattern with material gaps a human should validate.                     |
| 0.00–0.39 | Don't emit — gather more evidence or skip.                                         |

**The emit gate:** if a scout can't reach `confidence ≥ 0.65`, it should write a scratchpad
entry instead of emitting. Bake this threshold into the scout's Decide section.

## Severity

`P0`–`P4`, informational only — use consistently. P0: active critical (data loss, outage,
security). P1: active material (errors hitting many users, billing). P2: confirmed,
contained. P3: suspected or minor confirmed. P4: curiosity / FYI. Recommendation-style
scouts (e.g. observability gaps) emit P3 by default rather than P0–P2 anomalies.

## Description prose contract

The description is what a busy human reads in a feed of 30 other findings. Aim for one tight
paragraph (3–6 sentences):

1. **Hook** — what's happening, **quantified** ("434 occurrences across 434 distinct users"
   beats "many users").
2. **Pattern** — the shape that makes this signal, not noise ("one occurrence per user →
   per-request server path").
3. **Hypothesis** — the suspected cause.
4. **Lineage** — if a prior run touched a related topic, cite its `finding_id`.
5. **Recommendation** — the action that would resolve it.

Cite entity ids (issue ids, recording ids, dashboard short_ids) inline so a human pivots
straight from prose to source.

## Evidence

Each entry `{source_product, summary, entity_id?}`, capped at 20. Include a citation for
**every** concrete claim in the description. `source_product` is a short origin label —
common values: `error_tracking`, `session_replay`, `logs`, `feature_flag`, `experiment`,
`web_analytics`, `data_warehouse`, `query_runs`, `signals_scout` (cite a prior run/finding),
`inbox` (cite a report). `entity_id` pins the citable id.

## Dedupe keys

Stable strings the inbox uses to group related findings across runs and sources. Format
`<kind>:<entity_id>` or `<kind>:<entity_id>:<qualifier>`. Common kinds:
`error_tracking_issue:<id>`, `experiment:<id>`, `feature_flag:<key>`, `dashboard:<id>`,
`insight:<short_id>`, `missing_migration:<table>`, `traffic_anomaly:<event>`. Include 1–2
per finding; more is fine when a finding spans entities. **This is the primary anti-duplicate
mechanism — design your scout's dedupe keys deliberately.**

## finding_id (not a dedupe key)

`finding_id` is a stable, human-readable trace id tying the emitted signal back to its run.
It is **not** used for idempotency: `emit_signal` dedupes on its own generated `document_id`
and your `dedupe_keys`, never on `finding_id`. **Re-calling emit with the same `finding_id`
writes a second signal — so a scout must never retry an emit that may already have
succeeded.** Format `<topic>-<entity>-<date>`, e.g.
`missing-migration-access-control-propertyaccesscontrol-2026-05-01`. A recurrence on a later
day is a new finding that cites the prior `finding_id` in its description.

## Worked example

```yaml
finding_id: missing-migration-access-control-propertyaccesscontrol-2026-05-01
confidence: 0.9
severity: P1
hypothesis: >
  A new access_control.PropertyAccessControl model is referenced in production code paths
  without its Postgres migration applied — every per-request ORM check hits the missing table.
evidence:
  - source_product: error_tracking
    entity_id: 019de34e-e2a3-7e53-80d0-8ccdd0866a36
    summary: >
      UndefinedTable on access_control_propertyaccesscontrol — 434 occurrences across 434
      distinct users between 11:31 and 13:22 UTC.
  - source_product: signals_scout
    entity_id: 019de09b-bd36-78a7-b3ff-fba34c252187
    summary: Prior run surfaced the same class of bug (missing migration), internal-only blast radius.
time_range: { date_from: 2026-05-01T11:31:30Z, date_to: 2026-05-01T13:22:02Z }
dedupe_keys:
  - error_tracking_issue:019de34e-e2a3-7e53-80d0-8ccdd0866a36
  - missing_migration:access_control_propertyaccesscontrol
description: |
  High-volume UndefinedTable: relation "access_control_propertyaccesscontrol" does not exist
  started firing at 2026-05-01T11:31:30Z (issue 019de34e..., active). 434 occurrences across
  434 distinct users in a 2-hour window — one hit per user indicates a per-request ORM check
  on the new access_control.PropertyAccessControl model. Continuation of yesterday's signals
  refactor cluster (run 019de09b...) but with far wider blast radius. Recommend confirming the
  migration is in the deployed set, running it, then verifying the issue stops firing.
```

Why it's good: quantified hook (434/434 in a precise window), pattern explained ("one hit
per user" rules out alternatives), lineage cited so the inbox groups it, actionable
recommendation, dual dedupe keys (issue-id + topic), P1 justified by blast radius, confidence
0.9 because the pattern is unambiguous.
