# workflow-plan

Evaluates the `if:` conditions in `.github/workflows/*.yml` the way GitHub does, against synthetic PR, push, schedule, and cancellation scenarios, and reports which jobs and steps run.
The evaluator is GitHub's own [`@actions/expressions`](https://www.npmjs.com/package/@actions/expressions), so operator precedence, coercion, `contains`, `fromJSON`, and the `labels.*.name` filter syntax behave as they do in Actions.

## See a workflow's run plan

```bash
hogli ci:plan .github/workflows/ci-backend.yml
hogli ci:plan .github/workflows/ci-backend.yml --steps changes
```

The table has one row per job and one column per built-in scenario: `draft`, `ready`, and `fork` pull requests, a `queued` merge-queue run, a `merged` push to master, a `scheduled` run, and a `dispatched` run.
A cell reads `▶` for a job that runs, `✗` for one that fails, `⊘` for one that is cancelled, and `.` for a skipped job; a trailing `0` marks a matrix that expands to no cells. A legend under the table repeats this.
In a terminal the header row is bold and every second row has a shaded background; set `NO_COLOR` to turn that off.
Every paths filter is stubbed as if all of its filters matched.
Outputs that scripts produce at runtime are empty, so a job gated on `needs.x.outputs.matrix != ''` shows as skipped until a scenario stubs that output, and a matrix built from such an output has no cell count.
The Depot shadow in `.depot/workflows/` is planned as sampled in: every scenario sets `vars.CI_DEPOT_SHADOW_PERCENT` and stubs the `sample` job's `sampled` output to `true`, so the table shows the gates behind the sampling roll.

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
