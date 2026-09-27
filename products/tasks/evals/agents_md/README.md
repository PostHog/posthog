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
A positive difference means the rule reduced violations. A difference near zero means the sentence did not change behavior, so either the agent does it anyway or the words do not work.

Each run is one sample. Use `--repeats` so the difference is not noise.

## Run it

From a devbox, with `claude` or `codex` on `PATH`.
The judge uses `ANTHROPIC_API_KEY` when it is set, and the signed-in `claude` CLI otherwise:

```bash
python -m products.tasks.evals.agents_md list
python -m products.tasks.evals.agents_md run --claim frozen-dataclasses --runtime claude --model claude-opus-5-5
python -m products.tasks.evals.agents_md run --repeats 3 --workers 4 --runtime codex --model gpt-6-sol
python -m products.tasks.evals.agents_md report --results-dir products/tasks/evals/agents_md/results/<run>
```

Results land in `products/tasks/evals/agents_md/results/<timestamp>-<runtime>-<model>/`, which git ignores.
Each run writes a `.json` with the violation count and details, the `.diff`, and the agent log.

## Add or change a claim

`test_agents_md.py` fails when a `[review]` bullet in `AGENTS.md` has no entry in `claims.json`, or when an entry matches no bullet.
An entry's `starts_with` is the start of the bullet text. It must match exactly one bullet.
A bullet can have several entries when one trap is not enough, for example a task that names the forbidden path and one that does not. Each entry is its own claim with its own id.

A claim with no small task that has one right answer gets `untestable` with the reason instead of a task.
A claim whose right answer is to refuse the task gets `no_change_is_compliant`, so an empty diff scores zero instead of "cannot tell".
The `judge` detector asks the model three times and reports the share of answers that saw a violation.
The report marks a rule "no evidence" when no run without the rule broke it, because that says the trap did not tempt, not that the rule is useless.

Detectors take their parameters from the entry. `count_added_matching` and `missing_added_matching` cover most rules with a regex.
Add a function to `detectors.py` when a rule needs to read the file or parse the code.
