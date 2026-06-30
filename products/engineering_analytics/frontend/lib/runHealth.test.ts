import { CostableJob, computeFleetSummary, computeHealthSummary, summarizeRunCost } from './runHealth'

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

    it('summarizeRunCost is null when nothing is billable, so the caller omits the tile (no $0.00)', () => {
        expect(summarizeRunCost([job('github_hosted', 600, null), job('unknown', 600, null)])).toBeNull()
    })

    it('summarizeRunCost sums only settled self-hosted jobs and ignores free runners', () => {
        expect(
            summarizeRunCost([
                job('self_hosted', 120, 0.5),
                job('self_hosted', 60, 0.25),
                job('github_hosted', 600, null),
            ])
        ).toEqual({ billableMinutes: 3, estimatedCostUsd: 0.75, unsettledJobs: 0 })
    })

    it('summarizeRunCost excludes in-flight billable jobs from the total but counts them as unsettled', () => {
        // A running self-hosted job has no cost yet — counting it would understate $/min or report a bogus
        // 0; it must drop out of the total and surface as a caveat, matching the backend roll-up.
        expect(summarizeRunCost([job('self_hosted', 120, 0.5), job('self_hosted', null, null)])).toEqual({
            billableMinutes: 2,
            estimatedCostUsd: 0.5,
            unsettledJobs: 1,
        })
    })

    it('summarizeRunCost keeps the tile (null value) when every billable job is still in flight', () => {
        expect(summarizeRunCost([job('self_hosted', null, null)])).toEqual({
            billableMinutes: null,
            estimatedCostUsd: null,
            unsettledJobs: 1,
        })
    })
})
