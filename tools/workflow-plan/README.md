# workflow-plan

Evaluates the `if:` conditions in `.github/workflows/*.yml` the way GitHub does, against synthetic PR, push, schedule, and cancellation scenarios, and reports which jobs and steps run.
The evaluator is GitHub's own [`@actions/expressions`](https://www.npmjs.com/package/@actions/expressions), so operator precedence, coercion, `contains`, `fromJSON`, and the `labels.*.name` filter syntax behave as they do in Actions.

## See a workflow's run plan

```bash
hogli ci:plan .github/workflows/ci-backend.yml
hogli ci:plan .github/workflows/ci-backend.yml --steps changes
```

The table has one column per built-in scenario (draft PR, ready PR, fork PR, merge queue, master push, schedule, dispatch, cancelled run) and one row per job.
Every paths filter is stubbed as if all of its filters matched.
Outputs that scripts produce at runtime are empty, so a job gated on `needs.x.outputs.matrix != ''` shows as skipped until a scenario stubs that output.

## Pin the intended behavior in a test

```bash
hogli test:workflows
```

`tests/workflows.test.ts` holds one row per workflow and scenario, naming the jobs that must run and the jobs that must skip.
The rows encode the rules in [the authoring skill](../../.agents/skills/authoring-ci-workflows/SKILL.md): drafts skip the product matrix, the merge queue takes the full one, forks skip telemetry, a `no-ci` draft still reports its gate, the hourly schedule runs the matrices and skips the PR-only checks, and a superseded run records its gate as `cancelled` rather than `failure`.
A smoke test also feeds every workflow through the built-in scenarios and fails on any condition the evaluator rejects.

Add a row when you add or change a condition.
A row needs three things:

```ts
expectation(backend({ name: 'draft PR', github: pullRequest({ draft: true }) }), {
  runs: ['changes', 'django', 'django_tests'],
  skipped: ['turbo-tests'],
})
```

- `github`: the event, from `pullRequest()`, `mergeQueue()`, `push()`, `schedule()`, or `workflowDispatch()` in `src/scenarios.ts`.
- `steps`: stubbed step outputs by job id and step id (or step name), for the paths filter and selector scripts. `allFiltersChanged(workflow)` stubs every filter as matched; `pathsFilter({ backend: false })` narrows one.
- `runs`, `skipped`, `results`: the jobs to assert on. `results` takes the exact outcome, which is how a gate is checked for `cancelled` on a superseded run.

A cancelled run is modeled as cancelled before any job starts, except the jobs listed in `completedBeforeCancel`, which plan as if the run were live.
That is how the self-cancel in `ci-backend.yml` is tested: `repo-checks` completes with a failing step, the run cancels, and the gate still runs because its OR-ed `deterministic_failure` disjunct is true.

## What it does not model

- Trigger-level `on.<event>.paths`, `branches`, and `types` filters. A scenario assumes the workflow was dispatched.
- Concurrency groups and `cancel-in-progress`.
- Matrix expansion beyond a cell count, which the CLI prints as `0` when a job's matrix resolves to no cells.
- Anything a `run:` body does. Step outputs come only from stubs.
- Reusable-workflow calls are planned as one job. Stub their outputs with `jobOutputs`.
