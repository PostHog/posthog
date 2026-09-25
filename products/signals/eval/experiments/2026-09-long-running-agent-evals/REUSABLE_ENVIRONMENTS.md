# Reusable scout environments

Historical execution checkpoint: September 23, 2026.
The initial harness review used `ba2de6b231b`, with additional dependency checks after merging `e7e0c103433` from master.
The parameterized command now runs saved code and data cases through the production scout harness.
Historical data restoration is verified in fresh projects, two identical data trials completed, and the code case completed on the updated runtime.
The data trials start from equal normalized history and event checks with separate mutable identities.
Both environments retain full results and clean up their agent sandboxes and dedicated services.
The implementation history below records completed checks and failed attempts.
Those runs used the earlier JSON-based snapshot format.
The current snapshot contract uses schema v2 and Parquet tables; the historical runs do not establish conversion parity for that format.

## Purpose and agreed constraints

Keep a small set of scout cases usable for one to two months so that a new model, reasoning effort, or prompt can be compared with the current production configuration.
One trial runs one scout once, from reset initial state.
Every configuration uses the same execution path.
Fine-tuning, a new UI, an always-running environment, and a general snapshot service are outside the first version.

The saved case contains the world being investigated: repository state, project data, relevant history, and task scope.
The selected scout, prompt, model, and effort can change independently of those inputs.
Use the same harness and tool versions throughout a comparison and retain their versions with the outputs.
Rerun the current production configuration alongside candidates; an old score alone cannot distinguish an agent improvement from a change in the tools, harness, or rubric.

The first version is agreed: API quality for code and Agent feedback for data.
Reuse the API-quality file sets from round 1 and add a bounded historical dataset for Agent feedback.
Restore saved memory and prior reports with the feedback data on every trial, so the case includes normal duplicate handling and baseline comparisons.
Choose a natural window with several independently verified findings of varied difficulty, aiming for three to five, alongside ordinary activity, duplicates, and plausible false leads.
Keep the complete relevant activity in that window; selecting only rows that demonstrate known findings would change the investigation.
Restore memory and prior reports from the case's starting checkpoint, before its target findings were filed.
The reviewed answer belongs in the grader's reference, outside the scout's accessible inputs.
If the window spans several original runs, define it as one catch-up investigation from that checkpoint, rather than claiming to reproduce one original run.
Historical contents must be recoverable: current rows filtered by creation date can contain later edits, and the scratchpad does not retain earlier versions.
An existing report is a candidate answer until its evidence has been independently checked.
Historical data and resulting traces must stay in private storage; public files contain the case structure and implementation only.
Synthetic cases remain useful and are already supported by the existing harness.

### Saved cases and parallel live runs

Use two complementary ways to compare scout configurations:

- Saved cases reset the same repository, data, and initial history for repeated prompt, model, and effort comparisons.
- Parallel live copies investigate current project data to check whether promising changes also work beyond the saved cases.
  Live data can change during the comparison, so these runs have weaker repeatability.

Iterate on saved cases, validate promising changes with parallel live runs, then decide whether to deploy.
Live copies need the same starting history, private subsequent memory, and complete report capture without downstream delivery.
Enforce memory isolation on both reads and writes so copies cannot influence one another or the production scout.
The production safeguards identified in the [round-1 report](https://github.com/PostHog/posthog/blob/0dd2387f046/products/signals/eval/experiments/2026-09-long-running-agent-evals/FINAL_REPORT.md) remain prerequisites for another live comparison; the isolated runner does not implement those safeguards for production copies.
The [lightweight live comparison proposal](https://github.com/PostHog/posthog/blob/0dd2387f046/products/signals/eval/experiments/2026-09-long-running-agent-evals/PLAN.md#proposed-lightweight-live-comparisons) reuses existing run records and storage, with per-run overrides and a coordinating script.
Live experiments and their production changes continue on `signals/scout-live-experiments`.
This branch keeps the offline implementation and the pinned fixtures reused by its code case.

For bounded code and feedback investigations, retained inputs and the normal tools appear sufficient for useful comparisons without copying an entire production project.
Treat that as a working assumption supported by the completed investigations, not a demonstrated guarantee of production performance.
Broader coverage requires representative cases with clear issues, subtle recurring issues, existing duplicates, and valid no-report outcomes.
The current environments establish reusable execution; they do not yet establish that coverage or a superior configuration.

## Recommended implementation

Extend the existing [Signals agentic evals](../../../evals/agentic/) and [shared harness](../../../../posthog_ai/eval_harness/README.md).
The [scout adapter](../../../evals/agentic/runners.py) already calls the production `arun_signals_scout` entrypoint.
The [workflow runner](../../../../posthog_ai/eval_harness/workflow.py) prepares each trial, runs it with a timeout, and retains logs and usage.
The [team factory](../../../../posthog_ai/eval_harness/harness/demo_data.py) creates a separate project per trial, while the [service setup](../../../../posthog_ai/eval_harness/harness/services.py) runs real MCP tools against the eval backend.
Model, effort, repeat count, and concurrency controls already exist.

The lifecycle is:

1. Load a versioned case and verify its saved inputs.
2. Restore its data, memory, reports, and repository into isolated trial state.
3. Run the selected scout through the existing production entrypoint.
4. Save full report payloads, memory changes, transcript, effective settings, duration, and cost.
5. Grade the result and remove the agent sandbox. The next trial gets a fresh project.

A disposable agent sandbox is only part of the isolation.
Its MCP credentials must point to the restored project, and external reads must also use retained inputs where they affect the case.
No trial may silently fetch missing evidence from a changing production project.
Report creation should behave normally inside the eval project while downstream delivery and implementation remain disabled.

The existing [case seeders](../../../evals/agentic/seeders.py) and [scout cases](../../../evals/agentic/cases/scout.py) provide examples of real product data with report and no-report outcomes.
The implementation adds these capabilities to the original runner:

- Verify a retained repository commit before the first agent turn and serve subsequent Git fetches from a frozen local origin.
- Restore a case-specific snapshot into a fresh project, with schema, relationship, event-count, and timestamp checks.
- Load the selected skill version and restore initial memory and report history.
- Shift inventoried timestamps together using one explicit target cutoff, subject to the time-policy limits below.
- Capture complete persisted reports, memory changes, task status, and transcripts.
- Give every repeated trial a unique artifact path so local results cannot overwrite each other.

Implement v0 as a parameterized script on the devbox, using one case-specific loader and the existing Docker provider.
Its empty project option prevents unrelated demo evidence from entering a historical case.
Restore event files into ClickHouse and the small related state into the normal product models, preserving relationships when IDs change.
The scout adapter must forward the selected skill version, repository, and explicit investigation bounds through the production runner's existing inputs.
Do not build a general export service, another query engine, or a separate runner for prompt changes.

The [suite instructions](../../../evals/agentic/AGENTS.md) cover public synthetic cases and explicitly supplied private cases.
A historical snapshot requires a private fixture path and a review of every log and artifact destination.
`WorkflowPrivateEval` is an existing starting point; its flags alone do not establish privacy for every downstream service.

### Where restoration and execution happen

The v0 deliverable is a script that a developer runs on a started devbox.
Its parameters select the case, snapshot location, model, effort, skill or prompt version, repeat count, and result directory.
The PostHog backend, MCP server, Postgres, ClickHouse, and snapshot restoration run on that devbox; the existing Docker provider creates the scout containers there.
Restoration belongs in the runner's per-trial setup, after its test databases and fresh project exist.
Each trial gets fresh writable state, and the script retains complete results before cleanup.
The shared harness keeps its test databases by default, so completed projects remain local until normal test-database recreation.
They are never selected as the starting project for another trial.
Develop and verify this flow end to end on the devbox.

Keep case files separate from machine setup, and configure paths and service endpoints rather than tying them to one devbox.
Use the same restore/run/capture flow for every configuration.
These boundaries preserve a later move to programmatic Modal execution without adding a scheduler, deployment system, or new image build to v0.

For that later move, the existing [VM sandbox template](../../../../tasks/backend/sandbox/images/Dockerfile.sandbox-vm) and [dev-stack image preparation](../../../../tasks/backend/logic/services/dev_stack_image.py) are starting points for hosting the complete runner and databases inside a Modal VM.
Their compatibility and the job's launch, result-retention, and teardown steps remain future work.
The existing [harness Modal provider](../../../../posthog_ai/eval_harness/harness/providers.py) moves only the agent sandbox remotely and tunnels to the launching host's services; that option alone does not move the databases.

## Environment options

| Option                                       | What is retained                                           | Fit for the first version                                                          |
| -------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Pinned code and small project state          | Git commit, task scope, memory, report history             | Use for API quality; the repository alone does not preserve deduplication state    |
| Synthetic data in real PostHog               | Deterministic scenario setup and expected outcomes         | Existing support; useful controls, with realism limited by scenario design         |
| Bounded historical data in real PostHog      | Selected rows, metadata, related state, and time reference | Preferred direction for the first data scout                                       |
| Parquet queried through a custom MCP backend | Saved tables plus an implementation of the selected tools  | Consider only for a narrow interface; reproducing HogQL and product APIs adds work |
| Full service and project snapshot            | Broad application and database state                       | More storage and maintenance than the initial cases justify                        |

Parquet stores the bounded historical dataset while the restored case still uses real PostHog queries.
It does not require replacing MCP or ClickHouse.
ClickHouse supports [Parquet input and output](https://clickhouse.com/docs/reference/formats/Parquet/Parquet); schemas and product metadata still need explicit restoration.
[DuckDB can query Parquet directly](https://duckdb.org/docs/current/data/parquet/overview), but that does not supply PostHog's other tool behavior.

### Snapshot format

The saved-case runtime requires one JSON manifest with `schema_version: 2` and Parquet tables for events and history.
The manifest keeps the checkpoint, completeness, gaps, and timezone inline under `state`.
Its `events` list contains hashed Parquet file references, and `state.tables` maps history table names to hashed Parquet file references.
Each reference supplies a relative `path` and `sha256`.
Skill files retain their declared content types, and repository contents remain in a Git bundle.

History tables cover `scratchpad`, `reports`, `report_artefacts`, `scout_notes`, `tasks`, `task_runs`, `scout_runs`, `metrics`, and `project_profile`.
Omit empty history tables; `project_profile` must contain exactly one row when supplied.
Event files may contain zero rows if they retain the full declared schema.
The tables use explicit columns, UTC timestamps with microsecond precision, UUID strings, and JSON text for flexible nested fields.
One reader validates both event and history tables before the existing database restoration step.
The [saved-case command guide](../../../../../docs/internal/ai-offline-evaluation-reporting.md#private-saved-scout-cases) describes the contract and validation commands.

The runtime rejects schema v1 manifests, JSON Lines event files, and separate `state.json` payloads.
Convert older inputs once with a local script into a separate private directory and preserve the originals.
The runtime has no conversion mode or legacy reader.
Verify every decoded event and history record against the original, then verify restoration through real PostHog queries in a fresh project.
Conversion parity checks need no model calls; completed agent runs remain evidence for the format they used.
Record parity does not establish an advantage in storage size or execution speed.

Recorded tool responses cannot serve as the main environment for exploratory comparisons.
A different model may issue a new query or inspect another filter, for which a recording has no answer.
The retained state must support those valid alternative investigations within the case's declared scope.

## Data boundaries

The selected first data case is Agent feedback.
Three additional candidates test different dependency shapes: feature flag cleanup, flaky test investigation, and skill validation.
The descriptions below are proposed fixture requirements, without production data, private skill text, or operational measurements.

| Candidate                | Core evidence                                                                                         | Related state to preserve                                                                                                                              | Main difficulty                                                                          |
| ------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| Feedback analysis        | Feedback submissions and corresponding tool-call events, including successful and uneventful activity | Schema discovery, stable caller relationships, comparison windows, memory baselines/cursor, prior runs and reports, project profile, reviewer metadata | Reducing telemetry without changing denominators or removing corroborating evidence      |
| Feature flag cleanup     | Flag definitions, rollout conditions, lifecycle and usage evidence, matching source references        | Repository state, initial review cursor, known exceptions, prior reports, ownership                                                                    | A flag's apparent lack of use can depend on incomplete history or a moving time boundary |
| Flaky test investigation | Test-status transitions and source at the relevant revision                                           | CI configuration, referenced failure logs and run metadata, related transitions, prior findings, ownership                                             | Git does not retain CI logs or the external status history                               |
| Skill validation         | Skill corpus, references, tool catalog, and data exercised by selected skills                         | Repository history, coverage cursor, project capabilities, prior findings                                                                              | Selecting another skill can introduce a different product's data requirements            |

### Feedback analysis

Retain complete submissions for the chosen window, including positive and uneventful feedback.
Keep the tool-call properties needed for filtering, grouping, error analysis, and matching distinct callers.
Preserve the current investigation window and the comparison history the scout actually uses.
Successful calls belong in the snapshot whenever the scout compares rates; preserving only failures changes the answer.

Reduce unnecessary columns before reducing the time range.
A smaller declared investigation scope is reasonable, but missing history must not silently become zero activity.
Preserve event names and property types faithfully, including legacy forms where they are part of the case.
Restore the supporting discovery metadata so a model can find the data through the normal tools.

Select prior reports from the scout's saved memory references as well as recent runs.
A recent-run limit can omit an older report that still controls duplicate handling.
Current report rows and dated artifacts do not always establish the report's status at the starting checkpoint.
Record unresolved history as a case limitation; do not infer historical status from today's row or score duplicate handling as verified when the relevant report is absent.

### Feature flag cleanup

Retain flag keys and IDs, full definitions and targeting conditions, active/archived/deleted state, creation and modification times, recorded usage times, and relevant audit history.
Restore referenced records, incoming active dependent flags, and experiment associations; dependencies can live in another flag's definition.
Preserve complex targeting conditions rather than replacing them with a boolean.
Pin the repositories containing its production call sites and preserve source history needed to explain an intentional exception.
Start each trial with the same review cursor, known exceptions, prior reports, and reviewer lookup data.

The [flag model](../../../../feature_flags/backend/models/feature_flag.py) and [API](../../../../feature_flags/backend/api/feature_flag.py) expose stored state that can support a bounded case without exporting the entire flag-evaluation event stream.
The existing [flag eval seeders](../../../../feature_flags/evals/seeders.py) already create a stale flag and an active dependent using those records.
However, `last_called_at` reflects received telemetry: silence does not establish that the enabled branch never executes.
An old flag is also not proof of a long-standing full rollout; that claim needs change history.
These evidence limits are documented in the [stale-flag detector](../../../../feature_flags/backend/temporal/health_checks/stale_flags.py).
Keep the real list, definition, and status tools, including their different response shapes.

A useful initial fixture contains a reviewed cleanup opportunity, a flag that must remain, and a flag whose status is ambiguous without further evidence.
Keep the complete bounded candidate list and its initial selection state so every model faces the same investigation.
This appears to be the smallest additional data case of the three reviewed, subject to verifying metadata restoration and time behavior.

Project orientation is also part of the input.
The [profile builder](../../../backend/scout_harness/profile/builders.py) can query analytics when refreshing the profile, and the [profile cache](../../../backend/scout_harness/tools/profile.py) expires.
Preserve a compatible profile with timestamps covered by the case's time policy, and either supply the data required for a rebuild or prevent an incidental expiry from changing the case.

### Flaky test investigation

Retain a closed window of test-status transitions, including repository, test identity, previous and current status, quarantine state, and timestamps.
Include surrounding transitions from other tests: a burst across unrelated tests can change the diagnosis from one flaky test to a broader CI problem.
Preserve the initial cursor, previously investigated tests, prior reports, and ownership context.

Pin the relevant source revision, test fixtures, dependencies, and CI configuration.
Retain any CI run metadata, failure logs, and artifacts the case needs as separate inputs.
A status transition may not identify the failing commit or CI job; resolve those relationships when preparing the case, and preserve uncertainty when they cannot be established.
Checking out the repository alone does not recreate an expired CI log.

The case must define how the scout reads retained CI evidence through its normal interface.
That access path is additional work beyond restoring PostHog event rows.
For a smaller first case, choose a diagnosis supported by source with an identifiable CI job, so extensive failure-log retention is unnecessary.
For log-dependent cases, retain every relevant run attempt: [GitHub's log documentation](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs) explains that a rerun archive can omit jobs from earlier attempts.
Include a valid reason to withhold a report when evidence is insufficient, so the fixture does not reward unsupported diagnoses.
This is a useful later hybrid case, with a larger external-data boundary than flag cleanup.

### Skill validation

Retain the skill corpus, referenced files, repository history, and the tool schemas available to the scout.
Restore coverage memory, the scan cursor, prior findings, and the project capabilities used to select which skills to exercise.
The static checks mostly depend on Git; executing a chosen skill also depends on that skill's product data and APIs.

There is no single event table or universal time window that covers arbitrary target skills.
A change in selection can introduce requirements for another product, such as feature flags, dashboards, or error tracking.
For a bounded first case, define the eligible target skill and preserve the normal selection state that leads to it.
Keep other skills available for the static portion if they are in scope, and supply the coherent data required by the selected read-only workflow.
Coverage memory can influence selection but does not guarantee it; record the actual target and treat a workflow with missing fixture dependencies as an invalid case.

For example, the public [LLM-cost skill](../../../../ai_observability/skills/exploring-llm-costs/SKILL.md) supports a bounded cost-total or breakdown task.
Its [regression reference](../../../../ai_observability/skills/exploring-llm-costs/references/regression-debugging.md) expands the history requirement to sixty days, while trace inspection adds linked trace and message content.
Select the workflow before deciding which rows and stores to retain.

Record this restriction as case scope and apply it to every configuration.
It measures that portion of the validation task, not unrestricted skill discovery across the whole product.
This is less suitable as the first general data snapshot because selection and the target workflow introduce two sources of changing requirements.

### Implication for the first data case

Agent feedback is selected for the first version; its fixture must preserve comparison windows and tool-call denominators.
Flag cleanup is the next candidate for testing how much restoration code another scout can reuse.
Trunk and skill validation remain later candidates, once retained external evidence and explicit task scope are supported.
Development and end-to-end verification use the devbox; a comparative experiment remains a separately budgeted step.

## Time and evaluation awareness

A saved dataset eventually falls outside a query for recent activity.
For the first data case, shift the declared timestamps together into the recent past of each comparison batch.
Keep the original snapshot immutable, record the offset, and use the same offset for every configuration and repeat in that batch.
Pass the same explicit investigation start and exclusive end through the runner's existing `run_note` input.
This preserves relative ages, elapsed gaps, and ordering while using the existing tools and real clocks.

The transform must cover event and metadata timestamps, memory cursors and expiry, profile freshness, comparison windows, and relevant dates embedded in retained evidence.
Use a reviewed inventory of fields and date references; do not blindly rewrite arbitrary text or identifiers.
Keep only observations available by the source cutoff, with memory and reports restored to the agreed starting checkpoint.
A historical event timestamp alone does not prove the row was already available then; verify arrival history where possible and disclose any uncertainty.
Existing future expiry dates are valid state, not later observations.

Changing only the agent sandbox clock would leave backend and database queries on real time.
In the current harness, the agent container, backend, MCP server, and ClickHouse do not share one configurable process clock.
[Linux time namespaces](https://man7.org/linux/man-pages/man7/time_namespaces.7.html) do not virtualize the calendar clock.
[libfaketime](https://github.com/wolfcw/libfaketime/blob/master/README) can intercept time calls in supported processes, but coordinating these services, runtime compatibility, and credential expiry would add a separate integration task.
Defer that work for the first version.

Timestamp shifting does not reproduce every arbitrary calendar or relative-time query exactly.
Live clocks keep advancing during a batch, and weekdays, month boundaries, daylight-saving changes, and external repository dates may not retain their original relationships.
Choose a case whose reviewed findings do not depend on those unsupported relationships.
Check window membership, baseline counts and rates, active memory, and profile state before comparison; invalidate a batch if a required boundary changes.
Exact historical time across all tools can be revisited if this bounded approach proves insufficient.

A project containing only one event type may expose an incomplete environment or change the scout's conclusions.
Preserve the coherent context the chosen workflow can reasonably inspect: project profile, discoverable schema, relevant control data, prior reports, and memory.
Do not insert evaluation labels or reveal a special report mode through agent-visible tools.
Avoid invented background data that suggests activity the case does not contain.

No design here guarantees that a model cannot recognize an evaluation.
During later trials, inspect traces for missing-context detours, explicit evaluation awareness, and changes to normal report behavior.
Equal conditions support a comparison within the case; they do not establish production performance across other projects or time periods.

## Case records and grading

Keep a small manifest beside each case's grading instructions:

- Case ID/version, repository commit and file scope, or private dataset reference with checksum and schema version.
- Source cutoff and baseline windows, timestamp-transform version, initial memory and report checkpoint, and supported investigation scope.
- Reviewed findings and valid reasons to file nothing, with a rubric version.

Keep the grading reference inaccessible to the scout, even when stored beside the case manifest.
Record the harness/tool revision, skill body hash/version, model, effective effort, and trial ID with every result.
Case metadata includes `schema_version`, `manifest_sha256`, per-table `state_table_sha256`, and ordered `event_sha256` values.
Record the batch's target cutoff and time offset so reported dates can be mapped back to the immutable source case.
The case ID identifies the shared starting state; each repeated trial has its own mutable state and result directory.
Retain artifacts for the intended comparison period; recreate execution environments when needed.

Use three repeats per configuration as the current starting point, with a separately confirmed execution budget.
Report repeat spread alongside differences between configurations.
Three repeats are not a statistical guarantee.
Infrastructure failures need a separate category from agent-quality failures.

Grade actual reports and justified non-emission, using known findings as a stable recall reference.
Independently verify new findings before calling them false positives merely because the reference list omitted them.
When a rubric or reviewed reference changes, apply the same version to all compared outputs.
For prompt edits, change one behavior at a time and confirm the result on a held-out case.
The round-1 severity definition still needs clarification before the next scored comparison.

## Research and framework review

These sources informed the proposal; their results do not establish scout performance.

| Source                                                                                                                | Useful idea                                                                                                 | Why adoption does not remove the main work                                                              |
| --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| [Echoverse](https://github.com/microsoft/Echoverse/blob/a60d030fed0267f993a1355ffe9ce845eae05f9e/harness/launcher.py) | Copy initial application state, run independently, collect final state, discard the copy                    | Its SQLite application setup does not restore PostHog's databases or coordinate their clocks            |
| [OpenEnv](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_server/interfaces.py)                 | Explicit reset boundary and an [MCP adapter](https://huggingface.co/docs/openenv/tutorials/mcp-environment) | Environment authors still implement restoration and backing tools                                       |
| [Harbor](https://docs.harborframework.com/core-concepts/tasks/overview)                                               | Durable task directories, repetitions, separate environment and verification                                | Keeping the production scout path requires an adapter around capabilities the existing harness supplies |
| [DataSpace](https://arxiv.org/abs/2608.03451)                                                                         | Bounded data workspaces with executable reference checks                                                    | Explicit-question benchmarks do not solve open-ended scout grading                                      |

Keep the PostHog runner and borrow the reset/capture lifecycle and versioned input records.
No additional evaluation framework is proposed as a dependency.
Echoverse's implementation was inspected at the linked commit; OpenEnv and Harbor were inspected on their current branches on September 22, 2026.

The [autoresearch data preparation script](https://github.com/karpathy/autoresearch/blob/master/prepare.py) also separates cached Parquet inputs from repeated executions and reserves a validation shard.
Its loader prepares text for model training; it does not restore PostHog state or MCP behavior.
Reuse the separation of saved data from execution, with Parquet tables and a case-specific PostHog restore step.

## Next decisions and work

1. Resolve missing historical report context and define complete comparison windows before scoring duplicate handling in the data case.
2. Retain the completed code comparison and its scope failures. The later baseline also fails read-scope review, so scope compliance needs repeated checks for every configuration.
3. Clarify severity before a scored model or prompt comparison. These execution checks do not establish an improvement.
4. Keep the devbox command and private case inputs reproducible. Modal deployment remains outside v0.

The production improvements listed in the round-1 [final report](https://github.com/PostHog/posthog/blob/0dd2387f046/products/signals/eval/experiments/2026-09-long-running-agent-evals/FINAL_REPORT.md) remain useful, especially memory isolation, effort recording, and complete report capture.
The isolated eval path can supply these properties without first implementing every production configuration change.
The historical [round-1 run procedure](https://github.com/PostHog/posthog/blob/0dd2387f046/products/signals/eval/experiments/2026-09-long-running-agent-evals/PLAN.md) remains an execution record, not the recommended setup for reusable data cases.

Before unattended execution, verify credentials and model-provider access with invented input and establish the run budget.
If committing or pushing is unavailable, continue independent authorized implementation, tests, and review.
Keep recoverable local source snapshots and attempt history, then commit the sanitized implementation history when publishing is available.
Private inputs and full transcripts remain outside Git.

The [saved-case command guide](../../../../../docs/internal/ai-offline-evaluation-reporting.md#private-saved-scout-cases) covers worktree setup and the validation, preflight, and execution modes.
`--preflight-only` checks saved inputs and local execution prerequisites without starting Django, services, or a model.
Actual execution repeats those checks before repository preparation and retains failed prerequisite checks in its invocation history.
Preflight does not verify provider authentication, databases, free ports, retained bundles, or sandbox images.

## Implementation history

### September 22, 2026: restore and capture support

The shared harness now supports an empty project per trial and private result directories with unique trial IDs.
Scout output includes the initial and final reports, report artifacts, scratchpad, run metadata, and their changes.
Failures retain available output without becoming successful results.
A private engine configuration rejects uploads and does not require reporting credentials.

The retained-repository adapter installs a separate checkout in each Docker sandbox and verifies the saved commit before agent execution.
Its frozen local origin also handles subsequent Git fetches.
This adapter is currently Docker-only.

Focused checks cover empty-project isolation, repeated-trial artifacts, private tracing, scout output capture, retained Git history, and upload rejection.
End-to-end agent execution remains pending at this checkpoint.
The saved-case loader, restoration, and parameterized command are being connected next.

Keep subsequent entries chronological, including failed attempts and validation limits.
Private case inputs, historical evidence, and full run transcripts stay outside version control.

### September 22, 2026: saved cases and first setup attempt

The saved-case command validates file hashes, restores a fresh project, invokes the production scout, and retains private output.
Each attempt records its source commit, local source changes, input versions, target cutoff, model, effort, and outcome.
Restore checks passed through ClickHouse and HogQL in separate projects, including preserved event identities and historical report references.

The first end-to-end attempt stopped during repository preparation before a scout started.
It is recorded as an infrastructure failure.
The command now preserves startup exceptions and rejects runs without a completed task and transcript.
The fixed-page code cases explicitly retain one commit and its complete tree, which avoids requiring every historical blob from a partial clone.
The original commit SHA remains unchanged; a verified bundle cache supports retries.

Feedback cases retain profile expiry, so an expired profile refreshes from the restored project.
Finding discovery and duplicate handling are in scope for the first saved data case.
Full reviewer routing remains outside its supported context.
End-to-end execution and repeatability checks remain pending.

### September 22, 2026: first Docker startup check

The next attempt completed service setup and verified the pinned commit inside the Docker container.
The agent server then failed before producing a response while clone and startup overlapped.
The retained adapter now uses the existing clone-before-startup path and records that setting.
Its cache also works when the original source checkout is unavailable.

Saved-data checks passed through the real query engine, including event counts, timestamp bounds, historical identities, and isolated project state.
Private storage checks reject unignored paths in sibling Git repositories too.
The command restores progress logging after ASGI initialization and retains source snapshots for failed attempts.
Both execution attempts remain classified as infrastructure failures; a completed scout run is still required.

### September 22, 2026: completed code execution

The code baseline and its one-rule traced-file variant both completed through the production scout harness, real local MCP, and Docker.
Each took about three and a half minutes after service initialization was cached.
Outputs retained full reports, memory changes, transcript, input versions, and repository verification.
The baseline checkout remained clean at the pinned commit after execution.

Independent review of the baseline found an ordering gap but errors in the report's explanation and proposed fix.
This is a successful infrastructure check, not a verified quality pass.
The second code page remains the held-out check for the same prompt edit.
Private data execution awaits explicit model-provider approval; local restoration checks can proceed independently.

### September 22, 2026: bounded prompt comparison

All four code runs completed: two selected pages, each with the original prompt and the same traced-file rule change.
The second-page baseline produced a supported finding and fix.
It created a suppressed report and a replacement for the same issue, which count as one finding.

The first-page variant produced a supported finding but searched outside its permitted scan roots.
That run fails scope review even though its reported endpoint was selected.
This example supports keeping correctness, scope, severity, and execution status separate.
One run per combination does not establish prompt improvement, and severity remains unsettled.

Local output includes the complete history of failed setup attempts and completed runs.
Repository-wide type checking and full-size data restoration checks are in progress at this checkpoint.

### September 22, 2026: completed comparison review

The second-page variant's finding and proposed fix are supported, but it also searched outside the selected scan roots.
It missed the stronger message-cursor defect found by the baseline.
Both candidate runs therefore fail scope review, and the prompt change is not recommended for adoption from this example.
The comparison remains one run per combination with no claim of statistical superiority.

The complete repository mypy check passes after annotation fixes in the loader and test helpers.
The retained-repository tests also pass.
Full-size historical data verification is running independently with external connections blocked and no scout execution.

### September 22, 2026: full-size restoration checks

The full-size restore exposed slow date substitution and small database writes that the small fixtures did not reveal.
Grouping timestamp alternatives under shared boundary checks preserves replacement precedence and removes repeated matching work.
Generated differential cases and private-corpus comparisons produce identical transformed text.
The loader now writes bounded batches of 5,000 events, and the existing saved-case tests pass through the real query engine.
Interrupted attempts retain their partial counts and remain separate from completed restorations.

The private command's gateway settings need to cover backend report checks as well as sandbox model calls.
A scoped backend override is being added to use the private gateway without changing the developer's running services.
Full-size repeatability verification remains in progress at this checkpoint.

### September 22, 2026: repeated historical restoration verified

Two complete restores into fresh projects pass the saved-input and real-query checks.
Normalized historical state and event aggregates are equal across the projects, while their project, organization, member, and mutable-state identities are separate.
Skill and profile contents match, governed metrics retain their definitions, and downstream actions remain disabled.
Neither restored project has been used by a scout.
A deterministic event sample, including the reference evidence, also preserves full properties, timestamps, and supplied identities in both projects.

The restore uses bounded event batches and avoids repeated copying of the growing SQL parameter dictionary.
The shared runner now records ordinary cancellation as an error while retaining available output and initial-state metadata.
Repository-wide type checks and strict preflight pass.
The private backend route passes focused credential-scope and cleanup tests, including failure and cancellation.
A live provider check and private data scout execution remain pending at this checkpoint.

### September 23, 2026: private backend provider check

The normal report safety check completed with invented input through the private gateway.
The provider returned a valid judgment, both capture tokens were absent, and the temporary credential was deleted afterward.
Gateway settings were restored and the dedicated process stopped without changing the developer's running services.
The saved feedback case is ready for its first scout execution.

### September 23, 2026: first complete data scout execution

The saved data case completed through Docker, real MCP tools, and the production scout runner.
It retained a report, memory changes, the full transcript, input versions, restored-data checks, and usage from both the scout and backend report check.
The dedicated sandbox and service listeners were removed afterward; the developer's normal stack remained running.
The container mounted local skills without mounting the checkout or private grading files.

Initial review supports the reported symptom but does not establish its root cause or a verified fix.
The scout also missed a recurring theme and misstated an aggregate count in memory.
Duplicate handling requires further review of a historical memory pointer and saved report coverage.
The explicit investigation interval held, while a broader comparison queried beyond the retained data boundary.
The scout speculated that some feedback might be synthetic; the transcript does not establish that it recognized an evaluation.
These remain quality and case-coverage findings, separate from the successful execution check.

An identical data repeat is running in a fresh project with the same target cutoff.
The updated branch passes repository-wide type checking.
A CI rule flagged an older seed test's use of the current time; its fixture now uses a fixed timestamp, and the focused test and exact lint rule pass.

### September 23, 2026: data repeat and current-runtime code check

The identical data repeat completed with the same case, skill, cutoff, model, and effort in another fresh project.
Normalized starting reports, artifacts, memory, and prior runs match exactly; mutable record identities are separate and no first-trial writes appear in the second trial's starting state.
Restored event checks also match.
Configuration creation and update timestamps reflect each trial's setup time.

Both data trials reported the same candidate issue, while investigation depth, duration, cost, and memory accuracy varied.
The repeat avoided the first run's speculation about synthetic data but still missed other candidate themes.
Historical duplicate status remains unresolved.
Queries using the live clock changed a comparison count despite identical restored events, and broader comparison requests exceeded the saved boundary.
The case supports repeated discovery checks with these stated limits; it does not establish exact historical behavior for every relative-time query.

The code baseline completed on the updated agent image and private gateway, with its checkout and frozen origin verified at the saved commit.
Its report describes a supported ordering problem, but it read files outside the selected page and therefore fails scope review.
Severity remains unsettled.
Full outputs, input hashes, runtime image identity, gateway costs, failed attempts, and private reviews remain available locally.
Both completed environments removed their agent containers and dedicated listeners while leaving the developer's normal stack running.

CI follow-up uses the existing product facades for fixture access and moves the Docker integration test into its owning product.
The empty-project helper returns named fields, preserving the fresh-project setup behavior.
After these fixes, 48 focused tests pass, including repeated restoration, fresh-project setup, fixture isolation, model-boundary invariants, and test-module naming.
Repository-wide type checking, the CI import-boundary command, harness discovery, and the exact new lint rule also pass.

### September 23, 2026: realism review and comparison strategy

A read-only review of the retained code and feedback transcripts found substantive source investigation, data queries, history checks, and supported findings.
Some scout comments questioned whether parts of the context were synthetic, but the scouts continued investigating.
The transcripts contain no explicit identification of the assignment as an evaluation and do not establish deliberate test gaming.
They also do not establish production-equivalent behavior.

Observed quality failures include missed issues, shallow grouping, inaccurate counts, and source-read scope violations.
Missing historical reports, advancing clocks, and limited ownership context remain separate environment limitations.
The evidence does not establish that awareness of the environment caused the quality failures.
Use the saved cases for bounded comparisons with those limitations recorded, and validate promising changes against current data before deployment.

Implementation, operating instructions, decisions, and sanitized findings are versioned in this repository.
Historical snapshots, raw transcripts, source feedback, and detailed private reviews remain outside Git on the devbox.
A pushed branch preserves the implementation and summarized context; it does not back up those private inputs or results.
