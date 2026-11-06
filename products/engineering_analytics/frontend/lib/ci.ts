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

export function ciStatusOf(rollup: CIRollup): CIStatus {
    if (rollup.runs === 0) {
        return 'none'
    }
    if (rollup.failing > 0) {
        return 'failing'
    }
    if (rollup.pending > 0) {
        return 'running'
    }
    if (rollup.passing > 0) {
        return 'passing'
    }
    // Every run was cancelled or skipped, which is not green.
    return 'inconclusive'
}
