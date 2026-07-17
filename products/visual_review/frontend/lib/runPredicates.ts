import type { RunApi } from '../generated/api.schemas'

// A run with no PR is a default-branch (master/main) push: tracking-only, never approvable.
// CI submits these with purpose "observe", and the backend rejects approve/finalize on them,
// so the UI must never offer an approval that can't apply. The run API doesn't expose `purpose`
// yet, so PR presence is the proxy — it matches the backend's needs_review filter.
export function isReportingOnlyRun(run: RunApi | null): boolean {
    return !!run && run.pr_number == null
}
