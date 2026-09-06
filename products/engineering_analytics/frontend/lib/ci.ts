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
    // Runs that settled without a verdict (all cancelled, all skipped) leave nothing passing. Reading
    // that as a pass let a PR whose CI never ran satisfy the "CI passing" and "Ready to merge" filters.
    return rollup.passing > 0 ? 'passing' : 'inconclusive'
}

/** The runs the PR's author caused, dropping merge-queue gate attempts.
 *
 * A queue lands a PR by pushing its commits onto a gate branch, so each attempt adds a distinct head
 * SHA that the author never pushed. Anything counting authoring activity (pushes, re-run cycles) reads
 * this; anything measuring CI keeps the gate runs. The backend applies the same split in the PR list's
 * `runs_by_pr` rollup, and the two disagreeing is what made one PR report two different push counts.
 */
export function authoredRunsOnly<T extends { is_merge_queue: boolean }>(runs: T[]): T[] {
    return runs.filter((run) => !run.is_merge_queue)
}
