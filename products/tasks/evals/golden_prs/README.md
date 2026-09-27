# Golden PR evals

Score how well a coding agent can one-shot a real PostHog pull request.

The golden set is a list of pull requests from 2023 and 2024, written and reviewed by people before coding agents were common.
For each PR, the eval:

1. Checks out the repository at the commit before the PR merged. The agent gets a fresh git repository with only that tree, so it cannot read the merged PR from git history.
2. Sends the PR title and description to the agent as its only prompt.
3. Compares the agent's diff with the merged PR's diff.

## Scores

| Score          | What it measures                                                                                   |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Files hit      | Share of the golden PR's files that the agent also changed.                                        |
| Line F1        | Overlap between the added lines of the two diffs.                                                  |
| Judge          | An Anthropic model reads the task and both diffs and scores behavioral equivalence from 0 to 1.    |

Snapshot files and images are ignored, because an agent cannot regenerate them without the test suite.
The deterministic scores are strict, so a correct change written in a different way scores low on them. Read the judge score and its reasoning together with them.

## Known limits

The agent runs unsandboxed (`--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox`), with its working directory as a soft boundary rather than a hard one. It is not run inside a container or namespace, so it could, in principle, read the original checkout that fetched the golden merge commit, or other host state, instead of relying on the PR description alone. Treat a score as a signal for comparing agents and models, not as proof the agent only ever saw the task description.

## Run it

From GitHub, open the **Golden PR Evals** workflow and choose **Run workflow**. Pick the runtime, the model, and the PR numbers. Each PR runs as its own job. The run summary shows the score table, and the artifacts hold every diff, agent log, and score file.

From a devbox, with `claude` or `codex` on `PATH`.
The judge uses `ANTHROPIC_API_KEY` when it is set, and the signed-in `claude` CLI otherwise:

```bash
python -m products.tasks.evals.golden_prs list
python -m products.tasks.evals.golden_prs run --pr 25832 --runtime claude --model claude-opus-5
python -m products.tasks.evals.golden_prs run --runtime codex --model gpt-5.5
python -m products.tasks.evals.golden_prs report --results-dir products/tasks/evals/golden_prs/results/<run>
```

Results land in `products/tasks/evals/golden_prs/results/<timestamp>-<runtime>-<model>/`, which git ignores.

## Add a golden PR

Pick a merged PR that a person wrote, with a description that says what should change. Small, self-contained fixes and features work best. Then append it to `golden_prs.json`:

```bash
gh pr view <number> --json number,title,body,mergedAt,mergeCommit,author \
  --jq '{number, author: .author.login, title, merged_at: .mergedAt, merge_commit_sha: .mergeCommit.oid, body}'
```

The tests in `test_golden_prs.py` check that every entry is complete.
