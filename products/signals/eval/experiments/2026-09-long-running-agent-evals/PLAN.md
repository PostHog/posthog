# Long-running agent evals: framework plan, instance one (the API-quality scout)

This document records the round-1 design and the [proposed lightweight live comparison workflow](#proposed-lightweight-live-comparisons).
For reusable environments and their implementation history, see [Reusable scout environments](https://github.com/PostHog/posthog/blob/signals/agentic-evals/products/signals/eval/experiments/2026-09-long-running-agent-evals/REUSABLE_ENVIRONMENTS.md) on the offline branch.
The implemented offline path restores a saved case into an isolated project for each trial.
The live path below would use current project data with private trial state.

## Question

For one agent task, which model and prompt version does the job best per dollar, and can a prompt change be shown to fix one weakness without breaking the rest?
The framework must work for any long-running agent (scouts first, then report research and ReviewHog).
The first instance is the API-quality scout, a code-reading scout that sweeps backend API files for contract gaps.

## Decisions fixed before running

- **Variants run in production on the internal dogfood project.** Each variant is a duplicate of the scout under an experiment name, with `emit=false` (nothing reaches the inbox) and `enabled=false` (never scheduled), triggered by hand. Data, inbox and memory reads stay live.
- **The task is frozen, the agent is not.** Every variant gets the same pinned commit and the same file list. The scout's judgment inside that task is what we measure.
- **A variant is one model plus one prompt version.** Any combination is allowed. The current canonical skill is always one variant, so a prompt change is scored as the difference from it in the same batch.
- **N runs per variant** (default 2) **on two task sets.** A gap between variants counts only if it beats the gap between a variant's own runs.
- **The judge is a different model family from the variants**, works from a checklist, and every "real" verdict gets a skeptic pass.
- **No code in the product.** Everything here is configuration on the project plus scripts and documents in this folder.

## The framework (agent-agnostic)

1. **Freeze the task.** Pin whatever the agent would pick at run time. Per agent type: a code scout gets a commit and a file list; a data scout gets a closed time window; ReviewHog gets a PR head; report research gets a report's signals and a repo commit.
2. **Build the variants.** One skill copy per variant: the frozen task written into the body, memory writes under an experiment prefix, no writes to shared keys, `emit=false`, `enabled=false`, model pinned on the config. N copies per variant so runs can start together.
3. **Run the batch.** All variants at the same time, so they read the same live state.
4. **Deterministic layer.** Hard checks that need no judgment: finished within budget, produced an output or a clean close-out, wrote memory only under its prefix, left shared keys untouched, cost, duration. Optional: a candidate script that lists mechanical findings for the judge to check against.
5. **Judge.** One judge per output with the agent's rubric file, the pinned inputs, and the transcript. Rubric items are yes / no / unsure, non-overlapping, split into process (did it do the work), outcome (is the result right) and hygiene. Every "real: yes" gets a skeptic that tries to refute it. A pooling step merges verified findings across variants; recall per variant is its share of that pool.
6. **Score.** One row per run, one row per judged finding. Per variant: rates per rubric item, recall, cost per verified finding, duration, and the spread between its own runs.
7. **Edit loop.** Change one thing in the skill. Run it against the current skill with the same N on the same files. Keep it only if the target item improves and nothing else drops. Confirm on the second task set, which was not used to design the change.
8. **Record.** `fixtures/` (pinned inputs, rubric version, skill diffs), `results/` (runs and findings), `FINAL_REPORT.md`.

## Instance one: the API-quality scout

- **Freeze recipe.** `fixtures/commit.txt` holds the commit. `fixtures/page-1.txt` and `page-2.txt` hold two sets of 100 backend API file paths, taken from the scout's own file list and hash order at that commit.
- **Skill copy.** Same body as the canonical scout except: the "choose the files" section is replaced by the fixed list and commit; memory keys use the `exp-apiq:` prefix; the shared sweep cursor is never written. The diff is stored in `fixtures/`.
- **Variants for batch 1.** Three models the fleet already runs (luna, terra, sol) on the current skill, N = 2, two pages: 12 runs. The model pin carries the model only; reasoning effort and queue tier follow the fleet defaults and are recorded, not varied.
- **Hard checks.** Run status, report emitted or clean close-out, memory prefix respected, cursor untouched, duration under 15 minutes, cost.
- **Candidate script.** Over the pinned files: offset pagination without ordering, a list endpoint using a heavy detail serializer, a tenant model read without a team filter. A cheat sheet for the judge, not a verdict.
- **Rubric v0.** Per report: real defect; in scope per the skill's own discriminator; endpoint, file, symbol and fix direction named and right; severity P2 vs P3 per the skill's definitions; not a duplicate of an inbox report or memory entry. Per run: recall against the pooled findings; hygiene from the hard checks. Rates, not scores.
- **Judge.** Claude-family judge (the variants are GPT), run as a workflow from a devbox with the repo at the pinned commit and read access to the project for inbox and memory.

## Metrics

- Per rubric item: share of reports that pass, per variant.
- Recall: share of the pooled verified findings each variant found.
- Cost per verified finding and duration, per variant.
- Noise: the spread between a variant's own runs, reported next to every gap.
- Refusals, timeouts and infra failures counted separately, excluded from rates.

## Cleanup

Experiment skill copies and their configs are deleted after the batch. Memory entries under the experiment prefix are deleted by their creating run. Nothing else on the project is touched.

## Not in this version

Judge calibration against hand-labelled reports. Rubric versions with a human-labelled set. Automated judging in the product UI. A memory-driven skill loop. Report research and ReviewHog instances.

## Proposed lightweight live comparisons

Proposal checkpoint: September 23, 2026.
Implementation is in progress on this branch; deployment remains disabled until its private capture paths are verified.
The reviewed v0 reuses existing scout runs and storage, with a script coordinating the comparison.
Live work continues on `signals/scout-live-experiments`; offline implementation remains on `signals/agentic-evals`.

### Intended operator flow

Select an existing scout and run its current configuration alongside one or more changes to its prompt body, model, or reasoning effort.
Keep the existing production scout running normally.
Use its real project data, repositories, and supported read tools without preparing a dataset or changing its saved configuration.
Every trial gets private writable memory and captured outputs, including outputs it can read again during its investigation.

The same idea as round 1 remains: run several versions of one scout together, then compare their findings and costs.
Apply the changes to individual runs, preserving the source scout's identity and permissions.
No persistent skill or config copies are needed.
A small operator script reads a variants file, launches repetitions with bounded concurrency, polls existing runs, and downloads results.
One variant with one repeat supports a manual smoke check through the same path.

The practical sequence is:

1. Pick the source scout, optional common investigation note, variants, repeat count, and maximum concurrency.
2. Resolve the current skill, runtime defaults, and initial scout context once for the comparison.
3. Launch each trial with its selected overrides and its own execution identity.
4. Let it investigate live data through the normal harness and supported tools.
5. Review complete captured outputs, memory changes, logs, effective settings, duration, and attributed cost together.
6. Retain the script's manifest and results; clean up private state by its recorded run IDs when it is no longer needed.

Include the current configuration as a baseline when making a quality comparison.
A single repeat is a smoke check; repeated runs are needed to see whether a difference exceeds ordinary run-to-run variation.
Judging remains manual in v0, using a scout-specific checklist and evidence checks.
Without a reviewed answer set, pooled verified findings measure relative coverage within the comparison, not absolute recall.

### Existing runs and storage

Use the existing `SignalScoutRun` and `TaskRun` records for each execution.
They already provide run identity, status, metadata, output, state, logs, and artifact references.
The operator's manifest groups those run IDs and records launch errors; v0 does not need a comparison table or a separate experiment-run lifecycle.
Reuse normal run polling, cancellation, and log retrieval with the access rules below.

| Data                                                                                | Proposed storage                                     |
| ----------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Source settings, requested and effective overrides, snapshot reference, group label | Existing server-written run metadata.                |
| Immutable starting memory and scout context                                         | Existing object storage, referenced by the run.      |
| Private memory changes, deleted keys, new report drafts, proposed edits             | A protected namespace in existing `TaskRun.state`.   |
| Complete finished outputs and memory changes                                        | Existing object storage and run artifact references. |
| Repetitions, run IDs, launch failures, downloaded comparison                        | Operator script manifest.                            |

This provides a bounded v0 without a new table.
Private working state must have an explicit aggregate size limit; exceeding it invalidates the trial instead of silently dropping content.
Use the existing atomic state mutation helper so concurrent tool calls cannot overwrite one another's changes.
Protect the namespace from generic run PATCH requests and exclude its bodies from Temporal processing-context payloads.
Keep object-storage I/O outside database row locks.
The authenticated task and server-written run mode determine access; an editable state key must not enable experiment privileges.
Output and artifact fields are not private by naming convention: detail responses and downloads need explicit access checks.

A separate private-state table is a later option if measured state sizes or update patterns require it.
Do not add one solely because a run is an experiment.

### Launch changes

Expose experiment mode and per-run settings through the scout API and MCP.
Prefer extending existing launch machinery; whether the public action extends `run` or sits beside it depends on the permission checks required.
The exact route is not a settled design requirement.

Launch inputs cover the source config, optional prompt body, model, reasoning effort, common investigation note, saved-context reference, and retry identity.
Variant labels and grouping belong in operator metadata, outside the scout's prompt and discovery tools.
Resolve and save the source configuration, skill version, and initial context before applying any candidate overrides.
Every repeat reuses that saved context; a candidate launched first must not redefine baseline defaults.
Changing the model retains the resolved baseline effort unless overridden; reject incompatible settings before starting a paid run.
Record requested and effective settings, and treat an observed mismatch as an invalid comparison.

Retrying a launch must find the same execution rather than create another paid run.
Reuse existing task identity and dispatch support for this.
Keep setup failures in the script manifest even if they happen before a scout run exists.
Creating a new execution table just to record these failures is unnecessary.

Reuse project permissions and skill-authoring checks for prompt or note overrides.
Recheck current access to source skills, repositories, and connections at launch; saved selections must not preserve revoked permissions.
Reject or explicitly record capability changes instead of silently changing the toolset.
Sandbox tokens cannot launch or manage the operator's comparison.

### Required product changes

| Change                                        | Why round 1 or the current code requires it                                                                                                                                             | Smallest useful behavior                                                                                                                                                                                                                                                                                                 |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| One-off runtime selection                     | Config pins carry a model, while the manual trigger accepts only a note. Different model defaults changed effort in round 1.                                                            | Thread validated model/runtime/effort through REST and Temporal into the runner's existing runtime override. Resolve baseline defaults once and reject unsupported combinations before dispatch. Record requested and effective values; mark observed mismatches invalid for comparison.                                 |
| Private prompt selection                      | Permanent skill copies change skill origin and harness instructions. The scout fetches its body through `skill-get`, so replacing an in-memory body alone does not apply the candidate. | Preserve the source name, origin, owners, and tool permissions. Bind `skill-get`, including pagination, to the trial's saved body. Freeze supporting files from the source version; file/tool-grant edits are outside v0.                                                                                                |
| Independent execution                         | The endpoint, Temporal workflow ID, and runner all enforce one active run per skill. Changing only one check leaves the others in place.                                                | Give each trial a unique workflow identity and keep trial rows out of the production concurrency guard, stale-run recovery, history, and health updates. Retain idempotency, authorization, concurrency limits, and normal spend enforcement.                                                                            |
| Private memory                                | Shared-key writes and substring searches allowed copies to influence one another and the production scout. Original-author metadata does not identify the last writer.                  | Snapshot initial scratchpad and recent scout context once per comparison. Each trial searches that starting state plus its own changes. Remember, forget, and exact-key reads operate only on that trial's state, preserving normal keys.                                                                                |
| Report capture                                | Dry-run can tell the scout not to file and does not provide a normal readable output. The normal harness also asks scouts to edit existing reports.                                     | Validate and capture report creation, edits, notes, and evidence privately. Preserve normal safety checks and stable IDs. Subsequent reads see the trial's own new or edited reports. Keep them out of inbox delivery, notifications, implementation, and production event destinations.                                 |
| Consistent visibility                         | Fleet profiles, run searches, task listings, and logs can reveal sibling activity. The profile currently exposes dry-run eligibility.                                                   | Derive the trial from its authenticated sandbox task, then apply that context consistently to list, search, detail, log, and mutation paths. Trials see normal production context and their own private changes; ordinary scouts see no trial state. Profile eligibility reflects acceptance by the private output path. |
| Restrict other mutations                      | Disabling optional write grants still leaves default notebook and task writes; external MCP servers have separate credentials.                                                          | Use a restricted trial token posture. Permit supported reads, private scout writes, and necessary own-task bookkeeping. Deny unrelated production mutations and reject scouts or connections whose required effects have no private implementation.                                                                      |
| Keep trial telemetry out of investigated data | Lifecycle events, MCP tool traces, feedback submissions, and model generations can themselves become data another scout queries.                                                        | Carry a trusted trial capture policy through backend, MCP, and the active model gateway. Keep these records outside the queried project while preserving billing and private per-run usage. Tags or hidden UI rows alone do not establish isolation.                                                                     |

The sandbox's bound task identity must select its private state; a caller-supplied run ID, namespace, header, or skill name must not let it select a sibling's state.
Keep source skill/config rows unchanged, including schedules, cursors, failure counts, and pause state.
Trial traffic still consumes real model spend and must remain visible to authorized operators and existing spend controls.
Do not grant experiments an unbounded bypass of the production budget.

Keep private output storage separate from ordinary production reports and signal records.
An ordinary report marked suppressed can still appear in searches, trigger hooks, or be used by another scout.
Use shared validation and output schemas so capture behavior stays close to the normal path, with a trial-aware read path for new reports and proposed edits.
Production report reads may remain live in this first version; only a trial's edits are private.

### What stays live and what is saved

Save the small agent context needed to compare variants: source skill/configuration, initial scratchpad, relevant notes and recent run summaries, and effective model settings.
A creation-time cutoff is not a memory snapshot because existing rows can be edited in place.
Analytics, product state, production inbox contents, and external read-only evidence remain live.
An optional shared note can narrow the task, but the first version does not claim to freeze every query or external dependency.
Record start/end times and repository revisions actually used, and run variants close together.
These comparisons assess current behavior; use the offline cases when exact input repeatability matters.

For v0, support investigation/reporting scouts using supported PostHog and repository reads, private memory, and captured report creation and edits.
Weak-signal and structured-output scouts are outside this first scope; reject unsupported output modes rather than quietly dropping their output.
Scouts that need product mutations, new task launches, or writable third-party connections also need additional support.
Read-only external connections can be admitted once their credentials and tools have a verified read boundary.
Do not claim that every scout can run with unchanged behavior under a restricted token.
The internal UI described below wraps the existing trial endpoints.
Automatic judging, a prompt optimizer, a general retention service, and a new execution platform remain outside v0.

Telemetry isolation is a required part of the feedback use case.
The source review found independent capture paths in the backend, MCP server, and Python model gateway; it did not establish the active production gateway route or every warehouse replica exposing task data.
Verify those destinations before implementing or promising that sibling activity cannot be discovered.
The offline harness's private reporting flag is not a production-wide telemetry switch.
Any gateway work must follow the existing [gateway migration policy](../../../../../services/llm-gateway/PARITY.md), rather than adding a new Python gateway feature by default.

### Reuse and implementation order

Reuse the [scout runner](../../../backend/scout_harness/runner.py), [Temporal dispatch](../../../backend/temporal/agentic/scout_scheduler.py), [run views](../../../backend/scout_harness/views.py), and existing sandbox provisioning and logs.
The runner on this branch accepts an explicit runtime and records model settings.
That override is part of the branch's eval work, so an independent live branch must carry the small shared runner change or wait for it to land.
The existing [cost reader](../../../backend/scout_harness/run_costs.py) can supply ordinary run costs, but its shared generation-event source must be reconciled with private capture before it is used for isolated trials.
Keep unknown or still-arriving cost distinct from zero.

1. Confirm deployed telemetry and billing routes, and verify the bounded private-state approach against resume and access paths.
2. Add experiment mode to existing runs, private memory and report capture, visibility rules, restricted writes, and private telemetry routing.
3. Thread per-run prompt/model/effort through dispatch and allow independent experiment executions without changing production scheduling.
4. Expose launch through API/MCP and add the thin launch/poll/download script.
5. Prove isolation with two simultaneous trials, including retries and failures, before the first live comparison.

The acceptance check must show that the same memory key can hold different values in two trials while the production value stays unchanged; guessed sibling IDs cannot be read or mutated; own outputs remain readable; private report edits leave originals unchanged; scheduled scout state stays unchanged; no downstream delivery or sibling-visible telemetry occurs; and the effective prompt/model/effort match the requested variant.
These are requirements for the implementation, not results already established by the offline checks.

### Branch split

`signals/agentic-evals` and its existing PR contain offline evals: saved cases, restoration, harness integration, validation, and their operating history.
`signals/scout-live-experiments` contains the original live experiment's report, results, scripts, and this proposal, followed by the production changes described here.
The live branch starts from master with the selected live material, so its PR does not inherit the offline implementation.
The original experiment is contained in `00f68612016` and `ba2de6b231b`; the offline-v0 checkpoint is `147adbcc3bd`.
Preserve those checkpoints and split the current file changes with ordinary commits, without rewriting shared history.

The offline code case reuses the pinned commit, file pages, and canonical skill from the original experiment.
Retain those inputs where needed and update document links during the split.
Port the small shared runtime override explicitly; do not pull in the whole offline harness to obtain it.
Check each branch's diff against master and verify its required fixtures and runner interfaces before continuing.
Private snapshots and transcripts stay outside both branches.

### Live trial operator script

The implementation adds `POST /signals/scout/configs/{id}/trial/` and `GET /signals/scout/configs/{id}/trial_result/?launch_id=...` under the normal project API prefix.
The matching MCP tools are `scout-trial-create` and `scout-trial-get`.
Only operators with scout write and skill editor access can use them; sandbox tokens cannot manage comparisons.
No skill/config copies or new tables are created.

Deploy the experiment capture policy to the existing Python gateway, then set `SCOUT_LIVE_TRIALS_ENABLED=true` and `SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=true` on the backend and workers.
Use the normal backend and sandbox gateway settings; no separate gateway URL or service is needed.
The private-capture setting is an explicit deployment check: verify the gateway version, task/query telemetry, and warehouse replicas before enabling it.
It does not automatically detect whether the gateway supports experiment capture suppression.
Trials retain ordinary spend/rate gates; cost is null when private accounting is unavailable, while runtime token counts are retained when reported before completion.
Do not infer zero cost from absent generation events.

Write a private variants JSON file, for example:

```json
[{ "label": "baseline" }, { "label": "trace-dependencies", "skill_file": "candidate.md" }]
```

`model` and `reasoning_effort` are optional per-variant fields.
`skill_file` is relative to that JSON file; `skill_body` can be supplied instead.
The source settings are saved before any override, so the first variant does not redefine the baseline.
If the source has no explicit effort pin, supply a common `--effort` supported by the selected models.

```sh
export POSTHOG_API_KEY=... # Set privately; never save it in the manifest.
.codex/with-flox python products/signals/eval/experiments/2026-09-long-running-agent-evals/scripts/run_live_trials.py \
  --host http://localhost:8000 --project-id 1 --config-id '<source-config-uuid>' \
  --variants playground/scout-evals/variants.json --effort medium \
  --repeats 3 --concurrency 2 --output playground/scout-evals/live-comparison
```

Resume with the same `--host` and `--output`, adding `--resume`.
The manifest saves each launch UUID and its exact request before sending it, and polling reuses those identities.
It downloads reports, proposed edits, memory changes, and session logs into the private output directory.
Existing task/run IDs support normal log and cancellation tools.
A polling timeout leaves executions available for later polling; it does not cancel them.

V0 accepts report-channel scouts without extra product write scopes, external MCP connections, or structured output.
Automatic downstream implementation and repository-selection agents do not run; authored report payloads are retained, with skipped enrichment recorded for the operator.
Unsupported write actions and unsupported specialized inbox filters invalidate the comparison explicitly.
Normal inbox deduplication reads, report details, evidence, and artefacts remain available.
Runtime settings are checked against the saved variant at completion.
That API check compares protected task state; inspect transcript configuration events and gateway model counters when verifying execution.
The MCP `llm_model` label is supplied by the model and is not authoritative runtime evidence.
MCP trial launch/result tools omit analytics, including nested `exec` calls.
Task content reads retain call metrics but omit payload spans and free-text intent for every caller, including operators retrieving private transcripts.

### Implementation history

- September 23: split the branches and pushed the reviewed experiment records.
- September 23: added retry-stable dispatch, private memory/report storage, source skill overlays, restricted credentials, and task/report visibility rules.
- September 23: focused private-state/report/inbox tests and task/gateway isolation tests passed; generated the new API/MCP types.
- September 23: checked ordinary scout behavior alongside private launch/config/history paths, and passed the repository-wide Python type check.
- September 23: exercised CLI connection retries, saved launch/context reuse, log pagination, unavailable startup logs, and private file permissions with synthetic responses.
- The local CodeRabbit review was skipped because the CLI was signed out during unattended work.
- September 23: real sandbox validation exposed missing private-gateway network rules and missing permissions for a scout to upload logs, update its summary, and record status/usage. Fixed those paths with exact run binding; general task writes remain blocked.
- September 23: completed two concurrent Docker scout runs through the normal Temporal harness against an invented invoice-export case. Luna and Terra both queried the data, read and wrote private memory, saved summaries, and authored captured reports at medium effort. Their transcript configuration matched the requested models and effort throughout.
- September 23: checked each sandbox's actual OAuth credentials against its own and its sibling's memory, reports, tasks, runs, and logs. Private results remained separate, the normal inbox could not retrieve them, and the source skill, config, and shared memory stayed unchanged.
- September 23: routing checks, private log/summary/lifecycle authorization tests, repository-wide Python type checks, API generation, and product dependency checks passed. Security scanning found no findings on the changed lines.
- September 23: merged current master, regenerated API types, and passed the trial API suite and repository-wide type checks again. Revoked the local verification credential, removed temporary services and scout containers, and restored the original backend and worker with a passing app health check. Trial opt-ins are disabled on the restored stack.
- The successful smoke checks execution and isolation. Model quality comparisons still need repeated runs and judging. An earlier local attempt was canceled for routing failures; another exposed an incomplete synthetic schema registry, which was corrected before the successful pair. Private transcripts and attempt history remain outside Git.
- No new production comparison has been launched during implementation. Deployment requires the gateway and capture checks described above.

### Gateway follow-up, September 23

The initial investigation recommended replacing the dedicated gateway with a capture policy for authenticated experiment requests on the existing Python gateway.
Implementation follows that recommendation; the points below record its scope and verification requirements.

- The gateway already reads OAuth scopes and the sandbox task identity in `auth/authenticators.py`.
  Use the experiment credential minted by the backend to select the capture policy.
  A caller-supplied event property is insufficient proof that a request belongs to an experiment.
- Suppress experiment generation events on both success and failure, including both configured capture destinations, exception capture, and rate-limit denial events.
  Keep the separate rate-limit and Prometheus callbacks active.
  The current `signals` product has no customer credit bucket; keep this exception limited to supported experiment traffic so other products retain their billing events.
- Apply the policy to the scout's sandbox calls and backend report-validation calls.
  Report validation uses a short-lived gateway-only experiment credential that is revoked when the operation finishes.
  Changing only the sandbox environment would leave this path uncovered.
- Use the normal gateway settings in place of the private URL override.
  Keep trial transcript/result storage and the existing backend/MCP capture controls.
  Missing generation events still mean event-based dollar totals are unavailable, not zero.

The Python gateway is under a feature freeze; any implementation must document the active caller's applicable migration blocker from `services/llm-gateway/PARITY.md` and stay limited to that caller.
That record still lists Python-only models available to scouts, so requiring all comparisons to use Go would narrow the supported model choices.
Verify normal and experiment traffic concurrently, including streaming, failures, retries, and report validation, with stubbed providers before another end-to-end scout check.
Check that spend limits remain active and experiment content reaches neither configured capture destination.
No service deployment or model call was performed for this investigation.

### Shared gateway implementation, September 23

Trials now use the existing Python gateway and its normal backend/sandbox settings.
The dedicated trial gateway URL setting is removed.
Capture suppression requires a task-bound OAuth credential from the allowlisted Signals application, with both internal-run and experiment scopes.
Caller-supplied headers cannot enable it.
Generation capture, exception capture, denial events, and content-bearing logs are suppressed; ordinary requests retain capture and both request types retain cost/rate checks.

Backend report validation mints a gateway-only credential after checking the trial identity and the original operator's current access.
The credential expires after ten minutes and is revoked when validation finishes, including failures.
It cannot upload task logs or change run state; those operations also require the sandbox's task-read scope.
Concurrent report calls keep distinct credentials, and the context is reset after each operation.

Validation used synthetic fixtures and stubbed providers, with no model calls:

- Full gateway suite: 1,718 passed; 102 provider integration cases skipped with their credentials disabled.
- Concurrent ordinary/trial HTTP requests, streaming, failure sanitization, both capture destinations, and cost counters passed.
- Backend client suite: 88 passed; trial routing: 10 passed; sandbox network policy: 22 passed.
- Selected database-backed trial state, launch, report, dispatch, and task-permission checks: 77 passed after correcting the new OAuth test fixture.
- Repository-wide Python type checks, API generation, dependency boundaries, formatting, and security checks passed; API generation produced no changes.
- The standalone gateway strict type check has the same 42 existing errors as the pre-change source; normalized diagnostics match exactly. This is separate from the passing repository-wide type check.

The running development backend still passes its health check.
No service was restarted or deployed for this change, and trial enablement remains off.
Deploy the gateway support before setting the backend/worker capture attestation and enabling trials.

### Internal comparison UI, September 23

Staff members in project 2 can open **Scouts > Compare scouts** at `/inbox/scouts/comparisons`.
Choose a supported scout, edit variant names, models, reasoning efforts, and optional replacement skill bodies, then select repeats and optional common instructions.
The UI caps a comparison at 20 runs and uses the same launch, result, and task-cancel endpoints as the script.
It adds no batch table or execution platform.

`GET /signals/scout/configs/{id}/trial_setup/` reads source readiness and available model/effort choices without creating a snapshot.
`GET /signals/scout/configs/{id}/trial_history/` lists the requesting operator's recent private runs.
Both enforce staff access in project 2 as well as existing scout permissions.

The first launch saves starting context, and all remaining submissions share that context with independent private changes.
Retries reuse each launch ID and its exact request body.
Keep the page open until submissions are confirmed; accepted runs continue on the server.
Browser storage saves only source config and launch IDs, scoped to the operator and project.
Prompt edits, reports, and memory stay out of browser storage, autocapture, and session replay.
After a reload, accepted runs can be reopened; unsubmitted prompt edits must be entered into a new comparison.

Results include captured reports, private memory changes, run settings, and available token counts, with JSON download and per-run stop controls.
Dollar costs remain unknown when private capture removes the shared cost-event source.
The page does not automatically judge results or enforce instructions as query filters.

UI validation used invented checkout fixtures and mocked run endpoints, without model calls or production experiments.
Chromium exercised four submissions with one shared starting context, a replacement prompt on two runs, result inspection, JSON download, reload recovery, and cancellation.
The page was inspected at 1,100px and 520px with no browser errors.
Focused API and frontend tests cover access restrictions, private history, retry identity, double submission, persistence, and polling recovery.
Repository-wide Python and frontend TypeScript checks passed before the master refresh.

After updating from master, the trial API/state suite passed 42 tests, focused task/sandbox suites passed 259, and UI/Inbox routing suites passed 66.
Repository-wide Python typing passed on 21,449 files; frontend TypeScript and regenerated API/product contracts passed.
The security scan found no issues in the four changed backend inspection/launch files.
Local migrations were applied and the existing app returned a healthy response.
Production enablement remains off.
