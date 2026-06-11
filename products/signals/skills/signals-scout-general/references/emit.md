# Emit: how to call `signals-scout-emit-signal`

Read this before your first emit. The harness validates request shape but doesn't
grade prose quality — that's on you.

## Required fields

| Field         | Type   | Constraint      |
| ------------- | ------ | --------------- |
| `description` | string | non-empty prose |
| `confidence`  | float  | `[0.0, 1.0]`    |
| `evidence`    | list   | 0-20 entries    |

## Recommended fields (use them; the inbox uses them)

| Field          | Type                   | When                                                                 |
| -------------- | ---------------------- | -------------------------------------------------------------------- |
| `hypothesis`   | string                 | Always — one-line root-cause hypothesis the finding tests.           |
| `severity`     | `P0`-`P4`              | Always — informational; calibrates downstream review.                |
| `dedupe_keys`  | list of strings        | Always — see "Dedupe keys" below.                                    |
| `time_range`   | `{date_from, date_to}` | When the finding has a clear window (burst, deploy, experiment).     |
| `finding_id`   | string                 | Always — stable trace id (not a dedupe key); see "Finding ID" below. |
| `mcp_trace_id` | string                 | When you used MCP queries you'd want a reviewer to replay.           |

## Description prose contract

The description becomes the inbox surface and the dedupe target. A busy human
reads it in a feed of 30 other findings. Aim for one tight paragraph (3-6
sentences):

1. **Hook** — what's happening, quantified.
   _"High-volume UndefinedTable errors started firing at 11:31 UTC today — 434
   occurrences across 434 distinct users."_

2. **Pattern** — the shape that makes this signal not noise.
   _"One occurrence per user, all on the same fingerprint, confined to a 2-hour
   window — indicates a per-request server path, not a stray exception."_

3. **Hypothesis** — what you think the cause is.
   _"Likely an ORM query against a `PropertyAccessControl` model whose Postgres
   migration didn't ship to this environment."_

4. **Lineage** — if a prior run touched a related topic, cite its `finding_id`.

5. **Recommendation** — what action would resolve it.

Quantify ("434 users") over qualitative ("many users"). Cite entity IDs (issue
ids, recording ids, dashboard ids) inline so a human can pivot straight from
prose to source.

## Confidence rubric (epistemic certainty)

`confidence` is your certainty the finding is _real_. It is the emit gate: a
finding you can't stand behind belongs in the scratchpad, not the inbox. You do
not rank findings yourself — the inbox handles ordering once you emit.

| Range       | Use when                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------- |
| `0.85-1.00` | Multiple corroborating queries; pattern unambiguous; verified not in inbox or scratchpad. |
| `0.65-0.84` | One strong query + plausible hypothesis; minor unknowns remain.                           |
| `0.40-0.64` | Suggestive pattern with material gaps you'd want a human to validate.                     |
| `0.00-0.39` | Don't emit. Gather more evidence or skip.                                                 |

If you can't get to `confidence ≥ 0.65`, prefer a scratchpad entry over emitting.

## Severity mapping

`P0`-`P4` is informational only — no automated routing — but use it consistently:

| Severity | Meaning                                                               |
| -------- | --------------------------------------------------------------------- |
| `P0`     | Active critical impact (data loss, total outage, security exposure).  |
| `P1`     | Active material impact (errors hitting many users, billing affected). |
| `P2`     | Confirmed issue, contained scope or non-urgent mitigation path.       |
| `P3`     | Suspected issue or minor confirmed issue.                             |
| `P4`     | Curiosity / FYI.                                                      |

## Evidence list shape

Each entry: `{source_product, summary, entity_id?}`. The harness caps at 20.

- `source_product` — short string identifying where the citation came from. Common
  values: `error_tracking`, `session_replay`, `logs`, `feature_flag`, `experiment`,
  `web_analytics`, `data_warehouse`, `query_runs`, `signals_scout` (cite a prior
  run / finding), `inbox` (cite a SignalReport).
- `summary` — one sentence on _why this evidence supports the finding_.
- `entity_id` — the citable id. Pin issue UUIDs, recording IDs, dashboard
  short_ids, insight short_ids, prior `scout_run_id`s, prior `finding_id`s.

Include a citation for every concrete claim in the description.

## Dedupe keys

Stable strings the inbox uses to group related findings across runs and sources.
Format: `<kind>:<entity_id>` or `<kind>:<entity_id>:<qualifier>`.

Common kinds: `error_tracking_issue:<id>`, `experiment:<id>`, `feature_flag:<key>`,
`warehouse_source:<id>`, `dashboard:<id>`, `insight:<short_id>`,
`missing_migration:<table_name>`, `traffic_anomaly:<event_name>`.

Include 1-2 keys per finding. Multiple is fine when a finding spans entities.

## Finding ID

`finding_id` is a stable, human-readable trace id — it ties the emitted signal
back to the run that produced it (stored in the signal's `source_id` metadata). It
is **not** a dedupe key: `emit_signal` dedupes on its own generated `document_id`
(and your `dedupe_keys`), never on `finding_id`. Re-calling emit with the same
`finding_id` writes a _second_ signal — so never retry an emit that may already
have succeeded. Format: `<topic>-<entity>-<date>` is a safe default.

Examples:

- `missing-migration-access-control-propertyaccesscontrol-2026-05-01`
- `experiment-checkout-flow-conversion-drop-2026-04-29`
- `warehouse-stripe-charges-stuck-2026-04-30`

Stable, human-readable, dated. A recurrence on a later day becomes a new finding
(cite the prior `finding_id` in the description).

## Worked example

Real finding from a shadow run on 2026-05-01:

```yaml
finding_id: missing-migration-access-control-propertyaccesscontrol-2026-05-01
confidence: 0.9
severity: P1
hypothesis: >
  A new access_control.PropertyAccessControl model is referenced in production
  code paths without its Postgres migration applied — every per-request ORM
  check hits the missing table.
evidence:
  - source_product: error_tracking
    entity_id: 019de34e-e2a3-7e53-80d0-8ccdd0866a36
    summary: >
      Primary issue UndefinedTable on access_control_propertyaccesscontrol —
      434 occurrences across 434 distinct users between 11:31 and 13:22 UTC.
  - source_product: error_tracking
    entity_id: 019de34e-48ea-7e12-b76a-106d06e2f153
    summary: >
      POST /api/environments/1/query/HogQLQuery/ returning 500, first seen at
      11:30:49Z — same window, likely same root cause.
  - source_product: signals_scout
    entity_id: 019de09b-bd36-78a7-b3ff-fba34c252187
    summary: >
      Prior run on 2026-04-30 surfaced the same class of bug (signals refactor
      missing migration) — internal-only blast radius. Today's pattern is the
      end-user-facing equivalent.
time_range:
  date_from: 2026-05-01T11:31:30Z
  date_to: 2026-05-01T13:22:02Z
dedupe_keys:
  - error_tracking_issue:019de34e-e2a3-7e53-80d0-8ccdd0866a36
  - missing_migration:access_control_propertyaccesscontrol
description: |
  High-volume UndefinedTable / ProgrammingError: relation
  "access_control_propertyaccesscontrol" does not exist started firing at
  2026-05-01T11:31:30Z (issue 019de34e-e2a3-7e53-80d0-8ccdd0866a36, active, no
  assignee). 434 occurrences across 434 distinct users between 11:31 and 13:22
  UTC — one hit per user indicates a per-request code path (likely an ORM check
  on the new access_control.PropertyAccessControl model). Continuation of
  yesterday's signals-backend refactor cluster (run
  019de09b-bd36-78a7-b3ff-fba34c252187, internal-only) but with much wider
  blast radius. Recommend confirming the migration adding
  access_control_propertyaccesscontrol is in the deployed set, running it, then
  verifying the issue stops firing. None of these are in the inbox.
```

Why this is a good finding:

- **Quantified hook**: 434/434 in a precise 2-hour window.
- **Pattern explained**: "one hit per user" rules out alternatives.
- **Lineage**: cites prior run id; the inbox groups them.
- **Recommendation**: actionable.
- **Evidence**: diverse sources strengthen confidence.
- **Dedupe keys**: both issue-id and topic-keyed, dedupes either way.
- **Severity**: P1 justified by 434-user blast.
- **Confidence 0.9**: pattern unambiguous; remaining uncertainty is "did the
  migration actually not ship, or is something else mocking this table?"
