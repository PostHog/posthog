import type { WorkflowRunDetailApi } from '../generated/api.schemas'

/** Engine and attempt stay in the key, because runs of two engines can share an integer id. */
export function jobCacheKey(
    runId: number,
    runAttempt: number | null,
    ciEngine?: WorkflowRunDetailApi['ci_engine']
): string {
    return `${ciEngine ? `${ciEngine}:` : ''}${runId}:${runAttempt ?? 'latest'}`
}
