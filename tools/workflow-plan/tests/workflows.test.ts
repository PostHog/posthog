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
import {
    REPO_ROOT,
    SCRIPT_STUBS,
    allFiltersChanged,
    defaultScenarios,
    mergeQueue,
    pathsFilter,
    pullRequest,
    push,
    schedule,
    workflowDispatch,
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
    'turbo-discover': { discover: { outputs: { run_legacy: 'true', matrix: '[{"group":"a"}]', mode: 'full' } } },
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

const suite = (file: string, selectors: Stubs = {}): ExpectationBuilder => {
    const filters = allFiltersChanged(workflow(file))
    const scripted = SCRIPT_STUBS[`.github/workflows/${file}`]
    return (overrides, rest) => ({
        file,
        scenario: {
            github: pullRequest(),
            ...scripted,
            ...overrides,
            steps: { ...filters, ...selectors, ...overrides.steps },
        },
        ...rest,
    })
}
const backend = suite('ci-backend.yml', backendSelectors)
const frontend = suite('ci-frontend.yml', frontendSelectors)
const deltalite = suite('build-deltalite.yml')
const PINNED_WORKFLOWS = ['ci-backend.yml', 'ci-frontend.yml']

interface ReleaseWorkflow {
    file: string
    // The job that decides whether the version needs a release, plus the step and output carrying
    // that verdict. Naming them rather than deriving them keeps a renamed job a test failure.
    check: string
    step: string
    output: string
    build: string
    publish: string
}

// The two PyPI parsers share a job layout; the npm one names everything differently.
const PYPI_PARSER_JOBS = {
    check: 'check-version',
    step: 'version',
    output: 'parser-release-needed',
    build: 'build-wheels',
    publish: 'publish',
} as const

const RELEASE_WORKFLOWS: ReleaseWorkflow[] = [
    { file: 'build-hogql-parser.yml', ...PYPI_PARSER_JOBS },
    { file: 'build-hogql-parser-rs.yml', ...PYPI_PARSER_JOBS },
    {
        file: 'build-hogql-parser-npm.yml',
        check: 'check-package-version',
        step: 'check-package-version',
        output: 'is-new-version',
        build: 'build-wasm',
        publish: 'publish-npm',
    },
]

// A release workflow builds its artifacts on a pull request as a check. Only a manual dispatch
// from master reaches the job that uploads to a registry. The version verdict is stubbed true,
// so the publish job is held back by the event and the ref alone.
const releaseExpectations = ({ file, check, step, output, build, publish }: ReleaseWorkflow): Expectation[] => {
    const release = suite(file, { [check]: { [step]: { outputs: { [output]: 'true' } } } })
    return [
        release({ name: 'ready PR' }, { runs: [check, build], skipped: [publish] }),
        release({ name: 'fork PR', github: pullRequest({ fork: true }) }, { runs: [check], skipped: [build, publish] }),
        release({ name: 'master dispatch', github: workflowDispatch() }, { runs: [check, build, publish] }),
        release(
            { name: 'branch dispatch', github: workflowDispatch('feat/example') },
            { runs: [check, build], skipped: [publish] }
        ),
    ]
}

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
            runs: [
                'dynamic-ci-filter',
                'turbo-tests',
                'django',
                'backend-coverage-report',
                'django_tests',
                'get_clickhouse_versions',
                'build-product-test-matrix',
                'build_django_matrix',
                'test-selection-verdict',
                'capture-test-selection',
            ],
            skipped: ['handle-snapshots', 'cancel-backend-on-openapi-check-failure', 'hand-off-to-depot'],
        }
    ),
    // Handed off to Depot: it runs the tests and the side effects, GitHub Actions relays the
    // verdict. Every heavy job and every side effect here stands down, and the required gate
    // keeps reporting.
    backend(
        {
            name: 'ready PR handed off to Depot',
            steps: { changes: { route: { outputs: { engine: 'depot' } } } },
        },
        {
            runs: ['changes', 'hand-off-to-depot', 'django_tests'],
            skipped: [
                'detect-snapshot-mode',
                'turbo-discover',
                'repo-checks',
                'validate-product-yamls',
                'check-migrations',
                'check-openapi-types',
                'get_clickhouse_versions',
                'build_django_matrix',
                'build-product-test-matrix',
                'django',
                'turbo-tests',
                'handle-snapshots',
                'test-selection-verdict',
                'capture-test-selection',
                'report-test-timings',
                'calculate-running-time',
                'backend-coverage-report',
                'cancel-backend-on-repo-check-failure',
                'cancel-backend-on-openapi-check-failure',
            ],
        }
    ),
    backend(
        { name: 'merge queue', github: mergeQueue() },
        {
            runs: ['turbo-tests', 'django', 'django_tests'],
            skipped: ['backend-coverage-report', 'dynamic-ci-filter'],
        }
    ),
    backend(
        { name: 'draft PR labeled no-ci', github: pullRequest({ draft: true, labels: ['no-ci'] }) },
        {
            runs: ['django_tests'],
            skipped: ['changes', 'django', 'turbo-tests', 'repo-checks', 'check-migrations', 'dynamic-ci-filter'],
        }
    ),
    backend(
        { name: 'fork PR', github: pullRequest({ fork: true }) },
        {
            runs: ['changes', 'django', 'django_tests'],
            skipped: [
                'dynamic-ci-filter',
                'validate-product-yamls',
                'calculate-running-time',
                'report-test-timings',
                'capture-test-selection',
                'handle-snapshots',
            ],
        }
    ),
    backend(
        { name: 'frontend-only PR', steps: frontendOnlyFilters },
        {
            runs: ['changes', 'django_tests'],
            skipped: [
                'detect-snapshot-mode',
                'turbo-tests',
                'django',
                'get_clickhouse_versions',
                'build_django_matrix',
            ],
        }
    ),
    backend(
        { name: 'master push', github: push() },
        {
            runs: ['changes', 'repo-checks', 'check-migrations', 'mirror-schema-cache', 'django_tests'],
            skipped: [
                'dynamic-ci-filter',
                'detect-snapshot-mode',
                'turbo-tests',
                'django',
                'get_clickhouse_versions',
                'build-product-test-matrix',
                'build_django_matrix',
                'test-selection-verdict',
            ],
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
        {
            runs: ['django_tests', 'cancel-backend-on-repo-check-failure'],
            results: { 'repo-checks': 'failure' },
        }
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
            runs: [
                'changes',
                'dynamic-ci-filter',
                'select-jest-tests',
                'jest',
                'frontend-typescript-checks',
                'frontend_tests',
            ],
        }
    ),
    frontend(
        { name: 'merge queue', github: mergeQueue() },
        {
            runs: ['jest', 'frontend_tests'],
            skipped: ['select-jest-tests', 'dynamic-ci-filter'],
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
            skipped: ['changes', 'jest', 'frontend-format', 'frontend-typescript-checks', 'dynamic-ci-filter'],
        }
    ),
    frontend(
        { name: 'fork PR', github: pullRequest({ fork: true }) },
        {
            runs: ['jest', 'frontend_tests'],
            skipped: ['dynamic-ci-filter', 'capture-jest-selection', 'report-test-signals', 'calculate-running-time'],
        }
    ),
    frontend(
        { name: 'master push', github: push() },
        {
            runs: ['frontend-format', 'frontend-typescript-checks', 'frontend_tests'],
            skipped: ['jest', 'select-jest-tests', 'dynamic-ci-filter'],
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
    ...RELEASE_WORKFLOWS.flatMap(releaseExpectations),
    deltalite({ name: 'ready PR' }, { runs: ['check-version', 'build-wheels'], skipped: ['publish'] }),
    deltalite(
        { name: 'fork PR', github: pullRequest({ fork: true }) },
        { runs: ['check-version'], skipped: ['build-wheels', 'publish'] }
    ),
    deltalite(
        { name: 'master dispatch', github: workflowDispatch() },
        { runs: ['check-version', 'build-wheels', 'publish'] }
    ),
    deltalite(
        { name: 'branch dispatch', github: workflowDispatch('feat/example') },
        { runs: ['check-version', 'build-wheels'], skipped: ['publish'] }
    ),
]

interface StepExpectation {
    file: string
    job: string
    step: string
    scenario: Scenario
    runs: boolean
}

const STEP_EXPECTATIONS: StepExpectation[] = PINNED_WORKFLOWS.flatMap((file) => [
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

const namedJobs = (file: string): Set<string> =>
    new Set(
        EXPECTATIONS.filter((expectation) => expectation.file === file).flatMap((expectation) => [
            ...(expectation.runs ?? []),
            ...(expectation.skipped ?? []),
            ...Object.keys(expectation.results ?? {}),
        ])
    )

describe('.github/workflows run plans', () => {
    it('Phrocs executes tests even when setup-go restores a warm build cache', () => {
        const testStep = workflow('ci-phrocs.yml').jobs.test.steps?.find((step) => step.name === 'Run tests')
        expect(testStep?.run).toMatch(/\bgo test\s+-count=1\b/)
    })

    it.each([
        ['master schedule', schedule(), 'success', true],
        ['same-repo PR', pullRequest(), 'success', false],
        ['fork PR', pullRequest({ fork: true }), 'success', false],
        ['failed master typecheck', schedule(), 'failure', false],
    ] as const)('mypy cache writer on %s', (_name, github, outcome, runs) => {
        const wf = workflow('ci-python.yml')
        const plan = planWorkflow(wf, {
            name: _name,
            github,
            steps: {
                ...allFiltersChanged(wf),
                'code-quality': { 'Check static typing': { outcome } },
            },
        })
        expect(plan.errors).toEqual([])
        expect(plan.jobs['code-quality'].steps.find((step) => step.name === 'Save mypy cache')?.runs).toBe(runs)
    })

    it.each(['success', 'failure'] as const)(
        'sccache counters survive a %s build without changing its verdict',
        (outcome) => {
            const wf = workflow('ci-rust.yml')
            const plan = planWorkflow(wf, {
                name: outcome,
                github: pullRequest(),
                steps: {
                    ...allFiltersChanged(wf),
                    affected: { shards: { outputs: { matrix: '{"include":[{"packages":"common-types"}]}' } } },
                    build: {
                        'Run cargo build': { outcome },
                        'Report sccache counters': { outcome: 'failure' },
                    },
                },
            })
            expect(plan.errors).toEqual([])
            expect(plan.jobs.build.steps.find((step) => step.name === 'Report sccache counters')?.runs).toBe(true)
            expect(plan.jobs.build.result).toBe(outcome)
        }
    )

    it.each(PINNED_WORKFLOWS)('%s names every conditional job in an expectation row', (file) => {
        const unnamed = Object.entries(workflow(file).jobs)
            .filter(([id, job]) => job.if !== undefined && !namedJobs(file).has(id))
            .map(([id]) => id)
        expect(unnamed).toEqual([])
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
