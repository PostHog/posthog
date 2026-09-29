# AGENTS.md claim evals

Measure whether each `[review]` rule in the root `AGENTS.md` changes what a coding agent does.

A `[lint: ...]` rule has a linter behind it, so CI catches a miss. A `[review]` rule has only the text.
This eval checks that the text earns its place.

## How it works

For each `[review]` bullet in `AGENTS.md`, `claims.json` holds:

- A trap task: a small change that tempts an agent to break the rule. The task never mentions the rule.
- One or more detectors: deterministic checks on the agent's diff, or a model judge for rules no regex can read.

Each run checks out the repository at one commit into a fresh git repository, writes the `AGENTS.md` variant for the arm, then runs the agent on the trap task:

- `with`: `AGENTS.md` unchanged.
- `without`: `AGENTS.md` with that one bullet removed.

The detectors count violations in the diff. The report shows the mean per arm and the difference.
A positive difference means fewer detected violations in the with-rule samples.
A difference near zero means this comparison found little difference on the selected task.

Each run is one sample. Use `--repeats` to observe variation between runs.

These scores are observations from the selected tasks, not statistical confidence or proof that the changes work.
Removing a root bullet leaves related skills, nested instructions, and repository examples available.
A zero in both arms does not show that a rule is unnecessary.
The entrypoint detector flags a query built inside `handle()`; other logic in the entrypoint passes it.
Failed agent runs are excluded from detector summaries, and missing scores remain unmeasured.
The run command returns a nonzero exit status if any job crashes or an agent run fails.
The team-scoping claim checks application files. Test files and fixtures neither satisfy its required read nor count as violations.

Each successful run also receives a separate task assessment: `issues_found`, `no_issues_found`, or `unmeasured`.
This judge checks the requested behavior and unsupported factual claims. It does not run tests.
`no_issues_found` means the judge found no visible issue, not that the output is correct.
Review the saved diff and assessment before accepting a low instruction score.

For these trials, the Claude CLI disables configurable hooks with its per-run settings so setup hooks cannot change the checkout.
Managed hooks remain subject to the CLI's policy. The runner rejects a trial if files under `.flox/` change and preserves its raw diff.
Prepare required tools on the devbox before the run. These controls do not turn the agent process into a security sandbox.

## Run it

From a devbox, with `claude` or `codex` on `PATH`.
The judge uses `ANTHROPIC_API_KEY` when it is set, and the signed-in `claude` CLI otherwise:

```bash
python -m products.tasks.evals.agents_md list
python -m products.tasks.evals.agents_md run --claim frozen-dataclasses --runtime claude --model claude-opus-5-5
python -m products.tasks.evals.agents_md run --repeats 3 --workers 4 --runtime codex --model gpt-6-sol
python -m products.tasks.evals.agents_md report --results-dir products/tasks/evals/agents_md/results/<run>
```

Use the standard model matrix for a comparison campaign:

```bash
python -m products.tasks.evals.agents_md run --matrix --claim frozen-dataclasses --repeats 3 --dry-run
python -m products.tasks.evals.agents_md run --matrix --claim frozen-dataclasses --repeats 3
```

The matrix includes Claude Opus 5.5, Claude Fable 5.1, Claude Sonnet 5.5, GPT-6 Astra, and GPT-6 Sol.
The dry run lists jobs without calling agents or judges. Both CLIs must be signed in before the real run.
Single-model runs still use `--runtime` and `--model`. Results are stored in separate model directories.
Repeats alternate which arm runs first. All models share the worker limit.

To compare a complete proposed file against the current file at a fixed commit:

```bash
python -m products.tasks.evals.agents_md run --ref <commit> --candidate-agents-md /path/to/candidate.md --claim double-submit-guard --repeats 3
```

In this mode, `with` means the candidate file and `without` means the current file.
The report labels the two files explicitly. Both file snapshots and each run's instruction hash are saved with the results.
Report whole-file comparisons separately from individual-rule removal runs.
Review task correctness separately; this runner instructs agents not to run the test suite.

Results land in `products/tasks/evals/agents_md/results/<timestamp>-<runtime>-<model>/`, which git ignores.
Each run writes a `.json` with the violation count and details, the `.diff`, and the agent log.

## Add or change a claim

`test_agents_md.py` fails when a `[review]` bullet in `AGENTS.md` has no entry in `claims.json`, or when an entry matches no bullet.
An entry's `starts_with` is the start of the bullet text. It must match exactly one bullet.
A bullet can have several entries when one trap is not enough, for example a task that names the forbidden path and one that does not. Each entry is its own claim with its own id.

A claim with no small task that has one right answer gets `untestable` with the reason instead of a task.
A claim whose right answer is to refuse the task gets `no_change_is_compliant`, so an empty diff scores zero instead of "cannot tell".
The `judge` detector asks the model three times and reports the share of answers that saw a violation.
The report marks a rule "no evidence" when no run in either arm broke it, because that says the trap did not tempt, not that the rule is useless.

Detectors take their parameters from the entry. `count_added_matching` and `missing_added_matching` cover most rules with a regex.
Add a function to `detectors.py` when a rule needs to read the file or parse the code.
