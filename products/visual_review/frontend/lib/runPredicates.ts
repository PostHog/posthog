import type { QuarantineSourceRunApi, RunApi } from '../generated/api.schemas'

// CI submits tracking-only runs with purpose "observe" (default-branch pushes and merge-queue
// runs), and the backend rejects approve/finalize on them. A merge-queue run keeps its PR number,
// so PR presence alone is not enough. A run with no PR also stays tracking-only, which matches
// the backend's needs_review filter.
export function isReportingOnlyRun(run: RunApi | null): boolean {
    return !!run && (run.purpose === 'observe' || run.pr_number == null)
}

// A merge-queue run's `pr_number` is Trunk's shadow PR, whose body lists every PR it tests.
// The branch names only the first of them. Keep the pattern in sync with `_MERGE_QUEUE_BRANCH_RE` in the backend.
export function mergeQueueBatchLeaderPrNumber(branch: string): number | null {
    const match = /^trunk-merge\/pr-(\d+)\//.exec(branch)
    return match ? Number(match[1]) : null
}

/** The PR a quarantine's source run came from, preferring the batch leader over Trunk's shadow PR. */
export function sourceRunPrNumber(run: QuarantineSourceRunApi): number | null {
    return mergeQueueBatchLeaderPrNumber(run.branch) ?? run.pr_number ?? null
}
