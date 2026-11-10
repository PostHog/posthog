import {
    CostableJob,
    OrderableWorkflowRow,
    RunCostSummary,
    computeFleetSummary,
    computeHealthSummary,
    isNoOpRun,
    orderWorkflowHealthRows,
    summarizeRunCost,
} from './runHealth'

const at = (hour: number): string => `2026-06-24T${String(hour).padStart(2, '0')}:00:00Z`

describe('runHealth', () => {
    it.each([
        ['no completed runs → unknown', [{ conclusion: null, durationSeconds: null, startedAt: at(9) }], 'unknown'],
        [
            'latest settled run failed → failing',
            [
                { conclusion: 'success', durationSeconds: 600, startedAt: at(9) },
                { conclusion: 'failure', durationSeconds: 600, startedAt: at(10) },
            ],
            'failing',
        ],
        [
            'below pass-rate floor but latest passed → degraded',
            [
                { conclusion: 'failure', durationSeconds: 600, startedAt: at(9) },
                { conclusion: 'failure', durationSeconds: 600, startedAt: at(10) },
                { conclusion: 'success', durationSeconds: 600, startedAt: at(11) },
            ],
            'degraded',
        ],
        [
            'cancelled is not a failure → healthy',
            [
                { conclusion: 'cancelled', durationSeconds: 600, startedAt: at(9) },
                { conclusion: 'success', durationSeconds: 600, startedAt: at(10) },
            ],
            'healthy',
        ],
    ])('classifies state: %s', (_name, runs, expected) => {
        expect(computeHealthSummary(runs).state).toBe(expected)
    })

    it('excludes non-verdict conclusions from the pass rate', () => {
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 600, startedAt: at(9) },
            { conclusion: 'skipped', durationSeconds: 600, startedAt: at(10) },
            { conclusion: 'cancelled', durationSeconds: 600, startedAt: at(11) },
            { conclusion: 'action_required', durationSeconds: 600, startedAt: at(12) },
            { conclusion: 'neutral', durationSeconds: 600, startedAt: at(13) },
            { conclusion: 'future_outcome', durationSeconds: 600, startedAt: at(14) },
        ])
        expect(summary.conclusiveRuns).toBe(1)
        expect(summary.passedRuns).toBe(1)
        expect(summary.passRate).toBe(1)
        expect(summary.failures).toBe(0)
        expect(summary.state).toBe('healthy')
    })

    it.each(['failure', 'timed_out', 'startup_failure', 'stale'])('counts %s as a decisive failure', (conclusion) => {
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 600, startedAt: at(9) },
            { conclusion, durationSeconds: 600, startedAt: at(10) },
        ])
        expect(summary.conclusiveRuns).toBe(2)
        expect(summary.failures).toBe(1)
        expect(summary.passRate).toBe(0.5)
        expect(summary.state).toBe('failing')
    })

    it('excludes still-running runs from rates and durations, and counts re-runs', () => {
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 120, startedAt: at(9), runAttempt: 1 },
            { conclusion: 'failure', durationSeconds: 240, startedAt: at(10), runAttempt: 2 },
            { conclusion: null, durationSeconds: null, startedAt: at(11), runAttempt: 1 },
        ])
        expect(summary.passRate).toBe(0.5)
        expect(summary.failures).toBe(1)
        expect(summary.reruns).toBe(1)
        expect(summary.medianSeconds).toBe(120)
        expect(summary.p95Seconds).toBe(120)
    })

    it.each([
        ['seconds-long success (gate job, rest skipped) → no-op', 'success', 4, true],
        ['seconds-long skipped run → no-op', 'skipped', 2, true],
        ['seconds-long cancelled run (superseded) → no-op', 'cancelled', 3, true],
        ['seconds-long failure is signal, not noise → kept', 'failure', 4, false],
        ['seconds-long action_required needs attention → kept', 'action_required', 3, false],
        ['at the threshold → kept', 'success', 10, false],
        ['still running (no duration yet) → kept', null, null, false],
    ])('flags no-op runs: %s', (_name, conclusion, durationSeconds, expected) => {
        expect(isNoOpRun({ conclusion, durationSeconds })).toBe(expected)
    })

    it('keeps no-op runs in counts and pass rate but out of the duration percentiles', () => {
        // A workflow dominated by no-op gate runs must not report their median, because that hides
        // the real CI duration.
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 4, startedAt: at(9) },
            { conclusion: 'success', durationSeconds: 4, startedAt: at(10) },
            { conclusion: 'success', durationSeconds: 4, startedAt: at(11) },
            { conclusion: 'success', durationSeconds: 600, startedAt: at(12) },
            { conclusion: 'success', durationSeconds: 900, startedAt: at(13) },
        ])
        expect(summary.medianSeconds).toBe(600)
        expect(summary.p95Seconds).toBe(900)
        expect(summary.totalRuns).toBe(5)
        expect(summary.passRate).toBe(1)
    })

    it('falls back to every duration when a workflow is legitimately all-fast', () => {
        // An intentionally quick workflow has no "real" runs by the no-op definition, so its median
        // must come from the runs it has.
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 3, startedAt: at(9) },
            { conclusion: 'success', durationSeconds: 4, startedAt: at(10) },
            { conclusion: 'success', durationSeconds: 5, startedAt: at(11) },
        ])
        expect(summary.medianSeconds).toBe(4)
    })

    it('lets a lone real duration win over no-op noise', () => {
        // With one real execution among gate runs, a fallback to all durations would let the no-ops
        // drown it.
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 4, startedAt: at(9) },
            { conclusion: 'success', durationSeconds: 4, startedAt: at(10) },
            { conclusion: 'success', durationSeconds: 600, startedAt: at(11) },
        ])
        expect(summary.medianSeconds).toBe(600)
    })

    const fleetRow = (
        latestRunFailed: boolean | null,
        successRate: number | null = 1,
        lastFailureAt: string | null = null
    ): {
        runCount: number
        successRate: number | null
        latestRunFailed: boolean | null
        lastFailureAt: string | null
    } => ({ runCount: 5, successRate, latestRunFailed, lastFailureAt })

    it.each([
        ['no workflows → unknown', [], 'unknown'],
        ['workflows present but none settled → unknown', [fleetRow(null), fleetRow(null)], 'unknown'],
        ['every settled workflow failing → failing', [fleetRow(true), fleetRow(true)], 'failing'],
        ['some failing, some green → degraded', [fleetRow(true), fleetRow(false)], 'degraded'],
        ['green but flaky (low success + a real failure) → degraded', [fleetRow(false, 0.7, at(9))], 'degraded'],
        // A low rate with no decisive failure in the window stays healthy, never a false flaky verdict.
        ['green, low success, no failures → healthy', [fleetRow(false, 0.7, null)], 'healthy'],
        ['all green and healthy → healthy', [fleetRow(false, 0.99), fleetRow(false)], 'healthy'],
    ])('classifies fleet state: %s', (_name, rows, expected) => {
        expect(computeFleetSummary(rows).state).toBe(expected)
    })

    it('sums runs, re-runs, and cost across workflows', () => {
        const summary = computeFleetSummary([
            {
                runCount: 10,
                successRate: 1,
                latestRunFailed: false,
                billableMinutes: 100,
                estimatedCostUsd: 4,
                rerunCycles: 3,
            },
            { runCount: 5, successRate: 1, latestRunFailed: true, billableMinutes: 50, estimatedCostUsd: 2 },
        ])
        expect(summary.totalRuns).toBe(15)
        expect(summary.failingNow).toBe(1)
        expect(summary.rerunCycles).toBe(3)
        expect(summary.estimatedCostUsd).toBe(6)
        expect(summary.billableMinutes).toBe(150)
    })

    it.each([
        // Weighted by conclusive runs, so skipped and cancelled volume cannot lower the rate.
        [
            'weights the fleet rate by conclusive runs, not per-row average',
            [
                { runCount: 2, successRate: 1, latestRunFailed: false, buckets: [{ successes: 2, failures: 0 }] },
                {
                    runCount: 10,
                    successRate: 0.5,
                    latestRunFailed: true,
                    buckets: [
                        { successes: 2, failures: 1 },
                        { successes: 1, failures: 2 },
                    ],
                },
            ],
            0.625,
        ],
        // Completed runs without a verdict produce null, never a misleading 0%.
        [
            'null when nothing reached a verdict',
            [{ runCount: 3, successRate: null, latestRunFailed: false, buckets: [{ successes: 0, failures: 0 }] }],
            null,
        ],
        // Rows without buckets (per-push rows) contribute nothing rather than crashing or zeroing the rate.
        [
            'rows without buckets are tolerated',
            [
                { runCount: 4, successRate: 0.5, latestRunFailed: false, buckets: [{ successes: 2, failures: 2 }] },
                { runCount: 9, successRate: 1, latestRunFailed: false },
            ],
            0.5,
        ],
    ])('computes the fleet pass rate: %s', (_name, rows, expected) => {
        expect(computeFleetSummary(rows).passRate).toBe(expected)
    })

    it.each<[string, OrderableWorkflowRow[], string[]]>([
        [
            'merge-queue workflows first, then run count',
            [
                { workflowName: 'Docs', runCount: 900, mergeQueueRunCount: 0 },
                { workflowName: 'Backend CI', runCount: 40, mergeQueueRunCount: 12 },
                { workflowName: 'Frontend CI', runCount: 300, mergeQueueRunCount: 5 },
            ],
            ['Frontend CI', 'Backend CI', 'Docs'],
        ],
        [
            'no gating rows leaves pure run-count order',
            [
                { workflowName: 'Docs', runCount: 90, mergeQueueRunCount: 0 },
                { workflowName: 'Backend CI', runCount: 400, mergeQueueRunCount: 0 },
            ],
            ['Backend CI', 'Docs'],
        ],
        [
            'equal run counts settle by name',
            [
                { workflowName: 'Zeta', runCount: 10, mergeQueueRunCount: 0 },
                { workflowName: 'Alpha', runCount: 10, mergeQueueRunCount: 0 },
            ],
            ['Alpha', 'Zeta'],
        ],
    ])('orderWorkflowHealthRows: %s', (_name, rows, expected) => {
        expect(orderWorkflowHealthRows(rows).map((row) => row.workflowName)).toEqual(expected)
    })

    const job = (
        runner_provider: string,
        duration_seconds: number | null,
        estimated_cost_usd: number | null
    ): CostableJob => ({ runner_provider, duration_seconds, estimated_cost_usd })

    it.each<[string, CostableJob[], RunCostSummary | null]>([
        // Null lets the caller omit the tile instead of showing $0.
        ['no billable jobs → null', [job('github_hosted', 600, null), job('unknown', 600, null)], null],
        [
            'sums settled self-hosted, ignores free',
            [job('self_hosted', 120, 0.5), job('self_hosted', 60, 0.25), job('github_hosted', 600, null)],
            { billableMinutes: 3, estimatedCostUsd: 0.75, unsettledJobs: 0 },
        ],
        // A running billable job stays out of the total, because counting it would understate $/min or
        // report a bogus 0.
        [
            'in-flight billable job is unsettled, not in the total',
            [job('self_hosted', 120, 0.5), job('self_hosted', null, null)],
            { billableMinutes: 2, estimatedCostUsd: 0.5, unsettledJobs: 1 },
        ],
        [
            'all in flight → null value, caveat only',
            [job('self_hosted', null, null)],
            { billableMinutes: null, estimatedCostUsd: null, unsettledJobs: 1 },
        ],
        // A finished self-hosted job with no cost ran on an unpriced tier (non-Linux Depot). It must not
        // keep the "unsettled job excluded" caveat alive on a completed run.
        [
            'finished uncostable self-hosted job is excluded, not unsettled',
            [job('self_hosted', 120, 0.5), job('self_hosted', 300, null)],
            { billableMinutes: 2, estimatedCostUsd: 0.5, unsettledJobs: 0 },
        ],
        [
            'all billable jobs finished but unpriced → null',
            [job('self_hosted', 300, null), job('self_hosted', 120, null)],
            null,
        ],
    ])('summarizeRunCost: %s', (_name, jobs, expected) => {
        expect(summarizeRunCost(jobs)).toEqual(expected)
    })
})
