// These tests check the CI workflows, not the planner. A failure here means a
// job condition in a workflow file changed what runs; the planner itself is covered by plan.test.ts.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { evaluateValue, planFunctions } from '../src/expressions.ts'
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
// A bare file name lives under .github/workflows; a repo-relative path names a Depot CI workflow.
const workflowKey = (file: string): string => (file.includes('/') ? file : `.github/workflows/${file}`)
const cache = new Map<string, Workflow>()
const workflow = (file: string): Workflow => {
    const cached = cache.get(file)
    if (cached) {
        return cached
    }
    const loaded = loadWorkflow(path.join(REPO_ROOT, workflowKey(file)))
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
    const scripted = SCRIPT_STUBS[workflowKey(file)]
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
const DEPOT_BACKEND = '.depot/workflows/ci-backend.yml'
const depotBackend = suite(DEPOT_BACKEND, backendSelectors)
const frontend = suite('ci-frontend.yml', frontendSelectors)
const deltalite = suite('build-deltalite.yml')
const PINNED_WORKFLOWS = [DEPOT_BACKEND, 'ci-frontend.yml']

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
            sdk_manifests: false,
        }),
    },
}

const allJobsExcept = (file: string, kept: string[]): string[] =>
    Object.keys(workflow(file).jobs).filter((id) => !kept.includes(id))

const EXPECTATIONS: Expectation[] = [
    // The master push runs on Depot CI: the per-commit checks and the schema dump, no matrices.
    depotBackend(
        { name: 'master push', github: push() },
        {
            runs: [
                'changes',
                'repo-checks',
                'sdk-major-guard',
                'check-migrations',
                'check-openapi-types',
                'django_tests',
            ],
            skipped: [
                'cancel-superseded-runs',
                'detect-snapshot-mode',
                'turbo-discover',
                'prime-schema-cache',
                'turbo-tests',
                'django',
                'get_clickhouse_versions',
                'build-product-test-matrix',
                'build_django_matrix',
                'test-selection-verdict',
            ],
        }
    ),
    depotBackend(
        { name: 'ready PR, superseded and cancelled', cancelled: true },
        { results: { django_tests: 'cancelled' } }
    ),
    depotBackend(
        { name: 'draft PR', github: pullRequest({ draft: true }) },
        {
            runs: [
                'changes',
                'turbo-discover',
                'django',
                'repo-checks',
                'sdk-major-guard',
                'check-migrations',
                'check-openapi-types',
                'django_tests',
            ],
            skipped: ['turbo-tests', 'backend-coverage-report'],
        }
    ),
    depotBackend(
        {
            name: 'draft PR labeled run-ci-backend',
            github: pullRequest({ draft: true, labels: ['run-ci-backend'] }),
        },
        {
            runs: ['turbo-tests', 'django'],
        }
    ),
    depotBackend(
        { name: 'ready PR' },
        {
            runs: [
                'cancel-superseded-runs',
                'turbo-tests',
                'django',
                'backend-coverage-report',
                'django_tests',
                'get_clickhouse_versions',
                'build-product-test-matrix',
                'build_django_matrix',
                'prime-schema-cache',
                'test-selection-verdict',
                'capture-test-selection',
            ],
            skipped: ['handle-snapshots', 'cancel-backend-on-openapi-check-failure'],
        }
    ),
    depotBackend(
        { name: 'merge queue', github: mergeQueue() },
        {
            runs: ['turbo-tests', 'django', 'django_tests'],
            skipped: ['backend-coverage-report'],
        }
    ),
    // A product change that reaches no legacy code skips the Django suite, but the events_json
    // rows still run the changed products' listed paths, because product jobs read the legacy
    // events table only.
    depotBackend(
        {
            name: 'product-only PR whose products have events_json paths',
            steps: {
                changes: { filter: pathsFilter({ backend: true, legacy: false }) },
                'turbo-discover': {
                    discover: {
                        outputs: {
                            run_legacy: 'false',
                            matrix: '[{"group":"a"}]',
                            mode: '',
                            selection: '{"json_targets_files":"products/web_analytics/backend/hogql_queries"}',
                        },
                    },
                },
            },
        },
        { runs: ['turbo-tests', 'django', 'django_tests'] }
    ),
    depotBackend(
        {
            name: 'product-only PR without events_json paths',
            steps: {
                changes: { filter: pathsFilter({ backend: true, legacy: false }) },
                'turbo-discover': {
                    discover: {
                        outputs: {
                            run_legacy: 'false',
                            matrix: '[{"group":"a"}]',
                            mode: '',
                            selection: '{"json_targets_files":""}',
                        },
                    },
                },
            },
        },
        { runs: ['turbo-tests', 'django_tests'], skipped: ['django'] }
    ),
    depotBackend(
        { name: 'draft PR labeled no-ci', github: pullRequest({ draft: true, labels: ['no-ci'] }) },
        {
            runs: ['cancel-superseded-runs', 'django_tests'],
            skipped: ['changes', 'django', 'turbo-tests', 'repo-checks', 'sdk-major-guard', 'check-migrations'],
        }
    ),
    // Depot CI never runs a fork's code. Only the gate runs, and it fails closed.
    depotBackend(
        { name: 'fork PR', github: pullRequest({ fork: true }) },
        { runs: ['django_tests'], skipped: allJobsExcept(DEPOT_BACKEND, ['django_tests']) }
    ),
    depotBackend(
        { name: 'frontend-only PR', steps: frontendOnlyFilters },
        {
            runs: ['changes', 'django_tests'],
            skipped: [
                'detect-snapshot-mode',
                'turbo-tests',
                'django',
                'get_clickhouse_versions',
                'build_django_matrix',
                'sdk-major-guard',
            ],
        }
    ),
    depotBackend(
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
    depotBackend(
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

const E2E_DISPATCH: Scenario = {
    name: 'manual dispatch',
    github: workflowDispatch('feat/example'),
    steps: {
        changes: {
            decide: { outputs: { shouldRun: 'true' } },
            'schema-key': { outputs: { migrations_key: 'posthog-schema-mig-test' } },
        },
    },
}

const mirrorPullRequest = (): Scenario['github'] =>
    JSON.parse(JSON.stringify(pullRequest()).replaceAll('PostHog/posthog', 'PostHog/example'))

const pathsFilterJobs = workflowFiles.flatMap((file) =>
    Object.entries(workflow(file).jobs).flatMap(([job, definition]) =>
        definition.steps?.some(
            (step) =>
                step.id === 'app-token' &&
                String(step.with?.['client-id']).includes('GH_APP_POSTHOG_PATHS_FILTER_APP_ID')
        )
            ? [{ file, job }]
            : []
    )
)

const STEP_EXPECTATIONS: StepExpectation[] = [
    ...pathsFilterJobs.flatMap(({ file, job }) => [
        {
            file,
            job,
            step: 'app-token',
            scenario: { name: 'canonical PR token', github: pullRequest() },
            runs: true,
        },
        {
            file,
            job,
            step: 'app-token',
            scenario: { name: 'mirror PR token', github: mirrorPullRequest() },
            runs: false,
        },
        {
            file,
            job,
            step: 'app-token',
            scenario: { name: 'fork PR token', github: pullRequest({ fork: true }) },
            runs: false,
        },
    ]),
    ...[
        { name: 'known fallback', selective: '', changedFiles: '', fork: false },
        { name: 'empty source selection', selective: 'true', changedFiles: '', fork: false },
        { name: 'selective PR', selective: 'true', changedFiles: 'src/example.ts', fork: false },
        { name: 'selective fork PR', selective: 'true', changedFiles: 'src/example.ts', fork: true },
    ].flatMap(({ name, selective, changedFiles, fork }) =>
        ['setup-gh-token', 'selector-install'].map((step) => ({
            file: 'ci-frontend.yml',
            job: 'select-jest-tests',
            step,
            scenario: {
                name,
                github: pullRequest({ fork }),
                steps: {
                    ...allFiltersChanged(workflow('ci-frontend.yml')),
                    'select-jest-tests': { prepare: { outputs: { selective, changed_files: changedFiles } } },
                },
            },
            runs: selective === 'true' && changedFiles !== '' && (step === 'selector-install' || !fork),
        }))
    ),
    {
        file: 'ci-frontend.yml',
        job: 'changes',
        step: 'filter',
        scenario: { name: 'hourly schedule', github: schedule() },
        runs: false,
    },
    ...PINNED_WORKFLOWS.flatMap((file) => [
        {
            file,
            job: 'changes',
            step: 'filter',
            scenario: { name: 'ready PR', github: pullRequest() },
            runs: true,
        },
        { file, job: 'changes', step: 'filter', scenario: { name: 'master push', github: push() }, runs: false },
        {
            file,
            job: 'changes',
            step: 'app-token',
            scenario: { name: 'ready PR', github: pullRequest() },
            runs: true,
        },
        {
            file,
            job: 'changes',
            step: 'app-token',
            scenario: { name: 'fork PR', github: pullRequest({ fork: true }) },
            runs: false,
        },
    ]),
    { file: 'ci-e2e-playwright.yml', job: 'changes', step: 'schema-key', scenario: E2E_DISPATCH, runs: true },
    { file: 'ci-e2e-playwright.yml', job: 'playwright', step: 'schema-cache', scenario: E2E_DISPATCH, runs: true },
]

const namedJobs = (file: string): Set<string> =>
    new Set(
        EXPECTATIONS.filter((expectation) => expectation.file === file).flatMap((expectation) => [
            ...(expectation.runs ?? []),
            ...(expectation.skipped ?? []),
            ...Object.keys(expectation.results ?? {}),
        ])
    )

describe('CI workflow run plans', () => {
    it.each([
        { name: 'canonical PR', github: pullRequest(), runs: true },
        { name: 'mirror PR', github: mirrorPullRequest(), runs: false },
        { name: 'fork PR', github: pullRequest({ fork: true }), runs: false },
    ])('bot comment resolver on $name runs=$runs', ({ name, github, runs }) => {
        const plan = planWorkflow(workflow('pr-resolve-outdated-bot-comments.yml'), { name, github })
        expect(runningJobs(plan).includes('resolve-outdated')).toBe(runs)
    })

    it.each(pathsFilterJobs)('$file $job can read changed files without the App token', ({ file, job }) => {
        const wf = workflow(file)
        const definition = wf.jobs[job]!
        const tokens = definition
            .steps!.map((step) => step.with?.token ?? step.with?.['github-token'] ?? step.env?.GH_TOKEN)
            .filter((token) => String(token).includes('steps.app-token.outputs.token'))
        expect(tokens.length).toBeGreaterThan(0)
        for (const token of tokens) {
            expect(
                evaluateValue(
                    token,
                    { github: mirrorPullRequest(), steps: { 'app-token': { outputs: { token: '' } } } },
                    planFunctions({ dependenciesSucceeded: true, dependenciesFailed: false, cancelled: false })
                )
            ).toBe('stub-token')
        }
    })

    it.each([
        ['failed install', 'failure', 'src/example.ts', 'full'],
        ['empty source selection', 'skipped', '', 'selective'],
        ['successful install', 'success', 'src/example.ts', 'selective'],
    ])('Jest selection after %s', (_name, installOutcome, changedFiles, mode) => {
        const script = workflow('ci-frontend.yml').jobs['select-jest-tests']?.steps?.find(
            (step) => step.id === 'classify'
        )?.run
        if (!script) {
            throw new Error('Missing Jest matrix classification script')
        }
        const directory = mkdtempSync(path.join(os.tmpdir(), 'jest-selection-'))
        const output = path.join(directory, 'output')
        const fallback = path.join(directory, 'fallback')
        try {
            writeFileSync(fallback, 'mode=full\nshould_run=true\n')
            const result = spawnSync(
                'bash',
                [
                    '-e',
                    '-c',
                    `node() { printf 'mode=selective\\nshould_run=false\\n' >> "$GITHUB_OUTPUT"; }\n${script.replaceAll('/tmp/jest-selection-fallback', fallback)}`,
                ],
                {
                    encoding: 'utf8',
                    env: {
                        PATH: process.env.PATH,
                        SELECTIVE: 'true',
                        INSTALL_OUTCOME: installOutcome,
                        CHANGED_FILES: changedFiles,
                        GITHUB_OUTPUT: output,
                    },
                }
            )
            expect({ status: result.status, stderr: result.stderr }).toEqual({ status: 0, stderr: '' })
            expect(readFileSync(output, 'utf8')).toBe(`mode=${mode}\nshould_run=${mode === 'full'}\n`)
        } finally {
            rmSync(directory, { recursive: true, force: true })
        }
    })

    it.each([
        ['new bump', workflowDispatch(), 'bump', 'success', 'pass', true, false],
        ['missing image', workflowDispatch(), 'bump', 'failure', 'pass', false, false],
        ['failed gateway', workflowDispatch(), 'bump', 'success', 'broken', false, false],
        ['nightly with open PR', schedule(), 'current', 'success', 'pass', false, true],
    ] as const)('sandbox agent release: %s', (name, github, action, imageOutcome, result, enqueue, nightly) => {
        const plan = planWorkflow(workflow('update-sandbox-agent-version.yml'), {
            name,
            github,
            steps: {
                'update-sandbox-agent-version': {
                    state: { outputs: { action } },
                    smoke: { outputs: { conclusion: 'success' } },
                    image: { outcome: imageOutcome },
                    'gateway-smoke': { outputs: { result } },
                    'Stop when the gateway smoke did not pass': { outcome: 'failure' },
                    'nightly-smoke': { outputs: { result: 'pass' } },
                },
            },
        })
        expect(plan.errors).toEqual([])
        const steps = plan.jobs['update-sandbox-agent-version']?.steps ?? []
        expect(steps.find((step) => step.id === 'commit')?.runs).toBe(action === 'bump')
        expect(steps.find((step) => step.id === 'enqueue')?.runs).toBe(enqueue)
        expect(steps.find((step) => step.id === 'nightly-smoke')?.runs).toBe(nightly)
    })

    it('Phrocs executes tests even when setup-go restores a warm build cache', () => {
        const testStep = workflow('ci-phrocs.yml').jobs.test?.steps?.find((step) => step.name === 'Run tests')
        expect(testStep?.run).toMatch(/\bgo test\s+-count=1\b/)
    })

    it('Backend CI runs once every hour', () => {
        const crons = (file: string): string[] =>
            ((loadWorkflow(path.join(REPO_ROOT, file)).on as { schedule?: { cron: string }[] }).schedule ?? []).map(
                (entry) => entry.cron
            )

        expect(crons('.depot/workflows/ci-backend.yml')).toEqual([
            '23 */3 * * *',
            '23 1,2,4,5,7,8,10,11,13,14,16,17,19,20,22,23 * * *',
        ])
    })

    it.each(['refs/heads/master', ''])('the hourly Depot run keeps master coverage with ref %j', (ref) => {
        const depot = workflow(DEPOT_BACKEND)
        const plan = planWorkflow(depot, {
            name: 'hourly schedule',
            github: { ...schedule(), ref },
            steps: {
                ...allFiltersChanged(depot),
                ...backendSelectors,
            },
        })
        expect(plan.errors).toEqual([])
        const running = new Set(runningJobs(plan))
        const perCommit = ['repo-checks', 'sdk-major-guard', 'check-migrations', 'check-openapi-types']
        expect({
            didNotRun: ['changes', 'turbo-tests', 'django', 'django_tests', 'report-test-timings'].filter(
                (id) => !running.has(id)
            ),
            didNotSkip: perCommit.filter((id) => plan.jobs[id]?.result !== 'skipped'),
            filterRuns: plan.jobs.changes?.steps.find((step) => step.id === 'filter')?.runs,
            productTimings: plan.jobs['turbo-tests']?.steps.find((step) => step.name === 'Upload timing data')?.runs,
        }).toEqual({ didNotRun: [], didNotSkip: [], filterRuns: false, productTimings: true })
    })

    it.each([
        ['23 */3 * * *', true],
        ['23 1,2,4,5,7,8,10,11,13,14,16,17,19,20,22,23 * * *', false],
    ])('the events_json leg follows the scheduled trigger %s', (cron, runs) => {
        const depot = workflow(DEPOT_BACKEND)
        const step = depot.jobs.build_django_matrix?.steps?.find((step) => step.id === 'build')
        const github = { ...schedule(), event: { schedule: cron } }
        const functions = planFunctions({ dependenciesSucceeded: true, dependenciesFailed: false, cancelled: false })
        expect(evaluateValue(step?.env?.RUN_JSON_TARGETS, { github }, functions)).toBe(runs)
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
        expect(plan.jobs['code-quality']?.steps.find((step) => step.name === 'Save mypy cache')?.runs).toBe(runs)
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
            expect(plan.jobs.build?.steps.find((step) => step.name === 'Report sccache counters')?.runs).toBe(true)
            expect(plan.jobs.build?.result).toBe(outcome)
        }
    )

    it.each([
        ['frontend PR', pullRequest(), false, true, 'false', 'skipped', false],
        ['frontend merge queue', mergeQueue(), false, true, 'true', 'success', false],
        ['hobby PR', pullRequest(), true, false, 'true', 'success', true],
        ['hobby merge queue', mergeQueue(), true, false, 'true', 'success', false],
        ['unrelated merge queue', mergeQueue(), false, false, 'false', 'skipped', false],
    ] as const)('Docker image build on %s', (name, github, hobby, buildInputs, shouldBuild, result, publish) => {
        const wf = workflow('container-images-ci.yml')
        const plan = planWorkflow(wf, {
            name,
            github,
            steps: { changes: { filter: pathsFilter({ hobby, build_inputs: buildInputs }) } },
        })
        expect(plan.errors).toEqual([])
        expect(plan.jobs.changes?.outputs.should_build).toBe(shouldBuild)
        expect(plan.jobs.posthog_build?.result).toBe(result)
        const build = wf.jobs.posthog_build?.steps?.find((step) => step.id === 'build')
        if (result === 'success') {
            const functions = planFunctions({
                dependenciesSucceeded: true,
                dependenciesFailed: false,
                cancelled: false,
            })
            expect(evaluateValue(build?.with?.['push-image'], { github }, functions)).toBe(publish)
            expect(evaluateValue(build?.with?.['pr-number'], { github }, functions)).toBe(publish ? 1 : '')
        }
        expect(plan.jobs.posthog_build?.steps.find((step) => step.name === 'Container image digest')?.runs).toBe(
            result === 'success' && publish
        )
    })

    it.each(PINNED_WORKFLOWS)('%s names every conditional job in an expectation row', (file) => {
        const unnamed = Object.entries(workflow(file).jobs)
            .filter(([id, job]) => job.if !== undefined && !namedJobs(file).has(id))
            .map(([id]) => id)
        expect(unnamed).toEqual([])
    })

    it.each([...workflowFiles, DEPOT_BACKEND])(
        '%s evaluates every job and step condition under the built-in scenarios',
        (file) => {
            const wf = workflow(file)
            const errors = defaultScenarios(wf, path.join(REPO_ROOT, workflowKey(file))).flatMap((scenario) =>
                planWorkflow(wf, scenario).errors.map((error) => formatPlanError(scenario.name, error))
            )
            expect(errors).toEqual([])
        }
    )

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
