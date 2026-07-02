/** Faked data for the UX-overhaul preview. Nothing here touches the backend — every number is
 *  invented but plausible for a monorepo the size of PostHog/posthog. Deterministic (seeded RNG)
 *  so screenshots are reproducible while we iterate on layout. */

import type { ActivityRun } from '../components/RunActivityChart'

function mulberry32(a: number): () => number {
    return function () {
        a |= 0
        a = (a + 0x6d2b79f5) | 0
        let t = Math.imul(a ^ (a >>> 15), 1 | a)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

export const DAY_LABELS: string[] = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(2026, 5, 19 + i)
    return `${d.getMonth() + 1}/${d.getDate()}`
})

export function daySeries(seed: number, base: number, noise: number, trend: number = 0): number[] {
    const r = mulberry32(seed)
    return DAY_LABELS.map((_, i) => Math.max(0, base + trend * i + (r() - 0.5) * 2 * noise))
}

export interface MockWorkflow {
    slug: string
    name: string
    runs30d: number
    passRate: number
    passRateDeltaPp: number
    p50Min: number
    p95Min: number
    p95DeltaMin: number
    cost30d: number
    costDeltaPct: number
    lastFailure: string
    onMaster: 'passing' | 'failing'
    /** daily completed runs + decisive failures for FailureSparkline */
    completed: number[]
    failures: number[]
    passSeries: number[]
}

export const MOCK_WORKFLOWS: MockWorkflow[] = [
    {
        slug: 'backend-ci',
        name: 'Backend CI',
        runs30d: 3120,
        passRate: 0.87,
        passRateDeltaPp: +2,
        p50Min: 22,
        p95Min: 41,
        p95DeltaMin: +4,
        cost30d: 4310,
        costDeltaPct: +10,
        lastFailure: '18m ago',
        onMaster: 'passing',
        completed: daySeries(11, 104, 22),
        failures: daySeries(12, 13, 7),
        passSeries: daySeries(13, 0.87, 0.04),
    },
    {
        slug: 'e2e-ci',
        name: 'E2E CI',
        runs30d: 2260,
        passRate: 0.72,
        passRateDeltaPp: -6,
        p50Min: 31,
        p95Min: 58,
        p95DeltaMin: +9,
        cost30d: 2870,
        costDeltaPct: +22,
        lastFailure: '6m ago',
        onMaster: 'failing',
        completed: daySeries(21, 75, 16),
        failures: daySeries(22, 19, 9, +0.9),
        passSeries: daySeries(23, 0.79, 0.05, -0.008),
    },
    {
        slug: 'frontend-ci',
        name: 'Frontend CI',
        runs30d: 2980,
        passRate: 0.94,
        passRateDeltaPp: +1,
        p50Min: 14,
        p95Min: 26,
        p95DeltaMin: -2,
        cost30d: 1130,
        costDeltaPct: -7,
        lastFailure: '3h ago',
        onMaster: 'passing',
        completed: daySeries(31, 99, 18),
        failures: daySeries(32, 6, 4),
        passSeries: daySeries(33, 0.94, 0.02),
    },
    {
        slug: 'storybook',
        name: 'Storybook',
        runs30d: 1410,
        passRate: 0.89,
        passRateDeltaPp: -1,
        p50Min: 24,
        p95Min: 37,
        p95DeltaMin: +1,
        cost30d: 920,
        costDeltaPct: +4,
        lastFailure: '1h ago',
        onMaster: 'passing',
        completed: daySeries(41, 47, 10),
        failures: daySeries(42, 5, 3),
        passSeries: daySeries(43, 0.89, 0.03),
    },
    {
        slug: 'cd-images',
        name: 'Container images CD',
        runs30d: 340,
        passRate: 0.91,
        passRateDeltaPp: 0,
        p50Min: 18,
        p95Min: 33,
        p95DeltaMin: 0,
        cost30d: 780,
        costDeltaPct: +2,
        lastFailure: '2d ago',
        onMaster: 'passing',
        completed: daySeries(51, 11, 3),
        failures: daySeries(52, 1, 1),
        passSeries: daySeries(53, 0.91, 0.04),
    },
    {
        slug: 'rust-ci',
        name: 'Rust CI',
        runs30d: 1890,
        passRate: 0.96,
        passRateDeltaPp: +1,
        p50Min: 9,
        p95Min: 17,
        p95DeltaMin: -1,
        cost30d: 640,
        costDeltaPct: -8,
        lastFailure: '9h ago',
        onMaster: 'passing',
        completed: daySeries(61, 63, 12),
        failures: daySeries(62, 2.5, 2),
        passSeries: daySeries(63, 0.96, 0.015),
    },
    {
        slug: 'plugin-server',
        name: 'Plugin server CI',
        runs30d: 1260,
        passRate: 0.93,
        passRateDeltaPp: 0,
        p50Min: 11,
        p95Min: 21,
        p95DeltaMin: +1,
        cost30d: 310,
        costDeltaPct: +3,
        lastFailure: '14h ago',
        onMaster: 'passing',
        completed: daySeries(71, 42, 9),
        failures: daySeries(72, 3, 2),
        passSeries: daySeries(73, 0.93, 0.025),
    },
    {
        slug: 'lint',
        name: 'Lint & types',
        runs30d: 3340,
        passRate: 0.98,
        passRateDeltaPp: 0,
        p50Min: 4,
        p95Min: 8,
        p95DeltaMin: 0,
        cost30d: 210,
        costDeltaPct: -2,
        lastFailure: '1d ago',
        onMaster: 'passing',
        completed: daySeries(81, 111, 20),
        failures: daySeries(82, 2, 1.6),
        passSeries: daySeries(83, 0.98, 0.008),
    },
    {
        slug: 'migrations',
        name: 'Migrations check',
        runs30d: 1180,
        passRate: 0.99,
        passRateDeltaPp: 0,
        p50Min: 6,
        p95Min: 10,
        p95DeltaMin: 0,
        cost30d: 95,
        costDeltaPct: 0,
        lastFailure: '4d ago',
        onMaster: 'passing',
        completed: daySeries(91, 39, 8),
        failures: daySeries(92, 0.5, 0.7),
        passSeries: daySeries(93, 0.99, 0.005),
    },
    {
        slug: 'docs',
        name: 'Docs preview',
        runs30d: 410,
        passRate: 0.97,
        passRateDeltaPp: 0,
        p50Min: 3,
        p95Min: 6,
        p95DeltaMin: 0,
        cost30d: 60,
        costDeltaPct: 0,
        lastFailure: '6d ago',
        onMaster: 'passing',
        completed: daySeries(101, 14, 4),
        failures: daySeries(102, 0.4, 0.5),
        passSeries: daySeries(103, 0.97, 0.01),
    },
]

export const mockWorkflow = (slug: string): MockWorkflow =>
    MOCK_WORKFLOWS.find((w) => w.slug === slug) ?? MOCK_WORKFLOWS[0]

export interface MockPr {
    number: number
    title: string
    author: string
    state: 'open' | 'merged'
    ci: 'passing' | 'failing' | 'running'
    /** which checks are red on the latest push — shown under the CI tag so a list answers "why" */
    failingChecks?: string
    pushes: number
    reruns: number
    costUsd: number
    openHours: number
}

export const MOCK_PRS: MockPr[] = [
    {
        number: 67891,
        title: 'feat(insights): add retention graph export',
        author: 'webjunkie',
        state: 'open',
        ci: 'failing',
        failingChecks: 'E2E CI · Backend CI',
        pushes: 4,
        reruns: 2,
        costUsd: 12.4,
        openHours: 52,
    },
    {
        number: 67874,
        title: 'fix(cohorts): handle empty cohort in query builder',
        author: 'anna-cx',
        state: 'open',
        ci: 'passing',
        pushes: 2,
        reruns: 0,
        costUsd: 5.1,
        openHours: 9,
    },
    {
        number: 67862,
        title: 'feat(llma): trace-level cost rollups for gateway spans',
        author: 'marcush',
        state: 'open',
        ci: 'running',
        pushes: 6,
        reruns: 1,
        costUsd: 19.8,
        openHours: 76,
    },
    {
        number: 67858,
        title: 'chore(deps): bump kea to 3.2.1',
        author: 'dev-priya',
        state: 'open',
        ci: 'passing',
        pushes: 1,
        reruns: 0,
        costUsd: 2.2,
        openHours: 4,
    },
    {
        number: 67851,
        title: 'fix(replay): guard against missing snapshot windows',
        author: 'tomasfp',
        state: 'open',
        ci: 'failing',
        failingChecks: 'Storybook',
        pushes: 5,
        reruns: 3,
        costUsd: 16.7,
        openHours: 121,
    },
    {
        number: 67845,
        title: 'feat(flags): payload preview in the flag form',
        author: 'webjunkie',
        state: 'merged',
        ci: 'passing',
        pushes: 3,
        reruns: 0,
        costUsd: 7.9,
        openHours: 22,
    },
    {
        number: 67840,
        title: 'fix(warehouse): nullable timestamps in source sync',
        author: 'anna-cx',
        state: 'merged',
        ci: 'passing',
        pushes: 2,
        reruns: 1,
        costUsd: 6.3,
        openHours: 15,
    },
]

export const mockPr = (n: number | string): MockPr => MOCK_PRS.find((p) => p.number === Number(n)) ?? MOCK_PRS[0]

export interface MockAuthor {
    handle: string
    prs30d: number
    prsDelta: number
    medianMergeHours: number
    mergeDeltaHours: number
    ciCost30d: number
    rerunCycles: number
}

export const MOCK_AUTHORS: MockAuthor[] = [
    {
        handle: 'webjunkie',
        prs30d: 14,
        prsDelta: +2,
        medianMergeHours: 18,
        mergeDeltaHours: -3,
        ciCost30d: 86,
        rerunCycles: 6,
    },
    {
        handle: 'marcush',
        prs30d: 11,
        prsDelta: -1,
        medianMergeHours: 26,
        mergeDeltaHours: +4,
        ciCost30d: 71,
        rerunCycles: 9,
    },
    {
        handle: 'anna-cx',
        prs30d: 9,
        prsDelta: +3,
        medianMergeHours: 14,
        mergeDeltaHours: -1,
        ciCost30d: 64,
        rerunCycles: 2,
    },
    {
        handle: 'tomasfp',
        prs30d: 8,
        prsDelta: 0,
        medianMergeHours: 31,
        mergeDeltaHours: +6,
        ciCost30d: 58,
        rerunCycles: 11,
    },
    {
        handle: 'dev-priya',
        prs30d: 7,
        prsDelta: +1,
        medianMergeHours: 22,
        mergeDeltaHours: 0,
        ciCost30d: 41,
        rerunCycles: 4,
    },
]

export const mockAuthor = (h: string): MockAuthor => MOCK_AUTHORS.find((a) => a.handle === h) ?? MOCK_AUTHORS[0]

export interface MockRunnerTier {
    tier: string
    jobs: number
    costUsd: number
    share: number
}

export const MOCK_RUNNER_TIERS: MockRunnerTier[] = [
    { tier: 'depot-ubuntu-latest-4', jobs: 9120, costUsd: 6980, share: 0.71 },
    { tier: 'depot-ubuntu-latest', jobs: 5460, costUsd: 2210, share: 0.22 },
    { tier: 'ubuntu-latest (GitHub-hosted)', jobs: 7220, costUsd: 0, share: 0.05 },
    { tier: 'depot-ubuntu-arm-4', jobs: 840, costUsd: 640, share: 0.02 },
]

export interface MockLogLine {
    t: string
    level: 'error' | 'warn' | 'info' | 'debug'
    msg: string
}

export const MOCK_LOG_E2E: MockLogLine[] = [
    { t: '14:32:18', level: 'info', msg: 'e2e/insights/retention-export.spec.ts:112 › export shows in the menu' },
    { t: '14:32:48', level: 'error', msg: 'Error: expect(locator).toBeVisible() failed' },
    { t: '14:32:48', level: 'debug', msg: "waiting for getByTestId('export-menu-item') to be visible" },
    { t: '14:32:48', level: 'debug', msg: '52 × locator resolved to hidden <li data-testid="export-menu-item">…</li>' },
    { t: '14:33:18', level: 'error', msg: 'Timed out 30000ms waiting for expect(locator).toBeVisible()' },
    { t: '14:33:18', level: 'debug', msg: 'at InsightsPage.openExportMenu (e2e/pages/insights.ts:64)' },
]

export const MOCK_LOG_DJANGO: MockLogLine[] = [
    {
        t: '13:58:41',
        level: 'error',
        msg: 'FAILED posthog/api/test/test_insight.py::TestInsight::test_retention_export',
    },
    { t: '13:58:41', level: 'error', msg: 'AssertionError: 404 != 200 : export endpoint returned 404' },
    {
        t: '13:58:41',
        level: 'debug',
        msg: 'response = self.client.post(f"/api/projects/{self.team.id}/insights/{id}/export")',
    },
    { t: '13:58:42', level: 'info', msg: 'hint: route registered under /exports — serializer renamed the action' },
]

export interface MockFailure {
    workflow: string
    workflowSlug: string
    runId: number
    branch: string
    prNumber: number | null
    /** which job failed — a run is a rollup of its jobs, so attribution names the job */
    failedJob: string
    summary: string
    when: string
    log: MockLogLine[]
}

export const MOCK_FAILURES: MockFailure[] = [
    {
        workflow: 'E2E CI',
        workflowSlug: 'e2e-ci',
        runId: 41397,
        branch: 'master',
        prNumber: null,
        failedJob: 'e2e (chromium, shard 3/8)',
        summary: 'retention-export.spec.ts — export menu never visible',
        when: '6m ago',
        log: MOCK_LOG_E2E,
    },
    {
        workflow: 'E2E CI',
        workflowSlug: 'e2e-ci',
        runId: 41390,
        branch: 'master',
        prNumber: null,
        failedJob: 'e2e (chromium, shard 3/8)',
        summary: 'same spec — first red run of the window',
        when: '38m ago',
        log: MOCK_LOG_E2E,
    },
    {
        workflow: 'Backend CI',
        workflowSlug: 'backend-ci',
        runId: 41371,
        branch: 'feat/retention-export',
        prNumber: 67891,
        failedJob: 'Django tests (shard 3/6)',
        summary: 'test_insight.py::test_retention_export — 404 != 200',
        when: '1h ago',
        log: MOCK_LOG_DJANGO,
    },
    {
        workflow: 'Storybook',
        workflowSlug: 'storybook',
        runId: 41344,
        branch: 'fix/replay-window',
        prNumber: 67851,
        failedJob: 'chromatic (2/4)',
        summary: 'chromatic diff on InsightCard (2 stories)',
        when: '3h ago',
        log: [
            { t: '11:04:02', level: 'error', msg: '✗ InsightCard › with legend — visual diff 0.41% (threshold 0.1%)' },
            { t: '11:04:02', level: 'error', msg: '✗ InsightCard › narrow — visual diff 0.22% (threshold 0.1%)' },
            { t: '11:04:03', level: 'info', msg: 'review the diff in the Storybook run artifacts' },
        ],
    },
]

export interface MockJob {
    name: string
    queueMin: number
    startMin: number
    durMin: number
    conclusion: 'success' | 'failure' | 'skipped'
    runner: string
}

export function mockJobs(seed: number, failing: boolean, shardName: string = 'Django tests'): MockJob[] {
    const r = mulberry32(seed)
    const jobs: MockJob[] = []
    for (let i = 1; i <= 6; i++) {
        jobs.push({
            name: `${shardName} (shard ${i}/6)`,
            queueMin: 1 + r() * 3,
            startMin: 1.5 + r() * 2,
            durMin: 16 + r() * 7,
            conclusion: 'success',
            runner: 'depot-ubuntu-latest-4',
        })
    }
    if (failing) {
        jobs[2] = { ...jobs[2], conclusion: 'failure', durMin: 11.2 }
        jobs[4] = { ...jobs[4], conclusion: 'failure', durMin: 13.8 }
    }
    jobs.push({
        name: 'Migrations check',
        queueMin: 0.6 + r(),
        startMin: 1,
        durMin: 5.5 + r() * 2,
        conclusion: 'success',
        runner: 'depot-ubuntu-latest',
    })
    jobs.push({
        name: 'Lint & types',
        queueMin: 0.4 + r(),
        startMin: 0.8,
        durMin: 3.5 + r(),
        conclusion: 'success',
        runner: 'ubuntu-latest',
    })
    jobs.push({
        name: 'Build frontend assets',
        queueMin: 0.8 + r() * 2,
        startMin: 1.2,
        durMin: 9 + r() * 3,
        conclusion: 'success',
        runner: 'depot-ubuntu-latest-4',
    })
    jobs.push({
        name: 'Upload coverage',
        queueMin: 0.3,
        startMin: 24,
        durMin: 1.2,
        conclusion: failing ? 'skipped' : 'success',
        runner: 'ubuntu-latest',
    })
    return jobs
}

/** Rollup of a run's jobs — a run has almost no data of its own: its conclusion, duration
 *  (critical path), and cost all derive from the jobs underneath. */
export function summarizeJobs(jobs: MockJob[]): { failed: MockJob[]; skipped: number; label: string } {
    const failed = jobs.filter((j) => j.conclusion === 'failure')
    const skipped = jobs.filter((j) => j.conclusion === 'skipped').length
    const label = failed.length
        ? `${failed.length}/${jobs.length} jobs failed`
        : skipped
          ? `${jobs.length - skipped}/${jobs.length} jobs ran`
          : `${jobs.length} jobs`
    return { failed, skipped, label }
}

export interface MockJobAggregate {
    name: string
    /** matrix jobs auto-roll up into one row; null = plain job */
    matrixSize: number | null
    /** share of workflow runs this job actually ran in (conditional jobs skip) */
    runShare: number
    queueP50Min: number
    p50Min: number
    failureRate: number
    retries30d: number
    costShare: number
}

export const MOCK_JOB_AGGREGATES: MockJobAggregate[] = [
    {
        name: 'Django tests',
        matrixSize: 6,
        runShare: 1,
        queueP50Min: 1.4,
        p50Min: 19,
        failureRate: 0.09,
        retries30d: 41,
        costShare: 0.62,
    },
    {
        name: 'Build frontend assets',
        matrixSize: null,
        runShare: 1,
        queueP50Min: 0.9,
        p50Min: 10,
        failureRate: 0.02,
        retries30d: 6,
        costShare: 0.14,
    },
    {
        name: 'Migrations check',
        matrixSize: null,
        runShare: 0.94,
        queueP50Min: 0.7,
        p50Min: 6,
        failureRate: 0.01,
        retries30d: 2,
        costShare: 0.09,
    },
    {
        name: 'Lint & types',
        matrixSize: null,
        runShare: 1,
        queueP50Min: 0.5,
        p50Min: 4,
        failureRate: 0.02,
        retries30d: 3,
        costShare: 0.06,
    },
    {
        name: 'Visual regression',
        matrixSize: 4,
        runShare: 0.31,
        queueP50Min: 2.1,
        p50Min: 8,
        failureRate: 0.06,
        retries30d: 12,
        costShare: 0.04,
    },
    {
        name: 'Upload coverage',
        matrixSize: null,
        runShare: 0.66,
        queueP50Min: 0.3,
        p50Min: 1.5,
        failureRate: 0.04,
        retries30d: 9,
        costShare: 0.03,
    },
]

/** Runs for the real RunActivityChart, spread over the last 3 days relative to now. */
export function mockActivityRuns(seed: number, count: number, failRate: number, p50Min: number): ActivityRun[] {
    const r = mulberry32(seed)
    const now = Date.now()
    const spanMs = 3 * 24 * 60 * 60 * 1000
    return Array.from({ length: count }, (_, i) => {
        const failed = r() < failRate
        const cancelled = !failed && r() < 0.05
        const startedAt = new Date(now - r() * spanMs).toISOString()
        return {
            runId: 41100 + i * 3,
            conclusion: cancelled ? 'cancelled' : failed ? 'failure' : 'success',
            startedAt,
            durationSeconds: Math.round(p50Min * 60 * (0.65 + r() * 1.3) + (failed ? r() * p50Min * 30 : 0)),
            headBranch:
                r() < 0.4
                    ? 'master'
                    : ['feat/retention-export', 'fix/replay-window', 'chore/bump-kea'][Math.floor(r() * 3)],
            prNumber: r() < 0.55 ? MOCK_PRS[Math.floor(r() * MOCK_PRS.length)].number : null,
        }
    })
}

export interface MockRun {
    id: number
    branch: string
    prNumber: number | null
    conclusion: 'success' | 'failure' | 'cancelled'
    durationMin: number
    when: string
    attempt: number
}

export const MOCK_RECENT_RUNS: MockRun[] = [
    { id: 41397, branch: 'master', prNumber: null, conclusion: 'failure', durationMin: 40, when: '6m ago', attempt: 1 },
    {
        id: 41393,
        branch: 'feat/retention-export',
        prNumber: 67891,
        conclusion: 'failure',
        durationMin: 34,
        when: '31m ago',
        attempt: 2,
    },
    {
        id: 41390,
        branch: 'master',
        prNumber: null,
        conclusion: 'failure',
        durationMin: 37,
        when: '38m ago',
        attempt: 1,
    },
    {
        id: 41384,
        branch: 'fix/replay-window',
        prNumber: 67851,
        conclusion: 'success',
        durationMin: 29,
        when: '1h ago',
        attempt: 1,
    },
    {
        id: 41377,
        branch: 'chore/bump-kea',
        prNumber: 67858,
        conclusion: 'success',
        durationMin: 27,
        when: '2h ago',
        attempt: 1,
    },
    {
        id: 41371,
        branch: 'feat/llma-cost-rollups',
        prNumber: 67862,
        conclusion: 'success',
        durationMin: 32,
        when: '2h ago',
        attempt: 1,
    },
]
