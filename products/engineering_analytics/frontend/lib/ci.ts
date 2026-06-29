// Pure derivation of a PR's CI verdict from its workflow-run rollup. The rollup
// is workflow-level (collapsed to the latest run per workflow on the PR's
// head_sha) — NOT per-check. A run that has not completed is "running"
// (unsettled), never a pass/fail verdict. Shared by the logic's selectors and
// the CI badge so the two never drift.

export type CIStatus = 'passing' | 'failing' | 'running' | 'none'

export interface CIRollup {
    runs: number
    passing: number
    failing: number
    pending: number
}

export function ciStatusOf(rollup: Pick<CIRollup, 'runs' | 'failing' | 'pending'>): CIStatus {
    if (rollup.runs === 0) {
        return 'none'
    }
    if (rollup.failing > 0) {
        return 'failing'
    }
    if (rollup.pending > 0) {
        return 'running'
    }
    return 'passing'
}
