# Finding schema reference

Read this before your first call to `signals-agent-harness-runs-findings-create`.
The harness validates request shape but doesn't grade prose quality — that's on you.

## Required fields

| Field         | Type   | Constraint      |
| ------------- | ------ | --------------- |
| `description` | string | non-empty prose |
| `weight`      | float  | `[0.0, 1.0]`    |
| `confidence`  | float  | `[0.0, 1.0]`    |
| `evidence`    | list   | 0-20 entries    |

## Optional fields (use them; the inbox uses them)

| Field          | Type            | Use when                                                         |
| -------------- | --------------- | ---------------------------------------------------------------- |
| `hypothesis`   | string          | Always — one-line root-cause hypothesis the finding tests.       |
| `severity`     | `P0`-`P4`       | Always — informational; calibrates downstream review.            |
| `dedupe_keys`  | list of strings | Always — see "Dedupe keys" below.                                |
| `time_range`   | `{from, to}`    | When the finding has a clear window (burst, deploy, experiment). |
| `finding_id`   | string          | Always — see "Finding ID" below; idempotency key.                |
| `mcp_trace_id` | string          | When you used MCP queries you'd want a reviewer to replay.       |

## Description prose contract

The description becomes the inbox surface and the dedupe key. Treat it as the thing a
busy human reads in a feed of 30 other findings. Aim for one tight paragraph (3-6
sentences):

1. **Hook**: what's happening, quantified.
   _e.g. "High-volume `UndefinedTable` errors started firing at 11:31 UTC today —
   434 occurrences across 434 distinct users."_

2. **Pattern**: the shape that makes this a signal not noise.
   _e.g. "One occurrence per user, all on the same fingerprint, confined to a 2-hour
   window — indicates a per-request server path, not a stray exception."_

3. **Hypothesis**: what you think the cause is.
   _e.g. "Likely an ORM query against a `PropertyAccessControl` model whose Postgres
   migration didn't ship to this environment."_

4. **Lineage**: if a prior run touched a related topic, cite the prior finding's id.
   _e.g. "Continuation of pattern from prior run `019de09b-...` (signals refactor missed
   migrations) but with end-user blast radius this time."_

5. **Recommendation**: what action would resolve it.
   _e.g. "Confirm the migration adding `access_control_propertyaccesscontrol` is in the
   deployed set; run it and verify the three fingerprints stop firing."_

Keep it concrete. Quantify ("434 users") over qualitative ("many users").
Cite entity IDs (issue ids, recording ids, dashboard ids) inline so a human can pivot
straight from prose to source.

## Weight rubric (ranking score)

`weight` ranks findings within the inbox feed. Higher = more attention-worthy _to a
human reviewer_, not "more confident" — that's `confidence`.

| Range       | Use when                                                                             |
| ----------- | ------------------------------------------------------------------------------------ |
| `0.85-1.00` | Active customer impact, large blast radius, or a deploy regression with a clear fix. |
| `0.65-0.84` | Material pattern worth investigating today; not yet user-impacting at scale.         |
| `0.40-0.64` | Notable but speculative; or a confirmed minor issue worth the team knowing about.    |
| `0.20-0.39` | Curiosity-level — the team would probably want to know but it's not urgent.          |
| `0.00-0.19` | Don't emit at this weight. Skip or `remember()` instead.                             |

## Confidence rubric (epistemic certainty)

`confidence` is your certainty the finding is _real_ — independent of weight.

| Range       | Use when                                                                              |
| ----------- | ------------------------------------------------------------------------------------- |
| `0.85-1.00` | Multiple corroborating queries; pattern is unambiguous; verified not in inbox/memory. |
| `0.65-0.84` | One strong query + plausible hypothesis; minor unknowns remain.                       |
| `0.40-0.64` | Suggestive pattern with material gaps you'd want a human to validate.                 |
| `0.00-0.39` | Don't emit. Either gather more evidence or skip.                                      |

If you can't get to `confidence ≥ 0.65`, prefer `remember()` over `emit_finding()`.

## Evidence list shape

Each entry: `{source_product, summary, entity_id?}`. The harness caps at 20.

- `source_product`: short string identifying where the citation came from. Common values:
  `error_tracking`, `session_replay`, `logs`, `feature_flag`, `experiment`,
  `web_analytics`, `data_warehouse`, `query_runs`, `signals_agent` (cite a prior run /
  finding), `inbox` (cite a SignalReport).
- `summary`: one sentence on _why this evidence supports the finding_. The reviewer reads
  this before clicking through.
- `entity_id`: the citable id. Pin issue UUIDs, recording IDs, dashboard short_ids,
  insight short_ids, prior `agent_run_id`s, prior `finding_id`s.

Include a citation for every concrete claim in the description. If you wrote "434
occurrences across 434 distinct users", the corresponding evidence entry should have an
`entity_id` for the issue and a summary that names the count + the window.

## Hypothesis field

One sentence. The agent's best guess at root cause. Surfaces alongside the description in
the inbox so a human can validate or refute quickly. Skip if you genuinely can't form one
— but in that case ask whether `confidence` is too high.

## Severity mapping

`P0`-`P4` is informational only — no automated routing — but use it consistently:

| Severity | Meaning                                                               |
| -------- | --------------------------------------------------------------------- |
| `P0`     | Active critical impact (data loss, total outage, security exposure).  |
| `P1`     | Active material impact (errors hitting many users, billing affected). |
| `P2`     | Confirmed issue, contained scope or non-urgent mitigation path.       |
| `P3`     | Suspected issue or minor confirmed issue.                             |
| `P4`     | Curiosity / FYI.                                                      |

## Dedupe keys

`dedupe_keys` are stable strings the inbox uses to group related findings across runs and
sources. Format: `<kind>:<entity_id>` or `<kind>:<entity_id>:<qualifier>`.

Common kinds: `error_tracking_issue:<id>`, `experiment:<id>`, `feature_flag:<key>`,
`warehouse_source:<id>`, `dashboard:<id>`, `insight:<short_id>`,
`missing_migration:<table_name>`, `traffic_anomaly:<event_name>`.

Include 1-2 keys per finding. Multiple is fine when the finding spans entities.

## Finding ID

`finding_id` is the idempotency key. Same id on a retry short-circuits the emit (no
double-write). Format: `<topic>-<entity>-<date>` is a safe default.

Examples:

- `missing-migration-access-control-propertyaccesscontrol-2026-05-01`
- `experiment-checkout-flow-conversion-drop-2026-04-29`
- `warehouse-stripe-charges-stuck-2026-04-30`

Stable, human-readable, dated. The date scopes "this finding for this day" so a recurrence
on a later day is a new finding (and you'd cite the prior `finding_id` in the description).

## Worked example: the access-control missing-migration finding

Real finding from a shadow run on 2026-05-01. Reproduced here verbatim as a template.

```yaml
finding_id: missing-migration-access-control-propertyaccesscontrol-2026-05-01
weight: 0.92
extra:
  confidence: 0.9
  severity: P1
  hypothesis: >
    A new access_control.PropertyAccessControl model is referenced in production code
    paths without its Postgres migration applied — every per-request ORM check hits the
    missing table.
  evidence:
    - source_product: error_tracking
      entity_id: 019de34e-e2a3-7e53-80d0-8ccdd0866a36
      summary: >
        Primary issue UndefinedTable/ProgrammingError on relation
        access_control_propertyaccesscontrol — 434 occurrences across 434 distinct users
        between 11:31 and 13:22 UTC, no further occurrences since.
    - source_product: error_tracking
      entity_id: 019de34e-42b4-7853-8b27-c486cb77931a
      summary: >
        Separate fingerprint of the same UndefinedTable error on the same relation;
        co-occurring with the primary issue.
    - source_product: error_tracking
      entity_id: 019de34e-48ea-7e12-b76a-106d06e2f153
      summary: >
        POST /api/environments/1/query/HogQLQuery/ returning 500, first seen at
        11:30:49Z — same window, likely same root cause.
    - source_product: logs
      summary: >
        HogQL aggregation: 244 + 190 = 434 occurrences across 434 distinct users in
        2026-05-01T11:31-13:22Z.
    - source_product: signals_agent
      entity_id: 019de09b-bd36-78a7-b3ff-fba34c252187
      summary: >
        Prior run on 2026-04-30 surfaced the same class of bug (signals refactor missing
        migration cluster) — internal-only blast radius. Today's pattern is the
        end-user-facing equivalent.
  time_range:
    date_from: 2026-05-01T11:31:30Z
    date_to: 2026-05-01T13:22:02Z
  dedupe_keys:
    - error_tracking_issue:019de34e-e2a3-7e53-80d0-8ccdd0866a36
    - missing_migration:access_control_propertyaccesscontrol

description: |
  High-volume UndefinedTable / ProgrammingError: relation
  "access_control_propertyaccesscontrol" does not exist started firing today at
  2026-05-01T11:31:30Z (issue 019de34e-e2a3-7e53-80d0-8ccdd0866a36, status=active, no
  assignee). It hit 434 occurrences across 434 distinct users between 11:31 and 13:22
  UTC — i.e. one hit per user, indicating a per-request code path (likely an ORM check
  on the new access_control.PropertyAccessControl model) running for every active
  session. The pattern is a continuation of yesterday's signals-backend refactor cluster
  (prior finding from run 019de09b-bd36-78a7-b3ff-fba34c252187, internal-only) but with
  much wider blast radius — touched 434 distinct end-user sessions in two hours before
  tapering off at 13:22Z. Two related fresh issues from the same window are likely the
  same root cause: 019de34e-48ea (HogQLQuery 500) and 019de34e-42b4 (alt fingerprint of
  the UndefinedTable error). Recommend: confirm whether a migration adding the
  access_control_propertyaccesscontrol table is missing from the deployed set, run it,
  then verify all three fingerprints stop firing. None of these issues are in the inbox.
```

Why this is a good finding:

- **Quantified hook**: 434/434 in a precise 2-hour window is concrete.
- **Pattern explained**: "one hit per user" rules out the alternative explanations.
- **Lineage**: cites the prior run by id; the inbox can group them.
- **Recommendation**: actionable — exactly what a human on call would do.
- **Evidence scope**: 5 entries spanning error_tracking + logs + signals_agent (lineage)
  — diverse sources strengthen confidence.
- **Dedupe keys**: both issue-id and topic-keyed so a recurrence dedupes either way.
- **Severity**: P1 justified by 434-user blast.
- **Confidence 0.9**: pattern is unambiguous; remaining uncertainty is "did the migration
  actually not ship, or is something else mocking this table?"
