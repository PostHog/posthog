// These tests check the workflows under .github/workflows, not the planner. A failure here means a
// job condition in a workflow file changed what runs; the planner itself is covered by plan.test.ts.
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import {
    type Outcome,
    type Scenario,
    type StepStub,
    type Workflow,
    formatPlanError,
    loadWorkflow,
    planWorkflow,
    runningJobs,
} from '../src/plan.ts'
import { renderPlanTable } from '../src/render.ts'
import {
    REPO_ROOT,
    allFiltersChanged,
    defaultScenarios,
    mergeQueue,
    pathsFilter,
    pullRequest,
    push,
    schedule,
} from '../src/scenarios.ts'

const WORKFLOWS_DIR = path.join(REPO_ROOT, '.github/workflows')
const workflowFiles = readdirSync(WORKFLOWS_DIR).filter((file) => file.endsWith('.yml') || file.endsWith('.yaml'))
const cache = new Map<string, Workflow>()
const workflow = (file: string): Workflow => {
    const cached = cache.get(file)
    if (cached) {
        return cached
    }
    const loaded = loadWorkflow(path.join(WORKFLOWS_DIR, file))
    cache.set(file, loaded)
    return loaded
}

type Stubs = Record<string, Record<string, StepStub>>

// What the selector scripts emit on a run where every filter matched and one product group was selected.
const backendSelectors: Stubs = {
    'detect-snapshot-mode': { detect: { outputs: { mode: 'normal' } } },
    'turbo-discover': { discover: { outputs: { run_legacy: 'true', matrix: '[{"group":"a"}]' } } },
    'build-product-test-matrix': { build: { outputs: { include: '[{"group":"a"}]' } } },
    build_django_matrix: { build: { outputs: { include: '[{"group":"a"}]' } } },
}
const frontendSelectors: Stubs = {
    'select-jest-tests': {
        classify: { outputs: { mode: 'full', should_run: 'true', matrix: '[{"shard":1}]', shard_count: '1' } },
    },
}

interface Expectation {
    file: string
    scenario: Scenario
    runs?: string[]
    skipped?: string[]
    results?: Record<string, Outcome>
}

type ExpectationBuilder = (
    overrides: Partial<Scenario> & { name: string },
    rest: Omit<Expectation, 'file' | 'scenario'>
) => Expectation

const suite = (file: string, selectors: Stubs): ExpectationBuilder => {
    const filters = allFiltersChanged(workflow(file))
    return (overrides, rest) => ({
        file,
        scenario: { github: pullRequest(), ...overrides, steps: { ...filters, ...selectors, ...overrides.steps } },
        ...rest,
    })
}
const backend = suite('ci-backend.yml', backendSelectors)
const frontend = suite('ci-frontend.yml', frontendSelectors)

const frontendOnlyFilters: Stubs = {
    changes: {
        filter: pathsFilter({
            backend: false,
            migrations: false,
            migrations_any: false,
            migration_replay: false,
            persons_sql: false,
            tasks_temporal: false,
            openapi_types: false,
            product_yamls: false,
        }),
    },
}

const EXPECTATIONS: Expectation[] = [
    backend(
        { name: 'draft PR', github: pullRequest({ draft: true }) },
        {
            runs: [
                'changes',
                'turbo-discover',
                'django',
                'repo-checks',
                'check-migrations',
                'check-openapi-types',
                'django_tests',
            ],
            skipped: ['turbo-tests', 'backend-coverage-report'],
        }
    ),
    backend(
        {
            name: 'draft PR labeled run-ci-backend',
            github: pullRequest({ draft: true, labels: ['run-ci-backend'] }),
        },
        {
            runs: ['turbo-tests', 'django'],
        }
    ),
    backend(
        { name: 'ready PR' },
        {
            runs: ['turbo-tests', 'django', 'backend-coverage-report', 'django_tests'],
        }
    ),
    backend(
        { name: 'merge queue', github: mergeQueue() },
        {
            runs: ['turbo-tests', 'django', 'django_tests'],
            skipped: ['backend-coverage-report'],
        }
    ),
    backend(
        { name: 'draft PR labeled no-ci', github: pullRequest({ draft: true, labels: ['no-ci'] }) },
        {
            runs: ['django_tests'],
            skipped: ['changes', 'django', 'turbo-tests', 'repo-checks', 'check-migrations'],
        }
    ),
    backend(
        { name: 'fork PR', github: pullRequest({ fork: true }) },
        {
            runs: ['changes', 'django', 'django_tests'],
            skipped: ['validate-product-yamls', 'calculate-running-time', 'report-test-timings'],
        }
    ),
    backend(
        { name: 'frontend-only PR', steps: frontendOnlyFilters },
        {
            runs: ['changes', 'django_tests'],
            skipped: ['detect-snapshot-mode', 'turbo-tests', 'django'],
        }
    ),
    backend(
        { name: 'master push', github: push() },
        {
            runs: ['changes', 'repo-checks', 'check-migrations', 'mirror-schema-cache', 'django_tests'],
            skipped: ['detect-snapshot-mode', 'turbo-tests', 'django'],
        }
    ),
    backend(
        { name: 'hourly schedule', github: schedule() },
        {
            runs: ['changes', 'turbo-tests', 'django', 'django_tests'],
            skipped: ['repo-checks', 'check-migrations', 'check-openapi-types', 'mirror-schema-cache'],
        }
    ),
    backend(
        { name: 'ready PR, superseded and cancelled', cancelled: true },
        {
            results: { django_tests: 'cancelled' },
        }
    ),
    backend(
        {
            name: 'ready PR, self-cancelled after a deterministic repo-checks failure',
            cancelled: true,
            completedBeforeCancel: ['changes', 'repo-checks'],
            steps: {
                'repo-checks': {
                    'Run repo invariants (whole-repo pytest guards)': { outcome: 'failure' },
                    'deterministic-failure': { outputs: { deterministic_failure: 'true' } },
                },
            },
        },
        { runs: ['django_tests'], results: { 'repo-checks': 'failure' } }
    ),
    backend(
        {
            name: 'ready PR, cancelled after repo-checks failed during setup',
            cancelled: true,
            completedBeforeCancel: ['changes', 'repo-checks'],
            steps: {
                'repo-checks': {
                    'Set up Python': { outcome: 'failure' },
                    'deterministic-failure': { outputs: { deterministic_failure: 'true' } },
                },
            },
        },
        { results: { 'repo-checks': 'failure', django_tests: 'cancelled' } }
    ),
    frontend(
        { name: 'draft PR', github: pullRequest({ draft: true }) },
        {
            runs: ['changes', 'select-jest-tests', 'jest', 'frontend-typescript-checks', 'frontend_tests'],
        }
    ),
    frontend(
        { name: 'merge queue', github: mergeQueue() },
        {
            runs: ['jest', 'frontend_tests'],
            skipped: ['select-jest-tests'],
        }
    ),
    frontend(
        { name: 'ready PR labeled run-ci-frontend', github: pullRequest({ labels: ['run-ci-frontend'] }) },
        {
            runs: ['jest'],
            skipped: ['select-jest-tests'],
        }
    ),
    frontend(
        { name: 'draft PR labeled no-ci', github: pullRequest({ draft: true, labels: ['no-ci'] }) },
        {
            runs: ['frontend_tests'],
            skipped: ['changes', 'jest', 'frontend-format', 'frontend-typescript-checks'],
        }
    ),
    frontend(
        { name: 'fork PR', github: pullRequest({ fork: true }) },
        {
            runs: ['jest', 'frontend_tests'],
            skipped: ['capture-jest-selection', 'report-test-signals', 'calculate-running-time'],
        }
    ),
    frontend(
        { name: 'master push', github: push() },
        {
            runs: ['frontend-format', 'frontend-typescript-checks', 'frontend_tests'],
            skipped: ['jest', 'select-jest-tests'],
        }
    ),
    frontend(
        { name: 'hourly schedule', github: schedule() },
        {
            runs: ['jest', 'jest-replay-shared', 'frontend_tests'],
            skipped: ['frontend-format', 'frontend-bundle-size', 'frontend-typescript-checks'],
        }
    ),
    frontend(
        { name: 'ready PR, superseded and cancelled', cancelled: true },
        {
            results: { frontend_tests: 'cancelled' },
        }
    ),
]

interface StepExpectation {
    file: string
    job: string
    step: string
    scenario: Scenario
    runs: boolean
}

const STEP_EXPECTATIONS: StepExpectation[] = ['ci-backend.yml', 'ci-frontend.yml'].flatMap((file) => [
    { file, job: 'changes', step: 'filter', scenario: { name: 'ready PR', github: pullRequest() }, runs: true },
    { file, job: 'changes', step: 'filter', scenario: { name: 'master push', github: push() }, runs: false },
    { file, job: 'changes', step: 'filter', scenario: { name: 'hourly schedule', github: schedule() }, runs: false },
    { file, job: 'changes', step: 'app-token', scenario: { name: 'ready PR', github: pullRequest() }, runs: true },
    {
        file,
        job: 'changes',
        step: 'app-token',
        scenario: { name: 'fork PR', github: pullRequest({ fork: true }) },
        runs: false,
    },
])

const planTable = (file: string, selectors: Stubs): string => {
    const wf = workflow(file)
    const scenarioPlans = defaultScenarios(wf, path.join(WORKFLOWS_DIR, file)).map((scenario) => {
        const stubbed = { ...scenario, steps: { ...scenario.steps, ...selectors } }
        return { scenario: stubbed, plan: planWorkflow(wf, stubbed) }
    })
    return renderPlanTable(scenarioPlans)
}

describe('.github/workflows run plans', () => {
    it('ci-backend.yml plans every job under the built-in scenarios as pinned', () => {
        expect(planTable('ci-backend.yml', backendSelectors)).toMatchInlineSnapshot(`
          "job                                     draft ready fork queued merged scheduled dispatched
          changes                                   ▶     ▶    ▶     ▶      ▶        ▶         ▶
          detect-snapshot-mode                      ▶     ▶    ▶     ▶      .        ▶         ▶
          turbo-discover                            ▶     ▶    ▶     ▶      .        ▶         ▶
          build-product-test-matrix                 ▶     ▶    ▶     ▶      .        ▶         ▶
          get_clickhouse_versions                   ▶     ▶    ▶     ▶      .        ▶         ▶
          turbo-tests                               .     ▶    ▶     ▶      .        ▶         ▶
          repo-checks                               ▶     ▶    ▶     ▶      ▶        .         ▶
          cancel-backend-on-repo-check-failure      .     .    .     .      .        .         .
          validate-product-yamls                    ▶     ▶    .     ▶      .        .         .
          check-migrations                          ▶     ▶    ▶     ▶      ▶        .         ▶
          mirror-schema-cache                       .     .    .     .      ▶        .         .
          check-openapi-types                       ▶     ▶    ▶     ▶      ▶        .         ▶
          cancel-backend-on-openapi-check-failure   .     .    .     .      .        .         .
          build_django_matrix                       ▶     ▶    ▶     ▶      .        ▶         ▶
          django                                    ▶     ▶    ▶     ▶      .        ▶         ▶
          handle-snapshots                          .     .    .     .      .        .         .
          django_tests                              ▶     ▶    ▶     ▶      ▶        ▶         ▶
          test-selection-verdict                    ▶     ▶    ▶     ▶      .        .         .
          calculate-running-time                    ▶     ▶    .     ▶      ▶        ▶         ▶
          capture-test-selection                    .     .    .     .      .        .         .
          report-test-timings                       ▶     ▶    .     ▶      .        ▶         ▶
          backend-coverage-report                   .     ▶    .     .      .        .         .

          ▶ = runs   ✗ = fails   ⊘ = cancelled   . = skipped   0 = no matrix expansion"
        `)
    })

    it('ci-frontend.yml plans every job under the built-in scenarios as pinned', () => {
        expect(planTable('ci-frontend.yml', frontendSelectors)).toMatchInlineSnapshot(`
          "job                        draft ready fork queued merged scheduled dispatched
          changes                      ▶     ▶    ▶     ▶      ▶        ▶         ▶
          select-jest-tests            ▶     ▶    ▶     .      .        .         .
          frontend-format              ▶     ▶    ▶     ▶      ▶        .         ▶
          frontend-bundle-size         ▶     ▶    ▶     ▶      ▶        .         ▶
          frontend-typescript-checks   ▶     ▶    ▶     ▶      ▶        .         ▶
          jest                         ▶     ▶    ▶     ▶      .        ▶         ▶
          jest-replay-shared           ▶     ▶    ▶     ▶      ▶        ▶         ▶
          report-test-signals          ▶     ▶    .     ▶      .        ▶         ▶
          frontend_tests               ▶     ▶    ▶     ▶      ▶        ▶         ▶
          calculate-running-time       ▶     ▶    .     ▶      ▶        ▶         ▶
          capture-jest-selection       ▶     ▶    .     ▶      .        .         .

          ▶ = runs   ✗ = fails   ⊘ = cancelled   . = skipped   0 = no matrix expansion"
        `)
    })

    it.each(workflowFiles)('%s evaluates every job and step condition under the built-in scenarios', (file) => {
        const wf = workflow(file)
        const errors = defaultScenarios(wf, path.join(WORKFLOWS_DIR, file)).flatMap((scenario) =>
            planWorkflow(wf, scenario).errors.map((error) => formatPlanError(scenario.name, error))
        )
        expect(errors).toEqual([])
    })

    it.each(EXPECTATIONS)(
        '$file on $scenario.name runs the intended jobs',
        ({ file, scenario, runs, skipped, results }) => {
            const plan = planWorkflow(workflow(file), scenario)
            expect(plan.errors).toEqual([])
            const running = new Set(runningJobs(plan))
            const named = [...(runs ?? []), ...(skipped ?? []), ...Object.keys(results ?? {})]
            expect({
                unknownJobs: named.filter((id) => !(id in plan.jobs)),
                didNotRun: (runs ?? []).filter((id) => !running.has(id)),
                didNotSkip: (skipped ?? []).filter((id) => plan.jobs[id]?.result !== 'skipped'),
                results: Object.fromEntries(Object.keys(results ?? {}).map((id) => [id, plan.jobs[id]?.result])),
            }).toEqual({ unknownJobs: [], didNotRun: [], didNotSkip: [], results: results ?? {} })
        }
    )

    it.each(STEP_EXPECTATIONS)(
        '$file $job/$step on $scenario.name runs=$runs',
        ({ file, job, step, scenario, runs }) => {
            const plan = planWorkflow(workflow(file), scenario)
            const planned = plan.jobs[job]?.steps.find((candidate) => candidate.id === step)
            expect({ id: planned?.id, runs: planned?.runs }).toEqual({ id: step, runs })
        }
    )
})
