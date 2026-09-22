# Long-running agent evals: framework plan, instance one (the API-quality scout)

## Question

For one agent task, which model and prompt version does the job best per dollar, and can a prompt change be shown to fix one weakness without breaking the rest?
The framework must work for any long-running agent (scouts first, then report research and ReviewHog).
The first instance is the API-quality scout, a code-reading scout that sweeps backend API files for contract gaps.

## Decisions fixed before running

- **Arms run in production on the internal dogfood project.** Each arm is a duplicate of the scout under an experiment name, with `emit=false` (nothing reaches the inbox) and `enabled=false` (never scheduled), triggered by hand. Data, inbox and memory reads stay live.
- **The task is frozen, the agent is not.** Every arm gets the same pinned commit and the same file list. The scout's judgment inside that task is what we measure.
- **An arm is one model plus one prompt version.** Any combination is allowed. The current canonical skill is always one arm, so a prompt change is scored as the difference from it in the same batch.
- **N runs per arm** (default 2) **on two task sets.** A gap between arms counts only if it beats the gap between an arm's own runs.
- **The judge is a different model family from the arms**, works from a checklist, and every "real" verdict gets a skeptic pass.
- **No code in the product.** Everything here is configuration on the project plus scripts and documents in this folder.

## The framework (agent-agnostic)

1. **Freeze the task.** Pin whatever the agent would pick at run time. Per agent type: a code scout gets a commit and a file list; a data scout gets a closed time window; ReviewHog gets a PR head; report research gets a report's signals and a repo commit.
2. **Build the arms.** One skill copy per arm: the frozen task written into the body, memory writes under an experiment prefix, no writes to shared keys, `emit=false`, `enabled=false`, model pinned on the config. N copies per arm so runs can start together.
3. **Run the batch.** All arms at the same time, so they read the same live state.
4. **Deterministic layer.** Hard checks that need no judgment: finished within budget, produced an output or a clean close-out, wrote memory only under its prefix, left shared keys untouched, cost, duration. Optional: a candidate script that lists mechanical findings for the judge to check against.
5. **Judge.** One judge per output with the agent's rubric file, the pinned inputs, and the transcript. Rubric items are yes / no / unsure, non-overlapping, split into process (did it do the work), outcome (is the result right) and hygiene. Every "real: yes" gets a skeptic that tries to refute it. A pooling step merges verified findings across arms; recall per arm is its share of that pool.
6. **Score.** One row per run, one row per judged finding. Per arm: rates per rubric item, recall, cost per verified finding, duration, and the spread between its own runs.
7. **Edit loop.** Change one thing in the skill. Run it against the current skill with the same N on the same files. Keep it only if the target item improves and nothing else drops. Confirm on the second task set, which was not used to design the change.
8. **Record.** `fixtures/` (pinned inputs, rubric version, skill diffs), `results/` (runs and findings), `FINAL_REPORT.md`.

## Instance one: the API-quality scout

- **Freeze recipe.** `fixtures/commit.txt` holds the commit. `fixtures/page-1.txt` and `page-2.txt` hold two sets of 100 backend API file paths, taken from the scout's own file list and hash order at that commit.
- **Skill copy.** Same body as the canonical scout except: the "choose the files" section is replaced by the fixed list and commit; memory keys use the `exp-apiq:` prefix; the shared sweep cursor is never written. The diff is stored in `fixtures/`.
- **Arms for batch 1.** Three models the fleet already runs (luna, terra, sol) on the current skill, N = 2, two pages: 12 runs. The model pin carries the model only; reasoning effort and queue tier follow the fleet defaults and are recorded, not varied.
- **Hard checks.** Run status, report emitted or clean close-out, memory prefix respected, cursor untouched, duration under 15 minutes, cost.
- **Candidate script.** Over the pinned files: offset pagination without ordering, a list endpoint using a heavy detail serializer, a tenant model read without a team filter. A cheat sheet for the judge, not a verdict.
- **Rubric v0.** Per report: real defect; in scope per the skill's own discriminator; endpoint, file, symbol and fix direction named and right; severity P2 vs P3 per the skill's definitions; not a duplicate of an inbox report or memory entry. Per run: recall against the pooled findings; hygiene from the hard checks. Rates, not scores.
- **Judge.** Claude-family judge (the arms are GPT), run as a workflow from a devbox with the repo at the pinned commit and read access to the project for inbox and memory.

## Metrics

- Per rubric item: share of reports that pass, per arm.
- Recall: share of the pooled verified findings each arm found.
- Cost per verified finding and duration, per arm.
- Noise: the spread between an arm's own runs, reported next to every gap.
- Refusals, timeouts and infra failures counted separately, excluded from rates.

## Cleanup

Experiment skill copies and their configs are deleted after the batch. Memory entries under the experiment prefix are deleted by their creating run. Nothing else on the project is touched.

## Not in this version

Judge calibration against hand-labelled reports. Rubric versions with a human-labelled set. Automated judging in the product UI. A memory-driven skill loop. Report research and ReviewHog instances.
