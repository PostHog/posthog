// Rolls a flat list of one workflow's runs up into the health facts the verdict header renders. Kept
// separate from the kea logic so both the workflow-runs page and (later) the PR page can derive the same
// summary, and so the math is unit-testable without a logic harness.

import { isDecisiveFailure } from './lifecycle'

// The minimum a run needs to score its health. Both WorkflowRunRow and PrRunRow satisfy this.
export interface HealthRun {
    conclusion: string | null
    startedAt: string | null
    durationSeconds: number | null
    /** Re-run attempt (1 for the first); a 2nd+ attempt is a re-run. */
    runAttempt?: number | null
}

/** Billable minutes + estimated cost rolled up across the window; null fields when jobs aren't synced. */
export interface CostSummary {
    billableMinutes: number | null
    estimatedCostUsd: number | null
}

/** A single run's cost rolled up from its jobs, plus the count of billable jobs still in flight. */
export interface RunCostSummary extends CostSummary {
    unsettledJobs: number
}

/** Minimal job shape the run-cost roll-up needs; WorkflowJobApi satisfies it. */
export interface CostableJob {
    runner_provider: string
    duration_seconds: number | null
    estimated_cost_usd: number | null
}

export type WorkflowState = 'healthy' | 'degraded' | 'failing' | 'unknown'

export interface HealthSummary {
    state: WorkflowState
    totalRuns: number
    completedRuns: number
    passedRuns: number
    failures: number
    running: number
    /** Runs that were a 2nd+ attempt — re-runs, a flakiness signal the chart doesn't show. */
    reruns: number
    /** Passes ÷ completed runs (null when nothing has settled). */
    passRate: number | null
    medianSeconds: number | null
    p95Seconds: number | null
    lastFailureAt: string | null
    latestConclusion: string | null
}

// At or above this decisive-failure rate a workflow whose latest run still passed reads as "degraded".
// Keyed off failures, not pass rate, so cancellations (neither pass nor failure) don't drag the verdict.
const DEGRADED_FAILURE_RATE = 0.1
// Below this success rate a currently-green workflow counts as flaky in the fleet rollup.
const FLAKY_SUCCESS_RATE = 0.9

// One workflow's row in the all-workflows table, reduced to what the fleet rollup needs.
export interface FleetRow {
    runCount: number
    successRate: number | null
    /** Most recent completed run failed; null when nothing has completed for that workflow. */
    latestRunFailed: boolean | null
    /** Last decisive failure in the window, or null if there was none — so a low success rate driven by
     *  skips/cancels (not failures) isn't mistaken for flakiness. */
    lastFailureAt?: string | null
    billableMinutes?: number | null
    estimatedCostUsd?: number | null
    /** Per-bucket completed/success counts — the weights behind the fleet-wide pass rate. */
    buckets?: { completed: number; successes: number }[]
    /** Runs in the window that were a 2nd+ attempt — retry pressure. */
    rerunCycles?: number
}

export interface FleetSummary {
    state: WorkflowState
    workflowCount: number
    /** Workflows whose latest run has settled (so they're either green or red right now). */
    settledWorkflows: number
    failingNow: number
    /** Currently green but below the success-rate floor — flaky. */
    flakyNow: number
    totalRuns: number
    /** Fleet-wide passes ÷ completed runs, summed across every row's buckets — the same weighting as each
     *  row's own success rate. Null when nothing has completed (or no row carries buckets). */
    passRate: number | null
    /** Re-runs (attempt > 1) summed across workflows — fleet retry pressure. */
    rerunCycles: number
    billableMinutes: number | null
    estimatedCostUsd: number | null
}

/** Nearest-rank percentile over an ascending-sorted sample. */
export function percentileSorted(sortedAsc: number[], q: number): number | null {
    if (sortedAsc.length === 0) {
        return null
    }
    return sortedAsc[Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(q * sortedAsc.length) - 1))]
}

/**
 * Verdict + headline stats for one workflow's runs. State mirrors the run tables: the latest settled run
 * failing is "failing"; an otherwise-passing workflow whose decisive-failure rate is elevated is
 * "degraded"; everything else is "healthy". Durations and rates are over completed runs only — a run that
 * hasn't settled is excluded, never counted as a failure.
 */
export function computeHealthSummary(runs: HealthRun[]): HealthSummary {
    const completed = runs.filter((run) => run.conclusion !== null)
    const running = runs.length - completed.length
    // Strictly conclusion === 'success', mirroring the workflow-health endpoint's success_rate
    // (skipped/neutral don't count as passes) so this header and the Workflows table agree.
    const passed = completed.filter((run) => run.conclusion === 'success').length
    const failures = completed.filter((run) => isDecisiveFailure(run.conclusion)).length
    const reruns = runs.filter((run) => (run.runAttempt ?? 1) > 1).length
    const passRate = completed.length ? passed / completed.length : null

    const durations = completed
        .map((run) => run.durationSeconds)
        .filter((d): d is number => d != null)
        .sort((a, b) => a - b)

    const byStartDesc = [...completed].sort((a, b) => (b.startedAt ?? '').localeCompare(a.startedAt ?? ''))
    const latestConclusion = byStartDesc[0]?.conclusion ?? null
    const lastFailureAt =
        completed
            .filter((run) => isDecisiveFailure(run.conclusion))
            .map((run) => run.startedAt)
            .filter((at): at is string => !!at)
            .sort()
            .at(-1) ?? null

    let state: WorkflowState
    if (completed.length === 0) {
        state = 'unknown'
    } else if (isDecisiveFailure(latestConclusion)) {
        state = 'failing'
    } else if (failures / completed.length >= DEGRADED_FAILURE_RATE) {
        state = 'degraded'
    } else {
        state = 'healthy'
    }

    return {
        state,
        totalRuns: runs.length,
        completedRuns: completed.length,
        passedRuns: passed,
        failures,
        running,
        reruns,
        passRate,
        medianSeconds: percentileSorted(durations, 0.5),
        p95Seconds: percentileSorted(durations, 0.95),
        lastFailureAt,
        latestConclusion,
    }
}

/**
 * Fleet verdict + rollups across all workflows in the window (the all-workflows page). State is the
 * worst the fleet is right now: every settled workflow red is "failing"; any red or flaky is "degraded";
 * otherwise "healthy". Runs and cost are summed across workflows; cost is null until any row carries it.
 */
export function computeFleetSummary(rows: FleetRow[]): FleetSummary {
    const workflowCount = rows.length
    const settledWorkflows = rows.filter((row) => row.latestRunFailed != null).length
    const failingNow = rows.filter((row) => row.latestRunFailed === true).length
    // Flaky = currently green but below the success-rate floor AND it has actually failed in the window.
    // The `lastFailureAt` gate keeps this aligned with the single-workflow verdict: a low success rate that
    // comes from skips/cancels (no decisive failures) reads as healthy, not flaky.
    const flakyNow = rows.filter(
        (row) =>
            row.latestRunFailed === false &&
            row.successRate != null &&
            row.successRate < FLAKY_SUCCESS_RATE &&
            row.lastFailureAt != null
    ).length
    const totalRuns = rows.reduce((sum, row) => sum + row.runCount, 0)

    // Completed-run-weighted, so a 3-run workflow can't move the fleet as much as a 3,000-run one.
    // (A previous-window twin is deliberately absent: the endpoint has no prev completed counts, so an
    // honest fleet-level delta isn't computable — don't fake one from unweighted per-row prev rates.)
    let completedRuns = 0
    let passedRuns = 0
    for (const row of rows) {
        for (const bucket of row.buckets ?? []) {
            completedRuns += bucket.completed
            passedRuns += bucket.successes
        }
    }
    const passRate = completedRuns > 0 ? passedRuns / completedRuns : null
    const rerunCycles = rows.reduce((sum, row) => sum + (row.rerunCycles ?? 0), 0)

    // Gate each cost field on whether any row carries a real value — free runners report null, and a
    // bare sum would turn "no cost data" into a misleading $0.00 / 0 min.
    const hasBillable = rows.some((row) => row.billableMinutes != null)
    const hasEstimatedCost = rows.some((row) => row.estimatedCostUsd != null)
    const billableMinutes = hasBillable ? rows.reduce((sum, row) => sum + (row.billableMinutes ?? 0), 0) : null
    const estimatedCostUsd = hasEstimatedCost ? rows.reduce((sum, row) => sum + (row.estimatedCostUsd ?? 0), 0) : null

    let state: WorkflowState
    if (workflowCount === 0 || settledWorkflows === 0) {
        // Workflows exist but none has a completed run yet — no evidence either way, same as the
        // single-workflow "unknown".
        state = 'unknown'
    } else if (failingNow > 0 && failingNow === settledWorkflows) {
        state = 'failing'
    } else if (failingNow > 0 || flakyNow > 0) {
        state = 'degraded'
    } else {
        state = 'healthy'
    }

    return {
        state,
        workflowCount,
        settledWorkflows,
        failingNow,
        flakyNow,
        totalRuns,
        passRate,
        rerunCycles,
        billableMinutes,
        estimatedCostUsd,
    }
}

/**
 * Roll a run's jobs up to a single cost figure, mirroring the backend cost model (logic/cost.py): only
 * self-hosted runners are billable, and a job contributes once it has settled (a non-null estimated cost).
 * `unsettledJobs` counts only billable jobs that haven't finished yet (no duration) — excluded from the
 * total and surfaced as a caveat so the number never silently inflates. A finished self-hosted job with no
 * cost is an excluded tier (the backend doesn't price non-Linux Depot runners), not "unsettled", so it's
 * left out of both. Returns null when there's nothing to show — no priced jobs and nothing still running
 * (every job free, or every billable job finished on an unpriced tier) — so the caller omits the tile rather
 * than render a dangling "—".
 */
export function summarizeRunCost(jobs: CostableJob[]): RunCostSummary | null {
    const billable = jobs.filter((job) => job.runner_provider === 'self_hosted')
    const costed = billable.filter((job) => job.estimated_cost_usd != null)
    // A null cost on a finished job means an unpriced tier (excluded), not "still running" — only a job
    // with no duration is genuinely unsettled.
    const unsettledJobs = billable.filter((job) => job.duration_seconds == null).length
    if (costed.length === 0 && unsettledJobs === 0) {
        // Nothing to report: no priced jobs and nothing still running (all free, or every billable job
        // finished on an unpriced tier). Omit the tile rather than render a dangling "—".
        return null
    }
    if (costed.length === 0) {
        // Billable jobs are still running but none has settled yet — keep the tile (with a "—" value +
        // caveat) rather than reporting a misleading $0.00 / 0 min for a run whose cost hasn't landed.
        return { billableMinutes: null, estimatedCostUsd: null, unsettledJobs }
    }
    const billableMinutes = costed.reduce((sum, job) => sum + (job.duration_seconds ?? 0) / 60, 0)
    const estimatedCostUsd = costed.reduce((sum, job) => sum + (job.estimated_cost_usd ?? 0), 0)
    return { billableMinutes, estimatedCostUsd, unsettledJobs }
}
