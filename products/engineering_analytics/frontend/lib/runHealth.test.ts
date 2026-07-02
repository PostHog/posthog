import { CostableJob, RunCostSummary, computeFleetSummary, computeHealthSummary, summarizeRunCost } from './runHealth'

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

    it('counts only conclusion=success as a pass, matching the backend success_rate', () => {
        // Skipped/neutral are completed but not successes — the header must not inflate pass rate past
        // what the Workflows table shows for the same window.
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 600, startedAt: at(9) },
            { conclusion: 'skipped', durationSeconds: 600, startedAt: at(10) },
        ])
        expect(summary.completedRuns).toBe(2)
        expect(summary.passedRuns).toBe(1)
        expect(summary.passRate).toBe(0.5)
        expect(summary.failures).toBe(0)
        expect(summary.state).toBe('healthy')
    })

    it('excludes still-running runs from rates and durations, and counts re-runs', () => {
        const summary = computeHealthSummary([
            { conclusion: 'success', durationSeconds: 120, startedAt: at(9), runAttempt: 1 },
            { conclusion: 'failure', durationSeconds: 240, startedAt: at(10), runAttempt: 2 },
            { conclusion: null, durationSeconds: null, startedAt: at(11), runAttempt: 1 },
        ])
        expect(summary.completedRuns).toBe(2)
        expect(summary.running).toBe(1)
        expect(summary.passRate).toBe(0.5)
        expect(summary.failures).toBe(1)
        expect(summary.reruns).toBe(1)
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
        // Low success driven by skips/cancels, never a decisive failure → healthy, not flaky (matches the
        // single-workflow verdict).
        ['green, low success, no failures → healthy', [fleetRow(false, 0.7, null)], 'healthy'],
        ['all green and healthy → healthy', [fleetRow(false, 0.99), fleetRow(false)], 'healthy'],
    ])('classifies fleet state: %s', (_name, rows, expected) => {
        expect(computeFleetSummary(rows).state).toBe(expected)
    })

    it('sums runs and cost across workflows', () => {
        const summary = computeFleetSummary([
            { runCount: 10, successRate: 1, latestRunFailed: false, billableMinutes: 100, estimatedCostUsd: 4 },
            { runCount: 5, successRate: 1, latestRunFailed: true, billableMinutes: 50, estimatedCostUsd: 2 },
        ])
        expect(summary.totalRuns).toBe(15)
        expect(summary.failingNow).toBe(1)
        expect(summary.estimatedCostUsd).toBe(6)
        expect(summary.billableMinutes).toBe(150)
    })

    const job = (
        runner_provider: string,
        duration_seconds: number | null,
        estimated_cost_usd: number | null
    ): CostableJob => ({ runner_provider, duration_seconds, estimated_cost_usd })

    it.each<[string, CostableJob[], RunCostSummary | null]>([
        // Nothing billable (all free / unknown) → null so the caller omits the tile instead of showing $0.
        ['no billable jobs → null', [job('github_hosted', 600, null), job('unknown', 600, null)], null],
        // Settled self-hosted jobs sum; free runners are ignored.
        [
            'sums settled self-hosted, ignores free',
            [job('self_hosted', 120, 0.5), job('self_hosted', 60, 0.25), job('github_hosted', 600, null)],
            { billableMinutes: 3, estimatedCostUsd: 0.75, unsettledJobs: 0 },
        ],
        // A still-running (no duration) billable job is excluded from the total and counted as unsettled —
        // counting it would understate $/min or report a bogus 0.
        [
            'in-flight billable job is unsettled, not in the total',
            [job('self_hosted', 120, 0.5), job('self_hosted', null, null)],
            { billableMinutes: 2, estimatedCostUsd: 0.5, unsettledJobs: 1 },
        ],
        // Every billable job still in flight → keep the tile (null value) plus the unsettled caveat.
        [
            'all in flight → null value, caveat only',
            [job('self_hosted', null, null)],
            { billableMinutes: null, estimatedCostUsd: null, unsettledJobs: 1 },
        ],
        // A finished self-hosted job with no cost is an unpriced tier (non-Linux Depot), excluded — NOT
        // unsettled. It must not keep the "unsettled job excluded" caveat alive on a completed run.
        [
            'finished uncostable self-hosted job is excluded, not unsettled',
            [job('self_hosted', 120, 0.5), job('self_hosted', 300, null)],
            { billableMinutes: 2, estimatedCostUsd: 0.5, unsettledJobs: 0 },
        ],
        // Every billable job finished on an unpriced tier → nothing to show, omit the tile (no dangling "—").
        [
            'all billable jobs finished but unpriced → null',
            [job('self_hosted', 300, null), job('self_hosted', 120, null)],
            null,
        ],
    ])('summarizeRunCost: %s', (_name, jobs, expected) => {
        expect(summarizeRunCost(jobs)).toEqual(expected)
    })
})
