# Reusable scout environments

Research checkpoint: September 22, 2026.
This is a proposal, with the initial harness review at `ba2de6b231b` and additional dependency checks after merging `e7e0c103433` from master.
No new scout experiment or snapshot export was performed during this analysis.

## Purpose and agreed constraints

Keep a small set of scout cases usable for one to two months so that a new model, reasoning effort, or prompt can be compared with the current production configuration.
One trial runs one scout once, from reset initial state.
Every configuration uses the same execution path.
Fine-tuning, a new UI, an always-running environment, and a general snapshot service are outside the first version.

The saved case contains the world being investigated: repository state, project data, relevant history, and task scope.
The selected scout, prompt, model, and effort can change independently of those inputs.
Use the same harness and tool versions throughout a comparison and retain their versions with the outputs.
Rerun the current production configuration alongside candidates; an old score alone cannot distinguish an agent improvement from a change in the tools, harness, or rubric.

The first usable version needs both a code case and a data case.
Reuse the API-quality file sets from round 1 and add a bounded historical dataset for a data scout.
Historical data and resulting traces must stay in private storage; public files contain the case structure and implementation only.
Synthetic cases remain useful and are already supported by the existing harness.

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
5. Grade the result and discard the writable trial state.

A disposable agent sandbox is only part of the isolation.
Its MCP credentials must point to the restored project, and external reads must also use retained inputs where they affect the case.
No trial may silently fetch missing evidence from a changing production project.
Report creation should behave normally inside the eval project while downstream delivery and implementation remain disabled.

The existing [case seeders](../../../evals/agentic/seeders.py) and [scout cases](../../../evals/agentic/cases/scout.py) provide examples of real product data with report and no-report outcomes.
The following additions still need implementation:

- Enforce and verify a repository commit before the first agent turn. `repo_fixture` in the [case config](../../../../posthog_ai/eval_harness/config.py) is currently descriptive. A skill that fetches a moving remote branch must still see the retained repository state.
- Restore one case-specific data snapshot with schema and relationship checks. A reused demo project is not a versioned dataset.
- Load the selected skill version and restore its initial memory and report history.
- Apply one consistent time policy across the agent context, product APIs, and database queries.
- Capture complete persisted reports and memory changes. The current scout adapter exposes IDs and newly created memory keys, which are insufficient to grade all content and edits.

The [suite instructions](../../../evals/agentic/AGENTS.md) currently describe public repositories and synthetic fixtures.
A historical snapshot requires a private-fixture path and a review of every log and artifact destination.
`WorkflowPrivateEval` is an existing starting point; its flags alone do not establish privacy for every downstream service.

## Environment options

| Option                                       | What is retained                                           | Fit for the first version                                                          |
| -------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Pinned code and small project state          | Git commit, task scope, memory, report history             | Use for API quality; the repository alone does not preserve deduplication state    |
| Synthetic data in real PostHog               | Deterministic scenario setup and expected outcomes         | Existing support; useful controls, with realism limited by scenario design         |
| Bounded historical data in real PostHog      | Selected rows, metadata, related state, and time reference | Preferred direction for the first data scout                                       |
| Parquet queried through a custom MCP backend | Saved tables plus an implementation of the selected tools  | Consider only for a narrow interface; reproducing HogQL and product APIs adds work |
| Full service and project snapshot            | Broad application and database state                       | More storage and maintenance than the initial cases justify                        |

Parquet can store the bounded historical dataset while the restored case still uses real PostHog queries.
It does not require replacing MCP or ClickHouse.
ClickHouse supports [Parquet input and output](https://clickhouse.com/docs/reference/formats/Parquet/Parquet); schemas and product metadata still need explicit restoration.
[DuckDB can query Parquet directly](https://duckdb.org/docs/current/data/parquet/overview), but that does not supply PostHog's other tool behavior.

Recorded tool responses cannot serve as the main environment for exploratory comparisons.
A different model may issue a new query or inspect another filter, for which a recording has no answer.
The retained state must support those valid alternative investigations within the case's declared scope.

## Data boundaries

The working first data candidate is feedback analysis.
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

Feedback analysis remains the proposed analytics case; a manageable fixture must preserve its comparison windows and tool-call denominators.
Flag cleanup offers a smaller alternative or second data case because much of its evidence is stored metadata plus code.
Trunk and skill validation add useful coverage later, once retained external evidence and explicit task scope are supported.
This review does not change the selected first case or authorize any run.

## Time and evaluation awareness

A saved dataset eventually falls outside a query for recent activity.
Choose one policy per case: a consistent fixed reference time, or a documented shift of all relevant timestamps around the trial's reference time.
The policy must cover event and metadata timestamps, memory expiry, query windows, and linked evidence.
Freezing Python's clock alone does not control ClickHouse `now()` or external services.
This is a requirement to resolve for the selected case, not a reason to build a universal time service.

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
- Time reference/policy, initial memory and report state, and supported investigation scope.
- Reviewed findings and valid reasons to file nothing, with a rubric version.

Record the harness/tool revision, skill body hash/version, model, effective effort, and trial ID with every result.
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

## Next decisions and work

1. Choose the first data scout and one coherent case boundary using the dependency comparison above.
2. Specify its data selection, private artifact location, time policy, initial state, and expected checks.
3. Implement only the restoration and output-capture work that those cases require, using the existing runner.
4. Verify repository identity, restored queries, state isolation, and report containment before running agents.
5. Clarify severity and execution budget, then obtain approval for a new experiment.

The production improvements listed in the round-1 [final report](FINAL_REPORT.md) remain useful, especially memory isolation, effort recording, and complete report capture.
The isolated eval path can supply these properties without first implementing every production configuration change.
The historical round-1 run procedure in [PLAN.md](PLAN.md) remains an execution record, not the recommended setup for reusable data cases.
