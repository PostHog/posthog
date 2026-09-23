# Long-running agent evals: framework plan, instance one (the API-quality scout)

This document records the round-1 design and the [proposed lightweight live comparison workflow](#proposed-lightweight-live-comparisons).
For the proposed reusable environments, current decisions, and remaining work, see [Reusable scout environments](REUSABLE_ENVIRONMENTS.md).
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
This section describes changes to build; no trial API or production isolation mode has been implemented by this proposal.
Continue on this branch after the offline-v0 checkpoint `147adbcc3bd`, keeping subsequent implementation commits separate for a later PR split.

### Intended operator flow

Select an existing scout and run its current configuration alongside one or more changes to its prompt body, model, or reasoning effort.
Keep the existing production scout running normally.
Use its real project data, repositories, and supported read tools without preparing a dataset or changing its saved configuration.
Every trial gets private writable memory and captured outputs, including outputs it can read again during its investigation.

Start with one asynchronous trial endpoint, exposed through MCP, and a small operator script.
The script reads a variants file, launches the requested repetitions with bounded concurrency, polls results, and downloads the comparison.
Calling the endpoint directly supports a single manual trial; the same endpoint supports a scripted grid.
No UI, automatic prompt optimizer, or new execution platform is needed for this version.

The practical sequence is:

1. Pick the source scout, optional common investigation note, variants, repeat count, and maximum concurrency.
2. Resolve the current skill, runtime defaults, and initial scout context once for the comparison.
3. Launch each trial with its selected overrides and its own execution identity.
4. Let it investigate live data through the normal harness and supported tools.
5. Review complete captured outputs, memory changes, logs, effective settings, duration, and attributed cost together.
6. Retain or delete the comparison and its private state through the operator API.

Include the current configuration as a baseline when making a quality comparison.
A single repeat is a smoke check; repeated runs are needed to see whether a difference exceeds ordinary run-to-run variation.
Judging remains manual in v0, using a scout-specific checklist and evidence checks.
Without a reviewed answer set, pooled verified findings measure relative coverage within the comparison, not absolute recall.

### Small API surface

Add a one-off action beside the existing `run` action on the scout config API, for example `POST /api/projects/{project_id}/signals/scout/configs/{config_id}/try/`.
The route and field names here are proposed, not available commands.

| Input                       | Purpose                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------- |
| `group_id`                  | Omit to create a comparison; reuse it to share the source settings and initial context with later trials. |
| `idempotency_key`           | Retrying a launch returns the same trial instead of starting another paid run.                            |
| `variant`                   | Operator-facing label, kept out of the scout's prompt and discovery tools.                                |
| `model`, `reasoning_effort` | Optional overrides; omitted values resolve from the comparison's recorded baseline.                       |
| `skill_body`                | Optional replacement body supplied by the operator or read from a local file by the script.               |
| `note`                      | Optional common task focus, such as a closed investigation window or selected files.                      |

The first request creates the comparison and saves the source configuration, pinned skill version, and initial scout context before applying that first trial's overrides.
Starting with a candidate must not redefine the baseline for later trials.
Changing the model still uses the saved baseline effort unless the operator overrides it; reject an incompatible combination before dispatch.
Later requests cannot silently change that source snapshot or common note.
Each accepted launch immediately returns a durable trial ID, comparison ID, status, and resolved settings; the scout run ID becomes available once its task exists.
Persist setup failures against the trial too, so a failed launch does not disappear from the comparison.
Store large context and output bodies by reference instead of putting them in Temporal payloads.
Reuse existing project permissions and skill-authoring checks for prompt or note overrides.
Recheck current access to source skills, repositories, and connections at launch; a saved selection must not preserve revoked permissions.
Reject or explicitly record capability changes instead of silently running with a different toolset.
Operators can list, retrieve, cancel, download, and delete their authorized comparisons; sandbox tokens cannot operate the comparison API.

### Required product changes

| Change                                        | Why round 1 or the current code requires it                                                                                                                                             | Smallest useful behavior                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One-off runtime selection                     | Config pins carry a model, while the manual trigger accepts only a note. Different model defaults changed effort in round 1.                                                            | Thread validated model/runtime/effort through REST and Temporal into the runner's existing runtime override. Resolve baseline defaults once and reject unsupported combinations before dispatch. Record requested and effective values; mark observed mismatches invalid for comparison.                                                      |
| Private prompt selection                      | Permanent skill copies change skill origin and harness instructions. The scout fetches its body through `skill-get`, so replacing an in-memory body alone does not apply the candidate. | Preserve the source name, origin, owners, and tool permissions. Bind `skill-get`, including pagination, to the trial's saved body. Freeze supporting files from the source version; file/tool-grant edits are outside v0.                                                                                                                     |
| Independent execution                         | The endpoint, Temporal workflow ID, and runner all enforce one active run per skill. Changing only one check leaves the others in place.                                                | Give each trial a unique workflow identity and keep trial rows out of the production concurrency guard, stale-run recovery, history, and health updates. Retain idempotency, authorization, concurrency limits, and normal spend enforcement.                                                                                                 |
| Private memory                                | Shared-key writes and substring searches allowed copies to influence one another and the production scout. Original-author metadata does not identify the last writer.                  | Snapshot initial scratchpad and recent scout context once per comparison. Each trial searches that starting state plus its own changes. Remember, forget, and exact-key reads operate only on that trial's state, preserving normal keys.                                                                                                     |
| Full output capture                           | Dry-run can tell the scout not to file and does not provide a normal readable output. Editing a report can also mutate an existing production report.                                   | Validate and capture report creation, report edits/notes/evidence, weak signals, and structured records privately. Preserve normal safety checks and stable IDs. Subsequent reads see the trial's own new or edited outputs. Never send captured outputs into inbox delivery, grouping, notifications, implementation, or event destinations. |
| Consistent visibility                         | Fleet profiles, run searches, task listings, and logs can reveal sibling activity. The profile currently exposes dry-run eligibility.                                                   | Derive the trial from its authenticated sandbox task, then apply that context consistently to list, search, detail, log, and mutation paths. Trials see normal production context and their own private changes; ordinary scouts see no trial state. Profile eligibility reflects acceptance by the private output path.                      |
| Restrict other mutations                      | Disabling optional write grants still leaves default notebook and task writes; external MCP servers have separate credentials.                                                          | Use a restricted trial token posture. Permit supported reads, private scout writes, and necessary own-task bookkeeping. Deny unrelated production mutations and reject scouts or connections whose required effects have no private implementation.                                                                                           |
| Keep trial telemetry out of investigated data | Lifecycle events, MCP tool traces, feedback submissions, and model generations can themselves become data another scout queries.                                                        | Carry a trusted trial capture policy through backend, MCP, and the active model gateway. Keep these records outside the queried project while preserving billing and private per-run usage. Tags or hidden UI rows alone do not establish isolation.                                                                                          |

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

For v0, support investigation scouts using supported PostHog and repository reads plus captured scout outputs.
Scouts that need product mutations, new task launches, or writable third-party connections need additional effect-specific support.
Read-only external connections can be admitted once their credentials and tools have a verified read boundary.
Do not claim that every scout can run with unchanged behavior under a restricted token.

Telemetry isolation is a required part of the feedback use case.
The source review found independent capture paths in the backend, MCP server, and Python model gateway; it did not establish the active production gateway route or every warehouse replica exposing task data.
Verify those destinations before implementing or promising that sibling activity cannot be discovered.
The offline harness's private reporting flag is not a production-wide telemetry switch.
Any gateway work must follow the existing [gateway migration policy](../../../../../services/llm-gateway/PARITY.md), rather than adding a new Python gateway feature by default.

### Reuse and implementation order

Reuse the [scout runner](../../../backend/scout_harness/runner.py), [Temporal dispatch](../../../backend/temporal/agentic/scout_scheduler.py), [run views](../../../backend/scout_harness/views.py), and existing sandbox provisioning and logs.
The runner already accepts an explicit runtime and records model settings.
The existing [cost reader](../../../backend/scout_harness/run_costs.py) can supply ordinary run costs, but its shared generation-event source must be reconciled with private capture before it is used for isolated trials.
Keep unknown or still-arriving cost distinct from zero.

1. Confirm the deployed telemetry and billing routes so the isolation design covers the services actually used.
2. Add the durable trial/context record and enforce token-bound private memory, output capture, visibility, mutation restrictions, and private telemetry routing.
3. Add one-off settings and prompt resolution, unique dispatch, cancellation, and operator results.
4. Add the thin launch/poll/download script and MCP action.
5. Prove isolation with two simultaneous trials, including retries and failures, before the first live comparison.

The acceptance check must show that the same memory key can hold different values in two trials while the production value stays unchanged; guessed sibling IDs cannot be read or mutated; own outputs remain readable; private report edits leave originals unchanged; scheduled scout state stays unchanged; no downstream delivery or sibling-visible telemetry occurs; and the effective prompt/model/effort match the requested variant.
These are requirements for the implementation, not results already established by the offline checks.
