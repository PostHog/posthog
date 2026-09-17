// These tests check the workflows under .github/workflows, not the planner. A failure here means a
// job condition in a workflow file changed what runs; the planner itself is covered by plan.test.ts.
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { evaluateTemplate } from '../src/expressions.ts'
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
const PINNED_WORKFLOWS = ['ci-backend.yml', 'ci-frontend.yml']

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

const PACKAGE_RELEASES = [
    {
        file: 'build-hogql-parser-npm.yml',
        check: 'check-package-version',
        step: 'check-package-version',
        output: 'is-new-version',
        build: 'build-wasm',
        publish: 'publish-npm',
    },
    {
        file: 'build-hogql-parser.yml',
        check: 'check-version',
        step: 'version',
        output: 'parser-release-needed',
        build: 'build-wheels',
        publish: 'publish',
    },
    {
        file: 'build-hogql-parser-rs.yml',
        check: 'check-version',
        step: 'version',
        output: 'parser-release-needed',
        build: 'build-wheels',
        publish: 'publish',
    },
    {
        file: 'build-deltalite.yml',
        check: 'check-version',
        step: 'version',
        output: 'deltalite-release-needed',
        build: 'build-wheels',
        publish: 'publish',
    },
    {
        file: 'ci-hog.yml',
        check: 'hog-tests',
        step: 'check-package-version',
        output: 'is-new-version',
        build: 'hog-tests',
        publish: 'release-hogvm',
    },
]

const packageReleaseExpectations: Expectation[] = PACKAGE_RELEASES.flatMap(
    ({ file, check, step, output, build, publish }) => {
        const release = suite(file, { [check]: { [step]: { outputs: { [output]: 'true' } } } })
        const publishing = ['notify-approval-needed', publish]
        return [
            ...[
                { name: 'same-repo PR with new package version', github: pullRequest() },
                { name: 'fork PR with new package version', github: pullRequest({ fork: true }) },
                { name: 'merge queue with new package version', github: mergeQueue() },
            ].map((scenario) => release(scenario, { runs: [build], skipped: publishing })),
            ...[
                { name: 'non-master push', github: { ...push(), ref: 'refs/heads/feature' } },
                { name: 'tag push', github: { ...push(), ref: 'refs/tags/v1.0.0' } },
                { name: 'manual run', github: workflowDispatch() },
                { name: 'fork repository master push', github: { ...push(), repository: 'octocat/posthog' } },
            ].map((scenario) => release(scenario, { skipped: publishing })),
            release({ name: 'master push with new package version', github: push() }, { runs: [build, ...publishing] }),
            release(
                {
                    name: 'master push with published version',
                    github: push(),
                    steps: { [check]: { [step]: { outputs: { [output]: 'false' } } } },
                },
                { skipped: publishing }
            ),
            release(
                {
                    name: 'master push with failed build',
                    github: push(),
                    steps: {
                        [build]: {
                            'Upload artifact': { outcome: 'failure' },
                            'Upload wheels artifact': { outcome: 'failure' },
                            'Upload dist artifact': { outcome: 'failure' },
                            'Run Hog tests': { outcome: 'failure' },
                        },
                    },
                },
                { skipped: publishing }
            ),
        ]
    }
)

const EXPECTATIONS: Expectation[] = [
    ...packageReleaseExpectations,
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
            skipped: ['handle-snapshots', 'cancel-backend-on-openapi-check-failure'],
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
            skipped: [
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
    it('lets master Hog CI runs proceed while serializing HogVM publishing', () => {
        const wf = workflow('ci-hog.yml') as Workflow & { concurrency: { group: string } }
        const publish = wf.jobs['release-hogvm'] as { concurrency?: { group: string } }
        const first = { ...push(), sha: 'a'.repeat(40) }
        const second = { ...push(), sha: 'b'.repeat(40) }
        const group = (expression: unknown, github: Scenario['github']): string =>
            evaluateTemplate(expression, { github }, new Map())

        expect(group(wf.concurrency.group, first)).not.toBe(group(wf.concurrency.group, second))
        expect(publish.concurrency?.group).toBeTruthy()
        expect(group(publish.concurrency?.group, first)).toBe(group(publish.concurrency?.group, second))
        expect(group(wf.concurrency.group, { ...pullRequest(), sha: first.sha })).toBe(
            group(wf.concurrency.group, { ...pullRequest(), sha: second.sha })
        )
    })

    it.each(['true', 'false'])(
        'HogVM publishes only if the approved version is still unpublished (%s)',
        (isNewVersion) => {
            const wf = workflow('ci-hog.yml')
            const plan = planWorkflow(wf, {
                name: 'master push after approval',
                github: push(),
                steps: {
                    ...allFiltersChanged(wf),
                    'hog-tests': { 'check-package-version': { outputs: { 'is-new-version': 'true' } } },
                    'release-hogvm': { 'recheck-package-version': { outputs: { 'is-new-version': isNewVersion } } },
                },
            })
            expect(plan.errors).toEqual([])
            expect(
                plan.jobs['release-hogvm']?.steps.find(
                    (step) => step.name === 'Publish the package in the npm registry'
                )?.runs
            ).toBe(isNewVersion === 'true')
        }
    )

    it.each(PACKAGE_RELEASES)('$file requires release approval for registry authentication', ({ file, publish }) => {
        expect(workflow(file).jobs[publish]).toMatchObject({
            environment: 'Release SDK',
            permissions: { 'id-token': 'write' },
        })
        expect(workflow(file).on).toMatchObject({ push: { branches: ['master'] } })
    })

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
