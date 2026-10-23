import type { WorkflowRunDetailApi } from '../generated/api.schemas'

/** Keep engine and attempt distinct when runs share a compatible integer ID. */
export function jobCacheKey(
    runId: number,
    runAttempt: number | null,
    ciEngine?: WorkflowRunDetailApi['ci_engine']
): string {
    return `${ciEngine ? `${ciEngine}:` : ''}${runId}:${runAttempt ?? 'latest'}`
}
