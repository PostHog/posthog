// Pure derivation of a PR's CI verdict from its workflow-run rollup (latest run per workflow on the PR's
// head_sha, NOT per-check). An incomplete run is "running", never a pass/fail. Shared by the logic's
// selectors and the CI badge so the two never drift.

export type CIStatus = 'passing' | 'failing' | 'running' | 'inconclusive' | 'none'

export interface CIRollup {
    runs: number
    passing: number
    failing: number
    pending: number
    inconclusive: number
}

export function ciStatusOf(rollup: Pick<CIRollup, 'runs' | 'passing' | 'failing' | 'pending'>): CIStatus {
    if (rollup.runs === 0) {
        return 'none'
    }
    if (rollup.failing > 0) {
        return 'failing'
    }
    if (rollup.pending > 0) {
        return 'running'
    }
    // Nothing failed, pending, or passed means every run was cancelled or skipped, not green.
    return rollup.passing > 0 ? 'passing' : 'inconclusive'
}

/** Drops merge-queue gate attempts, whose head SHAs the author never pushed. Mirrors the backend's
 * `runs_by_pr` rollup, so push counts agree between the PR list and the PR detail page. */
export function authoredRunsOnly<T extends { is_merge_queue: boolean }>(runs: T[]): T[] {
    return runs.filter((run) => !run.is_merge_queue)
}
