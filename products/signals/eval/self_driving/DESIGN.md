# Self-Driving SWE-Eval: end-to-end evaluation of autonomous work on signals

Benchmark for the full PostHog Self-Driving loop:
customer signals + real product data in → researched inbox report → autonomous implementation → immediately mergeable PR out.
Inspired by DeepSWE (behavior-graded, containerized, patch-extracted verification) and FrontierSWE (per-workload correctness with gated partial credit),
adapted to the agentic product loop rather than an isolated SWE task.

Unlike `products/signals/eval/eval_grouping_e2e.py` (which mocks ClickHouse/Postgres and grades signal grouping),
this eval runs the **real** pipeline against the **real** local stack:
real Temporal workflows, real ClickHouse (embeddings + seeded product analytics), real Postgres models,
real Docker sandbox agents, real MCP tool access.
Nothing inside the product is mocked; only the world around it (the customer, their repo, their telemetry) is synthetic.

## What one task looks like

A task is a self-contained "customer universe" with planted ground truth:

```text
tasks/<task_id>/
  task.json          # spec: title, difficulty, signal fixture, seed spec, ground truth, rubric
  signals.json       # zendesk/github/linear-format records fed to emit_signals_from_fixture
  repo/              # fixture product repo (template) with the planted defect
  verify/            # hidden behavioral tests run against the patched repo at grade time
```

- **Planted root cause** lives in the repo (a real defect: logic bug, missing handling, perf trap, misconfiguration).
- **Evidence** lives in two layers: the signal text (what a customer would say — deliberately partial/misleading at higher difficulties)
  and seeded ClickHouse data for the task's team ($exception events, funnel drop-offs, custom events) that corroborates or disambiguates.
- **Ground truth** (`task.json`) records the root cause, the fix contract (observable behavior, not implementation),
  expected evidence the researcher should surface, and distractors that should NOT be blamed.

## Isolation & realism mechanics

- One **Postgres team per task** (`provision.py`) inside a dedicated eval org: isolates embeddings, reports, seeded events.
- A **synthetic GitHub Integration** per team whose cached installation token never expires locally —
  repo selection and sandbox provisioning run their real code paths, but no call ever reaches GitHub.
- The fixture repo is **bind-mounted** into the sandbox via `SANDBOX_REPO_MOUNT_MAP` (a first-class mechanism in
  `docker_sandbox.py`) — the agent's commits land directly in the task's working copy for patch extraction.
- ClickHouse seeding writes events for the task team only; cleanup uses `cleanup_signals` + team-scoped deletes.

## Stages & scorers

### Stage R — research (signal → report)

Graded from the `SignalReport` + artefacts (findings, actionability, priority, presentation):

| Scorer                      | Type                      | What it measures                                                                                 |
| --------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------ |
| `root_cause_identified`     | LLM judge vs ground truth | Does the report name the actual defect (file/mechanism), not just the symptom?                   |
| `evidence_grounding`        | LLM judge + fact check    | Are cited queries/numbers real (verified against seeded data), no hallucinated evidence?         |
| `distractor_avoidance`      | LLM judge                 | Does the report avoid blaming planted red herrings?                                              |
| `actionability_calibration` | exact                     | `immediately_actionable` matches ground truth label                                              |
| `priority_calibration`      | distance                  | Priority within ±1 grade of ground truth                                                         |
| `pipeline_progression`      | binary                    | Did the pipeline even produce a researched report (grouping, safety, repo selection all passed)? |

### Stage I — implementation (report → PR)

Graded from the extracted patch (fixture repo diff) + hidden behavioral tests, DeepSWE-style:

| Scorer                   | Type                 | What it measures                                                                                       |
| ------------------------ | -------------------- | ------------------------------------------------------------------------------------------------------ |
| `behavioral_correctness` | hidden tests         | Fraction of verify/ tests passing after the patch (0 pre-patch by construction)                        |
| `no_regressions`         | visible+hidden tests | Pre-existing behavior still passes                                                                     |
| `mergeability`           | LLM judge rubric     | Would a senior reviewer merge this as-is: scoped diff, no debug junk, style-consistent, commit quality |
| `pr_narrative`           | LLM judge            | PR title/description artefact: says what/why, links evidence                                           |
| `task_completion`        | binary               | Task run reached completed state and produced a non-empty diff                                         |

### End-to-end

`e2e_resolution` = gated score (FrontierSWE-style): behavioral_correctness gated on root_cause_identified —
a lucky patch without correct diagnosis scores ≤ 0.5; full credit needs both stages sound.

## Platform

Braintrust project **`signals-self-driving`**: one experiment per run, one row per task-trial;
stage scores as Braintrust scores, full report/patch/logs as span data. Runner is plain Python (asyncio),
driving the pipeline via management commands + Temporal REST, following `ee/hogai/eval` conventions
(`Eval()` from the `braintrust` SDK, `autoevals`-style scorers).

## Difficulty tiers

- **T1 — direct**: signal names the failing surface; single-file fix; evidence confirms.
- **T2 — indirect**: symptom ≠ cause (wrong layer blamed by the customer); data disambiguates; small multi-file fix.
- **T3 — adversarial**: misleading signal + distractor in data or code (recent innocent commit, red-herring error);
  correct fix requires the data, not just the ticket.

Task families: checkout/billing logic, API contract regressions, frontend state bugs, perf (N+1 / hot loop),
data-integrity (timezone/rounding), config/flag mishandling.
