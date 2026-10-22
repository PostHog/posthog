import type { RunApi } from '../generated/api.schemas'

// CI submits tracking-only runs with purpose "observe" (default-branch pushes and merge-queue
// runs), and the backend rejects approve/finalize on them. A merge-queue run keeps its PR number,
// so PR presence alone is not enough. A run with no PR also stays tracking-only, which matches
// the backend's needs_review filter.
export function isReportingOnlyRun(run: RunApi | null): boolean {
    return !!run && (run.purpose === 'observe' || run.pr_number == null)
}

// A merge-queue run's `pr_number` is Trunk's temporary PR, which Trunk closes. The PR being merged
// is only in the branch name. Keep the pattern in sync with `_MERGE_QUEUE_BRANCH_RE` in the backend.
export function mergeQueueSourcePrNumber(branch: string): number | null {
    const match = /^trunk-merge\/pr-(\d+)\//.exec(branch)
    return match ? Number(match[1]) : null
}
