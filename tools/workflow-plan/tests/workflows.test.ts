import { readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import {
    type Outcome,
    type Scenario,
    type StepStub,
    type Workflow,
    loadWorkflow,
    planWorkflow,
    runningJobs,
} from '../src/plan.ts'
import {
    allFiltersChanged,
    defaultScenarios,
    mergeQueue,
    pathsFilter,
    pullRequest,
    push,
    schedule,
} from '../src/scenarios.ts'

const WORKFLOWS_DIR = fileURLToPath(new URL('../../../.github/workflows/', import.meta.url))
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

const backend = (overrides: Partial<Scenario> & { name: string }): [string, Scenario] => {
    const wf = workflow('ci-backend.yml')
    return [
        'ci-backend.yml',
        {
            github: pullRequest(),
            ...overrides,
            steps: { ...allFiltersChanged(wf), ...backendSelectors, ...overrides.steps },
        },
    ]
}
const frontend = (overrides: Partial<Scenario> & { name: string }): [string, Scenario] => {
    const wf = workflow('ci-frontend.yml')
    return [
        'ci-frontend.yml',
        {
            github: pullRequest(),
            ...overrides,
            steps: { ...allFiltersChanged(wf), ...frontendSelectors, ...overrides.steps },
        },
    ]
}

interface Expectation {
    file: string
    scenario: Scenario
    runs?: string[]
    skipped?: string[]
    results?: Record<string, Outcome>
}

const expectation = (
    [file, scenario]: [string, Scenario],
    rest: Omit<Expectation, 'file' | 'scenario'>
): Expectation => ({
    file,
    scenario,
    ...rest,
})

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
    expectation(backend({ name: 'draft PR', github: pullRequest({ draft: true }) }), {
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
    }),
    expectation(
        backend({
            name: 'draft PR labeled run-ci-backend',
            github: pullRequest({ draft: true, labels: ['run-ci-backend'] }),
        }),
        {
            runs: ['turbo-tests', 'django'],
        }
    ),
    expectation(backend({ name: 'ready PR' }), {
        runs: ['turbo-tests', 'django', 'backend-coverage-report', 'django_tests'],
    }),
    expectation(backend({ name: 'merge queue', github: mergeQueue() }), {
        runs: ['turbo-tests', 'django', 'django_tests'],
        skipped: ['backend-coverage-report'],
    }),
    expectation(backend({ name: 'draft PR labeled no-ci', github: pullRequest({ draft: true, labels: ['no-ci'] }) }), {
        runs: ['django_tests'],
        skipped: ['changes', 'django', 'turbo-tests', 'repo-checks', 'check-migrations'],
    }),
    expectation(backend({ name: 'fork PR', github: pullRequest({ fork: true }) }), {
        runs: ['changes', 'django', 'django_tests'],
        skipped: ['validate-product-yamls', 'calculate-running-time', 'report-test-timings'],
    }),
    expectation(backend({ name: 'frontend-only PR', steps: frontendOnlyFilters }), {
        runs: ['changes', 'django_tests'],
        skipped: ['detect-snapshot-mode', 'turbo-tests', 'django'],
    }),
    expectation(backend({ name: 'master push', github: push() }), {
        runs: ['changes', 'repo-checks', 'check-migrations', 'mirror-schema-cache', 'django_tests'],
        skipped: ['detect-snapshot-mode', 'turbo-tests', 'django'],
    }),
    expectation(backend({ name: 'hourly schedule', github: schedule() }), {
        runs: ['changes', 'turbo-tests', 'django', 'django_tests'],
        skipped: ['repo-checks', 'check-migrations', 'check-openapi-types', 'mirror-schema-cache'],
    }),
    expectation(backend({ name: 'ready PR, superseded and cancelled', cancelled: true }), {
        results: { django_tests: 'cancelled' },
    }),
    expectation(
        backend({
            name: 'ready PR, self-cancelled after a deterministic repo-checks failure',
            cancelled: true,
            completedBeforeCancel: ['changes', 'repo-checks'],
            steps: {
                'repo-checks': {
                    'Run repo invariants (whole-repo pytest guards)': { outcome: 'failure' },
                    'deterministic-failure': { outputs: { deterministic_failure: 'true' } },
                },
            },
        }),
        { runs: ['django_tests'], results: { 'repo-checks': 'failure' } }
    ),
    expectation(
        backend({
            name: 'ready PR, cancelled after repo-checks failed during setup',
            cancelled: true,
            completedBeforeCancel: ['changes', 'repo-checks'],
            steps: {
                'repo-checks': {
                    'Set up Python': { outcome: 'failure' },
                    'deterministic-failure': { outputs: { deterministic_failure: 'true' } },
                },
            },
        }),
        { results: { 'repo-checks': 'failure', django_tests: 'cancelled' } }
    ),
    expectation(frontend({ name: 'draft PR', github: pullRequest({ draft: true }) }), {
        runs: ['changes', 'select-jest-tests', 'jest', 'frontend-typescript-checks', 'frontend_tests'],
    }),
    expectation(frontend({ name: 'merge queue', github: mergeQueue() }), {
        runs: ['jest', 'frontend_tests'],
        skipped: ['select-jest-tests'],
    }),
    expectation(
        frontend({ name: 'ready PR labeled run-ci-frontend', github: pullRequest({ labels: ['run-ci-frontend'] }) }),
        {
            runs: ['jest'],
            skipped: ['select-jest-tests'],
        }
    ),
    expectation(frontend({ name: 'draft PR labeled no-ci', github: pullRequest({ draft: true, labels: ['no-ci'] }) }), {
        runs: ['frontend_tests'],
        skipped: ['changes', 'jest', 'frontend-format', 'frontend-typescript-checks'],
    }),
    expectation(frontend({ name: 'fork PR', github: pullRequest({ fork: true }) }), {
        runs: ['jest', 'frontend_tests'],
        skipped: ['capture-jest-selection', 'report-test-signals', 'calculate-running-time'],
    }),
    expectation(frontend({ name: 'master push', github: push() }), {
        runs: ['frontend-format', 'frontend-typescript-checks', 'frontend_tests'],
        skipped: ['jest', 'select-jest-tests'],
    }),
    expectation(frontend({ name: 'hourly schedule', github: schedule() }), {
        runs: ['jest', 'jest-replay-shared', 'frontend_tests'],
        skipped: ['frontend-format', 'frontend-bundle-size', 'frontend-typescript-checks'],
    }),
    expectation(frontend({ name: 'ready PR, superseded and cancelled', cancelled: true }), {
        results: { frontend_tests: 'cancelled' },
    }),
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

// Job outputs a script produces at runtime, where a condition cannot even be evaluated without them.
const SCRIPT_OUTPUTS: Record<string, Record<string, Record<string, string>>> = {
    'release.yml': {
        plan: {
            val: JSON.stringify({ ci: { github: { artifacts_matrix: { include: null }, pr_run_mode: 'upload' } } }),
        },
    },
}

describe('.github/workflows run plans', () => {
    it.each(workflowFiles)('%s evaluates every job and step condition under the built-in scenarios', (file) => {
        const wf = workflow(file)
        const errors = defaultScenarios(wf).flatMap(({ name, ...scenario }) =>
            planWorkflow(wf, { name, ...scenario, jobOutputs: SCRIPT_OUTPUTS[file] ?? {} })
                .errors.filter((error) => error.where !== 'matrix')
                .map(
                    (error) =>
                        `${name}: ${error.job}${error.step ? `/${error.step}` : ''} ${error.where}: ${error.message}`
                )
        )
        expect(errors).toEqual([])
    })

    it.each(EXPECTATIONS)(
        '$file on $scenario.name runs the intended jobs',
        ({ file, scenario, runs, skipped, results }) => {
            const plan = planWorkflow(workflow(file), scenario)
            expect(plan.errors.filter((error) => error.where !== 'matrix')).toEqual([])
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
