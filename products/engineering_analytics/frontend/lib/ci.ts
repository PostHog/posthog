// The rollup counts the latest run per workflow on the PR's head_sha, not checks.

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
